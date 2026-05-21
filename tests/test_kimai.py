from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from kimai_everyday.kimai import KimaiClient, KimaiError

BASE = "https://kimai.example.com"


@pytest.fixture()
def client():
    c = KimaiClient(BASE, "abc")
    yield c
    c.close()


@respx.mock
def test_get_me(client):
    respx.get(f"{BASE}/api/users/me").mock(
        return_value=httpx.Response(200, json={"id": 4, "alias": "Michael"})
    )
    assert client.get_me()["alias"] == "Michael"


@respx.mock
def test_url_with_trailing_api_is_normalized():
    c = KimaiClient(f"{BASE}/api/", "tok")
    respx.get(f"{BASE}/api/users/me").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    c.get_me()
    c.close()


@respx.mock
def test_list_projects_resolves_integer_customer_id(client):
    # Real Kimai shape: `customer` is an integer ID, resolved via /api/customers.
    respx.get(f"{BASE}/api/projects").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Website", "customer": 2},
                {"id": 5, "name": "Internal", "customer": None},
            ],
        )
    )
    respx.get(f"{BASE}/api/customers").mock(
        return_value=httpx.Response(200, json=[{"id": 2, "name": "ACME"}])
    )
    projects = client.list_projects()
    assert projects[0].label == "ACME / Website"
    assert projects[1].customer_name == "—"


@respx.mock
def test_list_projects_handles_inline_customer_object(client):
    # Defensive fallback: some Kimai configurations expand `customer` inline.
    respx.get(f"{BASE}/api/projects").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "Website", "customer": {"id": 2, "name": "ACME"}}],
        )
    )
    respx.get(f"{BASE}/api/customers").mock(
        return_value=httpx.Response(200, json=[])
    )
    projects = client.list_projects()
    assert projects[0].label == "ACME / Website"


@respx.mock
def test_list_activities_merges_globals_and_project_scoped(client):
    respx.get(f"{BASE}/api/activities", params={"project": "10", "visible": "1"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 100, "name": "Dev work", "project": 10}],
        )
    )
    respx.get(f"{BASE}/api/activities", params={"globals": "1", "visible": "1"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 200, "name": "Meetings", "project": None}],
        )
    )
    activities = client.list_activities(10)
    ids = {a.id for a in activities}
    assert ids == {100, 200}
    by_id = {a.id: a for a in activities}
    assert by_id[100].project_id == 10
    assert by_id[200].is_global


@respx.mock
def test_create_timesheet_sends_iso_with_offset(client):
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"id": 999})

    respx.post(f"{BASE}/api/timesheets").mock(side_effect=handler)
    tz = ZoneInfo("Europe/Berlin")
    client.create_timesheet(
        begin=datetime(2026, 5, 4, 8, 0, tzinfo=tz),
        end=datetime(2026, 5, 4, 12, 0, tzinfo=tz),
        project_id=1,
        activity_id=2,
        description="Coding",
    )
    import json

    body = json.loads(captured["body"])
    assert body["begin"] == "2026-05-04T08:00:00+02:00"
    assert body["end"] == "2026-05-04T12:00:00+02:00"
    assert body["project"] == 1
    assert body["activity"] == 2
    assert body["description"] == "Coding"


@respx.mock
def test_create_timesheet_omits_empty_description(client):
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"id": 999})

    respx.post(f"{BASE}/api/timesheets").mock(side_effect=handler)
    tz = ZoneInfo("UTC")
    client.create_timesheet(
        begin=datetime(2026, 1, 4, 8, 0, tzinfo=tz),
        end=datetime(2026, 1, 4, 12, 0, tzinfo=tz),
        project_id=1,
        activity_id=2,
        description=None,
    )
    import json

    assert "description" not in json.loads(captured["body"])


@respx.mock
def test_kimai_error_surfaces_body(client):
    respx.get(f"{BASE}/api/users/me").mock(
        return_value=httpx.Response(401, json={"message": "Invalid token"})
    )
    with pytest.raises(KimaiError) as exc:
        client.get_me()
    assert exc.value.status == 401
    assert "Invalid token" in (exc.value.body or "")


@respx.mock
def test_list_public_holidays_sends_datetime_local(client):
    route = respx.get(f"{BASE}/api/public-holidays").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"date": "2026-05-01", "name": "Tag der Arbeit"},
                {"date": "2026-05-14T00:00:00+02:00", "name": "Christi Himmelfahrt"},
            ],
        )
    )
    holidays = client.list_public_holidays(date(2026, 5, 1), date(2026, 5, 31))
    by_date = {h.date: h.name for h in holidays}
    assert by_date[date(2026, 5, 1)] == "Tag der Arbeit"
    assert by_date[date(2026, 5, 14)] == "Christi Himmelfahrt"
    # Kimai requires datetime-local format, not date-only.
    assert route.calls[0].request.url.params["begin"] == "2026-05-01T00:00:00"
    assert route.calls[0].request.url.params["end"] == "2026-05-31T23:59:59"
