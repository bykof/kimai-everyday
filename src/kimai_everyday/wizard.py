from __future__ import annotations

import concurrent.futures
import os
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from kimai_everyday import config as config_module
from kimai_everyday import resolution
from kimai_everyday.expansion import expand
from kimai_everyday.kimai import KimaiClient, KimaiError
from kimai_everyday.llm import LLMError, parse_pattern
from kimai_everyday.resolution import ActivityOutcome, ProjectOutcome
from kimai_everyday.types import (
    Activity,
    Config,
    ParsedPattern,
    PreviewRow,
    Project,
    Provenance,
    RowStatus,
)


def run(config: Config, *, dry_run: bool = False, sentence: str | None = None) -> int:
    """One-liner flow. The sentence may come from a CLI arg (sentence=...) or a prompt."""
    console = Console()
    tz = _resolve_timezone(config.timezone, console)

    api_key = config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print(
            "[red]No Anthropic API key configured and $ANTHROPIC_API_KEY is unset.[/red]\n"
            "Set one, or run with [bold]--classic[/bold] to use the multi-step wizard."
        )
        return 1

    if sentence is None or not sentence.strip():
        sentence = questionary.text(
            "Pattern (e.g. 'jeden Tag 9–17 im Mai für Acme Migration, refactoring')",
            validate=lambda v: bool(v.strip()) or "Required",
        ).ask()
        if sentence is None:
            return 1
    sentence = sentence.strip()

    with KimaiClient(config.kimai_url, config.kimai_token) as client:
        catalog = _fetch_catalog(client, console)
        if catalog is None:
            return 1
        projects, activities = catalog

        if not projects:
            console.print("[red]No visible projects on this Kimai instance.[/red]")
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
                    sentence,
                    today=today,
                    timezone=config.timezone,
                    api_key=api_key,
                    projects=projects,
                    activities=activities,
                )
            except LLMError as exc:
                console.print(f"[red]Could not parse the pattern:[/red] {exc}")
                console.print(
                    "[dim]Try [bold]--classic[/bold] for the multi-step wizard if the LLM is unavailable.[/dim]"
                )
                return 1

        if not parsed.slots:
            console.print(
                "[yellow]The pattern produced no dates. Nothing to do.[/yellow]"
            )
            _print_diagnostic(parsed, projects, activities, console)
            return 0

        project, project_provenance = _resolve_project_interactive(
            parsed, projects, config.last_project_id, console
        )
        if project is None:
            return 1

        activity, activity_provenance = _resolve_activity_interactive(
            parsed, activities, project, config.last_activity_id, console
        )
        if activity is None:
            return 1

        try:
            holidays = client.list_public_holidays(parsed.slots[0].date, parsed.slots[-1].date)
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

        _print_banner(
            project, project_provenance,
            activity, activity_provenance,
            parsed.description, console,
        )
        _render_preview(rows, project, activity, parsed.description, console)

        creatable = [r for r in rows if r.will_create]
        if not creatable:
            console.print("[yellow]No working-day entries to create after filtering.[/yellow]")
            return 0

        if dry_run:
            console.print("[bold]--dry-run set; stopping before any POST.[/bold]")
            return 0

        confirm = questionary.confirm(
            f"Create {sum(len(r.blocks) for r in creatable)} entries for "
            f"{project.label} / {activity.name}?",
            default=False,
        ).ask()
        if not confirm:
            console.print("Cancelled.")
            return 0

        successes, failures = _post_all(
            client, creatable, project, activity, parsed.description, tz, console
        )

        _render_summary(successes, failures, console)

        new_config = replace(
            config,
            last_project_id=project.id,
            last_activity_id=activity.id,
        )
        config_module.save(new_config)

    return 0 if not failures else 2


def run_classic(config: Config, *, dry_run: bool = False) -> int:
    """The original multi-step wizard: Project → Activity → Description → Sentence.

    Kept as an escape hatch when the LLM is unavailable, or when the user wants
    to drive project/activity by hand.
    """
    console = Console()
    tz = _resolve_timezone(config.timezone, console)

    api_key = config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print(
            "[red]No Anthropic API key configured and $ANTHROPIC_API_KEY is unset.[/red]"
        )
        return 1

    with KimaiClient(config.kimai_url, config.kimai_token) as client:
        project = pick_project_interactive(client, config.last_project_id, console)
        if project is None:
            return 1

        activity = pick_activity_interactive(client, project, config.last_activity_id, console)
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

        try:
            holidays = client.list_public_holidays(parsed.slots[0].date, parsed.slots[-1].date)
        except KimaiError as exc:
            console.print(f"[yellow]Could not fetch public holidays:[/yellow] {exc}")
            if exc.body:
                console.print(f"[dim]{exc.body[:500]}[/dim]")
            cont = questionary.confirm(
                "Continue without holiday filtering?", default=False
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


# -- helpers -----------------------------------------------------------------


def _fetch_catalog(
    client: KimaiClient, console: Console
) -> tuple[list[Project], list[Activity]] | None:
    """Fetch projects + activities in parallel. Returns None on failure (already printed)."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description="Loading catalog...", total=None)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_projects = ex.submit(client.list_projects)
            f_activities = ex.submit(client.list_all_activities)
            try:
                projects = f_projects.result()
                activities = f_activities.result()
            except KimaiError as exc:
                console.print(f"[red]Could not load catalog:[/red] {exc}")
                return None
    return projects, activities


def _resolve_project_interactive(
    parsed: ParsedPattern,
    projects: list[Project],
    last_project_id: int | None,
    console: Console,
) -> tuple[Project | None, Provenance | None]:
    outcome = resolution.resolve_project(parsed, projects, last_project_id)
    if outcome.resolved is not None:
        return outcome.resolved, outcome.provenance

    if outcome.candidates:
        picked = _shortlist_pick(
            outcome.candidates,
            label_fn=lambda p: p.label,
            prompt_title="Which project?",
            console=console,
        )
        if picked is None:
            # Escaped to full list.
            chosen = _project_picker(projects, last_project_id, console)
            return chosen, Provenance.AUTOCOMPLETE if chosen else None
        return picked, Provenance.DISAMBIGUATED

    # Unresolved: no LLM signal and no usable last-used → full picker.
    chosen = _project_picker(projects, last_project_id, console)
    return chosen, Provenance.AUTOCOMPLETE if chosen else None


def _resolve_activity_interactive(
    parsed: ParsedPattern,
    activities: list[Activity],
    project: Project,
    last_activity_id: int | None,
    console: Console,
) -> tuple[Activity | None, Provenance | None]:
    outcome = resolution.resolve_activity(parsed, activities, project, last_activity_id)
    if outcome.resolved is not None:
        return outcome.resolved, outcome.provenance

    scoped = resolution.activities_for_project(activities, project)
    if not scoped:
        console.print(f"[red]No visible activities for project {project.label}.[/red]")
        return None, None

    if outcome.candidates:
        picked = _shortlist_pick(
            outcome.candidates,
            label_fn=_activity_label,
            prompt_title="Which activity?",
            console=console,
        )
        if picked is None:
            chosen = _activity_picker(scoped, last_activity_id, console)
            return chosen, Provenance.AUTOCOMPLETE if chosen else None
        return picked, Provenance.DISAMBIGUATED

    chosen = _activity_picker(scoped, last_activity_id, console)
    return chosen, Provenance.AUTOCOMPLETE if chosen else None


def _shortlist_pick(candidates, *, label_fn, prompt_title: str, console: Console):
    """Numbered short-list with single-keystroke selection. None = escape to full picker."""
    console.print(f"\n[bold]{prompt_title}[/bold]")
    for i, c in enumerate(candidates, start=1):
        console.print(f"  [{i}] {label_fn(c)}")
    escape_n = len(candidates) + 1
    console.print(f"  [{escape_n}] none of these — show the full list")

    choices = [str(i) for i in range(1, escape_n + 1)]
    pick = questionary.select(
        "Pick one",
        choices=choices,
    ).ask()
    if pick is None:
        return None
    idx = int(pick)
    if idx == escape_n:
        return None
    return candidates[idx - 1]


def _project_picker(
    projects: list[Project], last_id: int | None, console: Console
) -> Project | None:
    """Reuse the original autocomplete picker as the recovery path."""
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


def _activity_picker(
    activities: list[Activity], last_id: int | None, console: Console
) -> Activity | None:
    by_label = {_activity_label(a): a for a in activities}
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


def _activity_label(a: Activity) -> str:
    suffix = "(global)" if a.is_global else f"(project #{a.project_id})"
    return f"{a.name} {suffix}"


def pick_project_interactive(
    client: KimaiClient, last_id: int | None, console: Console
) -> Project | None:
    """Classic-mode project picker (loads on demand, then prompts)."""
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
    return _project_picker(projects, last_id, console)


def pick_activity_interactive(
    client: KimaiClient, project: Project, last_id: int | None, console: Console
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
    return _activity_picker(activities, last_id, console)


def _provenance_note(prov: Provenance | None) -> str:
    if prov is None or prov == Provenance.LLM:
        return ""
    notes = {
        Provenance.LAST_USED: "[dim](last used — not in your sentence)[/dim]",
        Provenance.SINGLE: "[dim](only option)[/dim]",
        Provenance.DISAMBIGUATED: "[dim](you picked from candidates)[/dim]",
        Provenance.AUTOCOMPLETE: "[dim](you picked from the full list)[/dim]",
    }
    return f" {notes.get(prov, '')}"


def _print_banner(
    project: Project,
    project_provenance: Provenance | None,
    activity: Activity,
    activity_provenance: Provenance | None,
    description: str | None,
    console: Console,
) -> None:
    lines: list[str] = []
    if project.customer_name and project.customer_name != "—":
        lines.append(f"[bold]Customer:[/bold] {project.customer_name}")
    lines.append(
        f"[bold]Project:[/bold]  {project.name}{_provenance_note(project_provenance)}"
    )
    lines.append(
        f"[bold]Activity:[/bold] {_activity_label(activity)}{_provenance_note(activity_provenance)}"
    )
    if description:
        lines.append(f"[bold]Description:[/bold] [italic]{description}[/italic]")
    console.print()
    console.print(Panel("\n".join(lines), border_style="cyan", expand=False))


def _print_diagnostic(
    parsed: ParsedPattern,
    projects: list[Project],
    activities: list[Activity],
    console: Console,
) -> None:
    """Show what the LLM did parse, when slots came back empty."""
    project_label = "—"
    if parsed.project_id is not None:
        match = next((p for p in projects if p.id == parsed.project_id), None)
        project_label = match.label if match else f"id={parsed.project_id}"
    elif parsed.project_candidates:
        project_label = f"candidates={list(parsed.project_candidates)}"

    activity_label = "—"
    if parsed.activity_id is not None:
        match = next((a for a in activities if a.id == parsed.activity_id), None)
        activity_label = match.name if match else f"id={parsed.activity_id}"
    elif parsed.activity_candidates:
        activity_label = f"candidates={list(parsed.activity_candidates)}"

    console.print(
        f"[dim]Parsed: project={project_label}, activity={activity_label}, "
        f"description={parsed.description or '—'}[/dim]"
    )


def _resolve_timezone(name: str, console: Console) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        console.print(f"[red]Unknown timezone {name!r} in config; falling back to UTC.[/red]")
        return ZoneInfo("UTC")


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
