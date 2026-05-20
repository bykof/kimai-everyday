from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import questionary
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from kimai_everyday import config as config_module
from kimai_everyday.expansion import expand
from kimai_everyday.kimai import KimaiClient, KimaiError
from kimai_everyday.llm import LLMError, parse_pattern
from kimai_everyday.types import Activity, Config, PreviewRow, Project, RowStatus


def run(config: Config, *, dry_run: bool = False) -> int:
    console = Console()
    tz = _resolve_timezone(config.timezone, console)

    with KimaiClient(config.kimai_url, config.kimai_token) as client:
        project = _pick_project(client, config.last_project_id, console)
        if project is None:
            return 1

        activity = _pick_activity(client, project, config.last_activity_id, console)
        if activity is None:
            return 1

        description = questionary.text(
            "Description for all entries (optional)",
            default="",
        ).ask()
        if description is None:
            return 1
        description = description.strip() or None

        sentence = questionary.text(
            "Pattern (e.g. 'jeden Tag von 08–12 und 13–17 im Mai außer 15.–23.')",
            validate=lambda v: bool(v.strip()) or "Required",
        ).ask()
        if sentence is None:
            return 1

        api_key = config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            console.print(
                "[red]No Anthropic API key configured and $ANTHROPIC_API_KEY is unset.[/red]"
            )
            return 1

        today = datetime.now(tz).date()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task(description="Parsing pattern...", total=None)
            try:
                parsed = parse_pattern(
                    sentence, today=today, timezone=config.timezone, api_key=api_key
                )
            except LLMError as exc:
                console.print(f"[red]Could not parse the pattern:[/red] {exc}")
                return 1

        if not parsed.slots:
            console.print("[yellow]The pattern produced no dates. Nothing to do.[/yellow]")
            return 0

        begin_date = parsed.slots[0].date
        end_date = parsed.slots[-1].date
        try:
            holidays = client.list_public_holidays(begin_date, end_date)
        except KimaiError as exc:
            console.print(f"[yellow]Could not fetch public holidays:[/yellow] {exc}")
            if exc.body:
                console.print(f"[dim]{exc.body[:500]}[/dim]")
            console.print(
                "[dim]This is usually because the Kimai 'Work Contract' plugin "
                "is not installed on your instance.[/dim]"
            )
            cont = questionary.confirm(
                "Continue without holiday filtering? (Mon–Fri filter still applies; "
                "you'll need to spot holidays manually in the preview.)",
                default=False,
            ).ask()
            if not cont:
                return 1
            holidays = []

        rows = expand(parsed, holidays)
        _render_preview(rows, project, activity, description, console)

        creatable = [r for r in rows if r.will_create]
        if not creatable:
            console.print("[yellow]No working-day entries to create after filtering.[/yellow]")
            return 0

        if dry_run:
            console.print("[bold]--dry-run set; stopping before any POST.[/bold]")
            return 0

        confirm = questionary.confirm(
            f"Create {sum(len(r.blocks) for r in creatable)} timesheet entries across "
            f"{len(creatable)} day(s)?",
            default=False,
        ).ask()
        if not confirm:
            console.print("Cancelled.")
            return 0

        successes, failures = _post_all(
            client, creatable, project, activity, description, tz, console
        )

        _render_summary(successes, failures, console)

        new_config = replace(
            config,
            last_project_id=project.id,
            last_activity_id=activity.id,
        )
        config_module.save(new_config)

    return 0 if not failures else 2


def _resolve_timezone(name: str, console: Console) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        console.print(f"[red]Unknown timezone {name!r} in config; falling back to UTC.[/red]")
        return ZoneInfo("UTC")


def _pick_project(
    client: KimaiClient, last_id: int | None, console: Console
) -> Project | None:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description="Loading projects...", total=None)
        try:
            projects = client.list_projects()
        except KimaiError as exc:
            console.print(f"[red]Could not load projects:[/red] {exc}")
            return None
    if not projects:
        console.print("[red]No visible projects on this Kimai instance.[/red]")
        return None
    projects_sorted = sorted(projects, key=lambda p: p.label.lower())
    labels = [p.label for p in projects_sorted]
    by_label = {p.label: p for p in projects_sorted}
    default_label = next(
        (p.label for p in projects_sorted if p.id == last_id), labels[0]
    )
    pick = questionary.autocomplete(
        "Project",
        choices=labels,
        default=default_label,
        validate=lambda v: v in by_label or "Pick one of the suggested projects",
        match_middle=True,
        ignore_case=True,
    ).ask()
    if pick is None:
        return None
    return by_label[pick]


def _pick_activity(
    client: KimaiClient,
    project: Project,
    last_id: int | None,
    console: Console,
) -> Activity | None:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description="Loading activities...", total=None)
        try:
            activities = client.list_activities(project.id)
        except KimaiError as exc:
            console.print(f"[red]Could not load activities:[/red] {exc}")
            return None
    if not activities:
        console.print(f"[red]No visible activities for project {project.label}.[/red]")
        return None

    def label_for(a: Activity) -> str:
        suffix = "(global)" if a.is_global else f"({project.name})"
        return f"{a.name} {suffix}"

    by_label = {label_for(a): a for a in activities}
    labels = sorted(by_label.keys(), key=str.lower)
    default_label = next((lbl for lbl, a in by_label.items() if a.id == last_id), labels[0])
    pick = questionary.autocomplete(
        "Activity",
        choices=labels,
        default=default_label,
        validate=lambda v: v in by_label or "Pick one of the suggested activities",
        match_middle=True,
        ignore_case=True,
    ).ask()
    if pick is None:
        return None
    return by_label[pick]


def _render_preview(
    rows: list[PreviewRow],
    project: Project,
    activity: Activity,
    description: str | None,
    console: Console,
) -> None:
    table = Table(
        title=f"Preview — {project.label} / {activity.name}",
        show_lines=False,
        header_style="bold",
    )
    table.add_column("Date")
    table.add_column("Day")
    table.add_column("Time blocks")
    table.add_column("Status")

    for row in rows:
        if row.status is RowStatus.OK:
            status_text = "[green]✓[/green]"
            style = ""
        elif row.status is RowStatus.FORCED:
            status_text = (
                f"[green]✓ forced[/green] [dim]({row.reason})[/dim]"
                if row.reason
                else "[green]✓ forced[/green]"
            )
            style = ""
        elif row.status is RowStatus.HOLIDAY:
            status_text = f"[red]⛔ {row.reason}[/red]"
            style = "dim"
        else:  # WEEKEND
            status_text = f"[yellow]– {row.reason}[/yellow]"
            style = "dim"

        blocks_text = (
            ", ".join(f"{b.begin.strftime('%H:%M')}–{b.end.strftime('%H:%M')}" for b in row.blocks)
            if row.will_create
            else "—"
        )
        table.add_row(
            row.date.isoformat(),
            row.date.strftime("%a"),
            blocks_text,
            status_text,
            style=style or None,
        )

    console.print()
    console.print(table)
    creatable = [r for r in rows if r.will_create]
    total_entries = sum(len(r.blocks) for r in creatable)
    console.print(
        f"[bold]{total_entries} timesheet entries across {len(creatable)} day(s)[/bold]; "
        f"{len(rows) - len(creatable)} day(s) skipped."
    )
    if description:
        console.print(f"Description: [italic]{description}[/italic]")
    console.print()


def _post_all(
    client: KimaiClient,
    rows: list[PreviewRow],
    project: Project,
    activity: Activity,
    description: str | None,
    tz: ZoneInfo,
    console: Console,
) -> tuple[int, list[tuple[str, str]]]:
    failures: list[tuple[str, str]] = []
    successes = 0
    total = sum(len(r.blocks) for r in rows)

    with Progress(console=console) as progress:
        task = progress.add_task("Creating timesheets", total=total)
        for row in rows:
            for block in row.blocks:
                begin = datetime.combine(row.date, block.begin, tzinfo=tz)
                end = datetime.combine(row.date, block.end, tzinfo=tz)
                label = (
                    f"{row.date.isoformat()} "
                    f"{block.begin.strftime('%H:%M')}–{block.end.strftime('%H:%M')}"
                )
                try:
                    client.create_timesheet(
                        begin=begin,
                        end=end,
                        project_id=project.id,
                        activity_id=activity.id,
                        description=description,
                    )
                    successes += 1
                except KimaiError as exc:
                    detail = f"{exc.status or '?'}: {(exc.body or str(exc))[:200]}"
                    failures.append((label, detail))
                progress.update(task, advance=1)
    return successes, failures


def _render_summary(
    successes: int, failures: list[tuple[str, str]], console: Console
) -> None:
    console.print()
    if successes:
        console.print(f"[green]✓ Created {successes} timesheet(s).[/green]")
    if failures:
        console.print(f"[red]✕ {len(failures)} failure(s):[/red]")
        for label, detail in failures:
            console.print(f"  [dim]{label}[/dim] → {detail}")
        console.print(
            "[yellow]Re-run will NOT skip the entries that succeeded; edit the pattern to retry only the failed dates.[/yellow]"
        )


