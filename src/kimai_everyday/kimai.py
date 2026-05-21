from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from kimai_everyday.types import Activity, Project, PublicHoliday


def _merge_activities(globals_raw: list[dict[str, Any]], scoped_raw: list[dict[str, Any]]) -> list[Activity]:
    seen: set[int] = set()
    activities: list[Activity] = []
    for item in [*globals_raw, *scoped_raw]:
        aid = int(item["id"])
        if aid in seen:
            continue
        seen.add(aid)
        raw_project = item.get("project")
        project_id_value: int | None
        if raw_project is None:
            project_id_value = None
        elif isinstance(raw_project, dict):
            project_id_value = int(raw_project["id"])
        else:
            project_id_value = int(raw_project)
        activities.append(Activity(id=aid, name=item["name"], project_id=project_id_value))
    return activities


class KimaiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body

    def __str__(self) -> str:
        base = super().__str__()
        if self.body:
            snippet = self.body.strip().replace("\n", " ")[:300]
            return f"{base} — {snippet}"
        return base


class KimaiClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        # Allow base_url with or without trailing /api — normalize to a root we can join paths to.
        self._base_url = base_url.rstrip("/")
        if self._base_url.endswith("/api"):
            self._base_url = self._base_url[: -len("/api")]
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def __enter__(self) -> KimaiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise KimaiError(f"HTTP error contacting Kimai: {exc}") from exc
        if response.status_code >= 400:
            raise KimaiError(
                f"Kimai returned {response.status_code} for {method} {path}",
                status=response.status_code,
                body=response.text,
            )
        if not response.content:
            return None
        return response.json()

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/api/users/me")

    def list_projects(self, *, visible: int = 1) -> list[Project]:
        raw = self._request("GET", "/api/projects", params={"visible": visible})
        projects: list[Project] = []
        for item in raw:
            customer = item.get("customer") or {}
            customer_name = customer.get("name") if isinstance(customer, dict) else None
            projects.append(
                Project(
                    id=int(item["id"]),
                    name=item["name"],
                    customer_name=customer_name or "—",
                )
            )
        return projects

    def list_activities(self, project_id: int) -> list[Activity]:
        # The API returns project-linked activities when filtered by project; we additionally
        # fetch globals and merge, because the project filter excludes them.
        scoped_raw = self._request(
            "GET", "/api/activities", params={"project": project_id, "visible": 1}
        )
        globals_raw = self._request("GET", "/api/activities", params={"globals": 1, "visible": 1})
        return _merge_activities(globals_raw, scoped_raw)

    def list_all_activities(self) -> list[Activity]:
        # No `project` filter → all visible project-scoped activities across every project.
        # `globals=1` is required to also include globals; without it Kimai excludes them.
        scoped_raw = self._request("GET", "/api/activities", params={"visible": 1})
        globals_raw = self._request("GET", "/api/activities", params={"globals": 1, "visible": 1})
        return _merge_activities(globals_raw, scoped_raw)

    def list_public_holidays(self, begin: date, end: date) -> list[PublicHoliday]:
        # Kimai's `begin`/`end` query params are HTML5 datetime-local
        # (`YYYY-MM-DDTHH:MM:SS`). A bare date returns 400.
        raw = self._request(
            "GET",
            "/api/public-holidays",
            params={
                "begin": f"{begin.isoformat()}T00:00:00",
                "end": f"{end.isoformat()}T23:59:59",
            },
        )
        holidays: list[PublicHoliday] = []
        for item in raw:
            raw_date = item.get("date") or item.get("day") or item.get("begin")
            if raw_date is None:
                continue
            holidays.append(
                PublicHoliday(
                    date=date.fromisoformat(raw_date[:10]),
                    name=item.get("name") or item.get("description") or "Public holiday",
                )
            )
        return holidays

    def create_timesheet(
        self,
        *,
        begin: datetime,
        end: datetime,
        project_id: int,
        activity_id: int,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "begin": begin.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "project": project_id,
            "activity": activity_id,
        }
        if description:
            payload["description"] = description
        return self._request("POST", "/api/timesheets", json=payload)
