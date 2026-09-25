"""Klient Employer Public API i adapter JustJoin.IT / RocketJobs (0381).

Bez bazy i bez sieci: ``httpx.MockTransport`` + stały dostawca tokenu.
Pilnuje reguł, które kosztują pieniądze albo zostawiają ogłoszenie na
portalu: adopcja po ``externalId`` zamiast drugiego ``POST``, jedno
odświeżenie tokenu po 401, 409 przy zamykaniu = sukces, mapowanie błędów
RFC 7807 na zdania po polsku i flagę ponowienia.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.models.job_posting import Portal
from app.services.job_portals.base import (
    PortalConfig,
    PortalError,
    PortalGone,
    PortalReconnectRequired,
    PostingContent,
)
from app.services.job_portals.jjit import JjitAdapter, RocketJobsAdapter
from app.services.job_portals.jjit_client import JjitApi, portal_error

pytestmark = pytest.mark.asyncio

UNIT = "unit-1"
ADS = f"/employer/organization-units/{UNIT}/job-advertisements"


class Recorder:
    def __init__(self, routes):
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append(
            (
                request.method,
                request.url.path,
                body,
                request.headers.get("authorization", ""),
            )
        )
        for (method, path), handler in self.routes.items():
            if request.method == method and request.url.path.endswith(path):
                return handler(request)
        return httpx.Response(500, json={"title": "unexpected", "status": 500})


def _api(routes) -> tuple[JjitApi, Recorder]:
    recorder = Recorder(routes)
    issued: list[bool] = []

    async def token(force: bool) -> str:
        # Każde żądanie pobiera token; wymuszone odświeżenie daje nowy.
        issued.append(force)
        return "t2" if force else "t1"

    api = JjitApi(
        token, transport=httpx.MockTransport(recorder), base_url="https://api.test"
    )
    api.issued = issued  # type: ignore[attr-defined]
    return api, recorder


def _content(**overrides) -> PostingContent:
    job = {
        "title": "Java Developer",
        "subtitle": "rozwój platformy",
        "about": "Opis projektu.",
        "must": [{"name": "Java", "note": None}],
        "nice": ["Kafka"],
        "params": {},
        "show": {"must": True, "nice": True, "params": True, "process": True},
    }
    base = dict(
        title="Java Developer",
        job=job,
        apply_url="https://kariera.test/r/java",
        options={
            "category": "java",
            "experience_level": "senior",
            "working_time": "full_time",
            "workplace_type": "remote",
            "city": "Warszawa",
        },
        external_ref="nexus-posting-5",
    )
    base.update(overrides)
    return PostingContent(**base)


def _adapter(cls, api):
    adapter = cls(PortalConfig(portal=cls.portal, enabled=True), api=api)

    async def unit():
        return UNIT

    adapter._unit = unit  # type: ignore[method-assign]
    return adapter


def _skills(request):
    names = json.loads(request.content)["skillNames"]
    return httpx.Response(200, json=[{"id": f"id-{n}", "name": n} for n in names])


BALANCE = {
    "codes": [
        {"name": "KOD", "maxUsage": 3, "currentUsage": 0, "jobBoard": "rocketjobs"}
    ],
    "subscriptions": [],
}


async def test_publish_adopts_existing_ad_instead_of_second_post():
    routes = {
        ("GET", ADS): lambda r: httpx.Response(
            200,
            json={
                "items": [
                    {"id": "ad-9", "slug": "java-dev", "externalId": "nexus-posting-5"}
                ]
            },
        ),
    }
    api, rec = _api(routes)
    result = await _adapter(RocketJobsAdapter, api).publish(_content())
    assert result.external_id == "ad-9"
    assert result.url == "https://rocketjobs.pl/oferta-pracy/java-dev"
    assert [c[0] for c in rec.calls] == ["GET"]


async def test_publish_ignores_list_item_with_foreign_external_id():
    routes = {
        ("GET", ADS): lambda r: httpx.Response(
            200, json={"items": [{"id": "x", "externalId": "someone-else"}]}
        ),
        ("GET", "/payments/balance"): lambda r: httpx.Response(200, json=BALANCE),
        ("PUT", "/rocketjobs/skills"): _skills,
        ("POST", ADS): lambda r: httpx.Response(
            200,
            json={"jobBoard": "rocketjobs", "id": "ad-1", "title": "T", "slug": "t"},
        ),
    }
    api, rec = _api(routes)
    result = await _adapter(RocketJobsAdapter, api).publish(_content())
    assert result.external_id == "ad-1"
    post = next(c for c in rec.calls if c[0] == "POST")
    body = post[2]
    assert body["jobBoard"] == "rocketjobs"
    assert body["payment"] == {"type": "Code", "id": "KOD"}
    assert body["externalId"] == "nexus-posting-5"
    assert [r["skillName"] for r in body["requirements"]] == ["Java", "Kafka"]


async def test_jjit_sends_only_required_skills():
    routes = {
        ("GET", ADS): lambda r: httpx.Response(200, json={"items": []}),
        ("GET", "/payments/balance"): lambda r: httpx.Response(
            200,
            json={
                "codes": [
                    {
                        "name": "J",
                        "maxUsage": 1,
                        "currentUsage": 0,
                        "jobBoard": "justjoinit",
                    }
                ]
            },
        ),
        ("PUT", "/justjoinit/skills"): _skills,
        ("POST", ADS): lambda r: httpx.Response(200, json={"id": "ad-2", "slug": "s"}),
    }
    api, rec = _api(routes)
    result = await _adapter(JjitAdapter, api).publish(_content())
    assert result.url == "https://justjoin.it/job-offer/s"
    skills_call = next(c for c in rec.calls if c[0] == "PUT")
    assert skills_call[2] == {"skillNames": ["Java"]}
    body = next(c for c in rec.calls if c[0] == "POST")[2]
    assert all(r["required"] for r in body["requirements"])


async def test_publish_without_payment_does_not_post():
    routes = {
        ("GET", ADS): lambda r: httpx.Response(200, json={"items": []}),
        ("GET", "/payments/balance"): lambda r: httpx.Response(
            200, json={"codes": [], "subscriptions": []}
        ),
    }
    api, rec = _api(routes)
    with pytest.raises(PortalError) as exc:
        await _adapter(RocketJobsAdapter, api).publish(_content())
    assert not exc.value.retryable
    assert "Brak kodów" in exc.value.message
    assert all(c[0] != "POST" for c in rec.calls)


async def test_invalid_options_fail_before_any_request():
    api, rec = _api({})
    with pytest.raises(PortalError) as exc:
        await _adapter(RocketJobsAdapter, api).publish(_content(options={}))
    assert "kategorię" in exc.value.message
    assert rec.calls == []


async def test_401_refreshes_token_once_then_succeeds():
    responses = iter([httpx.Response(401), httpx.Response(200, json={"sub": "u"})])
    api, rec = _api({("GET", "/oauth/me"): lambda r: next(responses)})
    assert await api.me() == {"sub": "u"}
    assert api.issued == [False, True]  # type: ignore[attr-defined]
    assert [c[3] for c in rec.calls] == ["Bearer t1", "Bearer t2"]


async def test_second_401_means_reconnect():
    api, _ = _api({("GET", "/oauth/me"): lambda r: httpx.Response(401)})
    with pytest.raises(PortalReconnectRequired):
        await api.me()


async def test_update_reads_current_ad_and_sends_full_body():
    current = {
        "id": "ad-1",
        "slug": "s",
        "title": "Stary tytuł",
        "informationClause": "Klauzula",
        "contact": {"name": "A", "email": "a@b.pl", "phone": "1"},
    }
    routes = {
        ("GET", f"{ADS}/ad-1"): lambda r: httpx.Response(200, json=current),
        ("PUT", "/rocketjobs/skills"): _skills,
        ("PUT", f"{ADS}/ad-1"): lambda r: httpx.Response(204),
    }
    api, rec = _api(routes)
    result = await _adapter(RocketJobsAdapter, api).update("ad-1", _content())
    put = [c for c in rec.calls if c[0] == "PUT" and c[1].endswith("/ad-1")][0]
    assert put[2]["informationClause"] == "Klauzula"
    assert "title" not in put[2] and "payment" not in put[2]
    assert result.extra.get("title_unchanged") is True


async def test_close_treats_409_and_404_as_done():
    for status in (409, 404):
        api, _ = _api(
            {
                ("DELETE", f"{ADS}/ad-1"): lambda r, s=status: httpx.Response(
                    s, json={"status": s}
                )
            }
        )
        await _adapter(RocketJobsAdapter, api).unpublish("ad-1")


async def test_close_other_error_is_raised():
    api, _ = _api({("DELETE", f"{ADS}/ad-1"): lambda r: httpx.Response(403)})
    with pytest.raises(PortalError):
        await _adapter(RocketJobsAdapter, api).unpublish("ad-1")


@pytest.mark.parametrize(
    ("status", "body", "retryable", "fragment"),
    [
        (429, {}, True, "chwilowo"),
        (503, {"traceId": "tr-1"}, True, "tr-1"),
        (
            422,
            {
                "title": "validation.errors",
                "errors": [
                    {
                        "propertyName": "EmploymentTypes[0].Salary.To",
                        "errorMessage": "too big",
                    }
                ],
            },
            False,
            "EmploymentTypes[0].Salary.To: too big",
        ),
        (422, {"title": "hiring.company.logo.required"}, False, "logo"),
        (403, {}, False, "uprawnień"),
    ],
)
async def test_error_mapping(status, body, retryable, fragment):
    error = portal_error(
        httpx.Response(status, json=body, request=httpx.Request("GET", "https://x")),
        action="t",
    )
    assert error.retryable is retryable
    assert error.status == status
    assert fragment in error.message


async def test_404_maps_to_gone():
    error = portal_error(
        httpx.Response(404, json={"title": "job.advertisement.not.found"}),
        action="t",
    )
    assert isinstance(error, PortalGone)


async def test_timeout_is_retryable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    api = JjitApi(
        lambda force: _token(),
        transport=httpx.MockTransport(boom),
        base_url="https://api.test",
    )
    with pytest.raises(PortalError) as exc:
        await api.me()
    assert exc.value.retryable


async def _token() -> str:
    return "t"


def test_both_boards_are_registered_as_separate_portals():
    from app.services import job_portals

    assert job_portals.ADAPTERS[Portal.rocketjobs] is RocketJobsAdapter
    assert job_portals.ADAPTERS[Portal.justjoinit] is JjitAdapter


async def test_close_without_id_finds_ad_by_external_ref():
    routes = {
        ("GET", ADS): lambda r: httpx.Response(
            200,
            json={"items": [{"id": "ad-7", "externalId": "nexus-job-5-rocketjobs"}]},
        ),
        ("DELETE", f"{ADS}/ad-7"): lambda r: httpx.Response(204),
    }
    api, rec = _api(routes)
    await _adapter(RocketJobsAdapter, api).unpublish(
        None, external_ref="nexus-job-5-rocketjobs"
    )
    assert [c[0] for c in rec.calls] == ["GET", "DELETE"]


async def test_close_without_id_and_no_ad_is_a_no_op():
    api, rec = _api({("GET", ADS): lambda r: httpx.Response(200, json={"items": []})})
    await _adapter(RocketJobsAdapter, api).unpublish(
        None, external_ref="nexus-job-5-rocketjobs"
    )
    assert [c[0] for c in rec.calls] == ["GET"]


async def test_close_works_with_the_portal_flag_off():
    api, rec = _api({("DELETE", f"{ADS}/ad-1"): lambda r: httpx.Response(204)})
    adapter = RocketJobsAdapter(
        PortalConfig(portal=Portal.rocketjobs, enabled=False), api=api
    )

    async def unit():
        return UNIT

    adapter._unit = unit  # type: ignore[method-assign]
    await adapter.unpublish("ad-1")
    assert rec.calls[0][0] == "DELETE"
    with pytest.raises(PortalError):
        await adapter.publish(_content())


async def test_create_without_id_resolves_it_by_external_ref():
    lists = iter(
        [
            httpx.Response(200, json={"items": []}),
            httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "ad-3", "slug": "s", "externalId": "nexus-posting-5"}
                    ]
                },
            ),
        ]
    )
    routes = {
        ("GET", ADS): lambda r: next(lists),
        ("GET", "/payments/balance"): lambda r: httpx.Response(200, json=BALANCE),
        ("PUT", "/rocketjobs/skills"): _skills,
        ("POST", ADS): lambda r: httpx.Response(201),
    }
    api, _ = _api(routes)
    result = await _adapter(RocketJobsAdapter, api).publish(_content())
    assert result.external_id == "ad-3"


async def test_create_without_id_and_not_found_is_retryable():
    routes = {
        ("GET", ADS): lambda r: httpx.Response(200, json={"items": []}),
        ("GET", "/payments/balance"): lambda r: httpx.Response(200, json=BALANCE),
        ("PUT", "/rocketjobs/skills"): _skills,
        ("POST", ADS): lambda r: httpx.Response(201),
    }
    api, _ = _api(routes)
    with pytest.raises(PortalError) as exc:
        await _adapter(RocketJobsAdapter, api).publish(_content())
    assert exc.value.retryable
