from __future__ import annotations

import os
import stat
import sys
import tomllib
from pathlib import Path

import questionary
import tomli_w
from rich.console import Console

from kimai_everyday.kimai import KimaiClient, KimaiError
from kimai_everyday.types import Config

CONFIG_FILENAME = "config.toml"
APP_DIR_NAME = "kimai-everyday"


def config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_DIR_NAME / CONFIG_FILENAME


def load() -> Config | None:
    path = config_path()
    if not path.is_file():
        return None
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return Config(
        kimai_url=data["kimai_url"],
        kimai_token=data["kimai_token"],
        anthropic_api_key=data.get("anthropic_api_key") or None,
        timezone=data.get("timezone") or _default_timezone(),
        last_project_id=data.get("last_project_id"),
        last_activity_id=data.get("last_activity_id"),
    )


def save(config: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "kimai_url": config.kimai_url,
        "kimai_token": config.kimai_token,
        "timezone": config.timezone,
    }
    if config.anthropic_api_key:
        payload["anthropic_api_key"] = config.anthropic_api_key
    if config.last_project_id is not None:
        payload["last_project_id"] = config.last_project_id
    if config.last_activity_id is not None:
        payload["last_activity_id"] = config.last_activity_id
    path.write_bytes(tomli_w.dumps(payload).encode("utf-8"))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _default_timezone() -> str:
    # Best-effort: try /etc/localtime symlink (macOS/Linux). Fall back to UTC.
    try:
        link = os.readlink("/etc/localtime")
    except (OSError, NotImplementedError):
        return "UTC"
    # link looks like "/var/db/timezone/zoneinfo/Europe/Berlin" or
    # "/usr/share/zoneinfo/Europe/Berlin" depending on OS.
    marker = "/zoneinfo/"
    idx = link.find(marker)
    if idx == -1:
        return "UTC"
    return link[idx + len(marker) :]


def run_setup(existing: Config | None = None) -> Config:
    console = Console()
    path = config_path()
    if existing is None:
        console.print(f"[bold]No config found at {path}.[/bold] Let's set it up.\n")
    else:
        console.print(f"[bold]Updating config at {path}.[/bold] Press Enter to keep current values.\n")

    kimai_url = questionary.text(
        "Kimai base URL (e.g. https://kimai.example.com)",
        default=existing.kimai_url if existing else "",
        validate=lambda v: bool(v.strip()) or "Required",
    ).ask()
    if kimai_url is None:
        raise SystemExit(1)

    if existing:
        token_prompt = "Kimai API token (Enter to keep existing)"
        token_validator = lambda v: True  # noqa: E731 — empty means "keep existing"
    else:
        token_prompt = "Kimai API token"
        token_validator = lambda v: bool(v.strip()) or "Required"  # noqa: E731
    kimai_token = questionary.password(token_prompt, validate=token_validator).ask()
    if kimai_token is None:
        raise SystemExit(1)
    if existing and not kimai_token.strip():
        kimai_token = existing.kimai_token

    if existing and existing.anthropic_api_key:
        anthropic_prompt = "Anthropic API key (Enter to keep existing, '-' to clear)"
    else:
        anthropic_prompt = "Anthropic API key (leave empty to use $ANTHROPIC_API_KEY)"
    anthropic_key = questionary.password(anthropic_prompt).ask()
    if anthropic_key is None:
        raise SystemExit(1)
    anthropic_key = anthropic_key.strip()
    if existing and existing.anthropic_api_key and not anthropic_key:
        anthropic_key = existing.anthropic_api_key
    elif anthropic_key == "-":
        anthropic_key = None
    else:
        anthropic_key = anthropic_key or None

    timezone = questionary.text(
        "Timezone (IANA name)",
        default=existing.timezone if existing else _default_timezone(),
        validate=lambda v: bool(v.strip()) or "Required",
    ).ask()
    if timezone is None:
        raise SystemExit(1)

    console.print()
    console.print("Testing Kimai connection...", end=" ")
    try:
        with KimaiClient(kimai_url.strip(), kimai_token.strip()) as client:
            me = client.get_me()
    except KimaiError as exc:
        console.print(f"[red]failed.[/red]\n{exc}")
        if exc.body:
            console.print(f"[dim]{exc.body}[/dim]")
        sys.exit(1)
    display_name = me.get("alias") or me.get("username") or me.get("email") or "?"
    console.print(f"[green]ok.[/green] Authenticated as [bold]{display_name}[/bold] (user #{me.get('id')}).")

    config = Config(
        kimai_url=kimai_url.strip(),
        kimai_token=kimai_token.strip(),
        anthropic_api_key=anthropic_key,
        timezone=timezone.strip(),
        last_project_id=existing.last_project_id if existing else None,
        last_activity_id=existing.last_activity_id if existing else None,
    )
    save(config)
    console.print(f"Saved to {path} (chmod 600).\n")
    return config


def load_or_setup() -> Config:
    cfg = load()
    if cfg is None:
        return run_setup()
    return cfg
