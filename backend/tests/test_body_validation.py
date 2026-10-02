"""Błędne ciało żądania w trasach, które sprawdzają je ręcznie: odmowa, nie 500.

FastAPI zamienia na 422 tylko błędy modeli zadeklarowanych w sygnaturze trasy.
Trasa, która przyjmuje ciało jako słownik (albo sprawdza model ponownie po
PATCH-u), rzuca ``pydantic.ValidationError`` z ciała handlera — do 02.10.2026
kończyło się to odpowiedzią 500, a treść wyjątku z wartościami z żądania szła
do logu i do Sentry.

Trzy poziomy:

1. ``validated_body`` / ``invalid_body`` — bez bazy.
2. Strażnik: żaden handler nie buduje modelu z surowego ciała żądania poza
   helperem albo blokiem ``try`` — bez bazy.
3. Trasy przez ``app_client``: odmowa i brak zapisu (baza; sprawdza CI).
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import func, select

from app.api.body_validation import INVALID_BODY, invalid_body, validated_body
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.champion_suggestion import (
    RAW_DESCRIPTION_LIMITS,
    GenerateFromJdPayload,
)

BACKEND = Path(__file__).resolve().parents[1]


# ── 1. Helper ────────────────────────────────────────────────────────────────


class _Sample(BaseModel):
    job_id: int = Field(gt=0)
    title: str = Field(min_length=3, max_length=10)
    tags: list[int] = Field(default_factory=list)


class _Pair(BaseModel):
    left: bool = True
    right: bool = True

    @model_validator(mode="after")
    def _one_side(self) -> "_Pair":
        if not (self.left or self.right):
            raise ValueError("co najmniej jedna strona")
        return self


def test_valid_body_is_returned_as_the_model() -> None:
    body = validated_body(_Sample, {"job_id": "7", "title": "Java"})
    assert (body.job_id, body.title, body.tags) == (7, "Java", [])


def test_invalid_body_is_a_polish_422_naming_the_fields() -> None:
    with pytest.raises(HTTPException) as raised:
        validated_body(_Sample, {"job_id": 0, "title": "x", "tags": [1, "sekret"]})
    assert raised.value.status_code == 422
    assert raised.value.detail == (
        "Nieprawidłowe dane żądania. Pola do poprawy: job_id, tags.1, title."
    )


def test_refusal_carries_neither_the_values_nor_the_pydantic_dump() -> None:
    with pytest.raises(HTTPException) as raised:
        validated_body(_Sample, {"job_id": 1, "title": "tajna-wartosc-z-zadania"})
    detail = raised.value.detail
    assert isinstance(detail, str)
    assert "tajna-wartosc" not in detail
    assert "pydantic" not in detail and "input_value" not in detail
    # `from None`: wyjątek Pydantica (z wartościami) nie jedzie w łańcuchu.
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("payload", [[1, 2], "tekst", 5, None])
def test_body_that_is_not_an_object_gets_the_plain_message(payload: object) -> None:
    with pytest.raises(HTTPException) as raised:
        validated_body(_Sample, payload)
    assert raised.value.status_code == 422
    assert raised.value.detail == INVALID_BODY


def test_model_level_error_has_no_field_list() -> None:
    with pytest.raises(HTTPException) as raised:
        validated_body(_Pair, {"left": False, "right": False})
    assert raised.value.detail == INVALID_BODY


def test_own_message_replaces_the_generic_one() -> None:
    with pytest.raises(HTTPException) as raised:
        validated_body(_Sample, {}, "Wybierz rekrutację.")
    assert (raised.value.status_code, raised.value.detail) == (
        422,
        "Wybierz rekrutację.",
    )


def test_field_list_is_capped_at_five() -> None:
    class _Wide(BaseModel):
        a: int
        b: int
        c: int
        d: int
        e: int
        f: int
        g: int

    with pytest.raises(ValidationError) as raised:
        _Wide.model_validate({})
    assert invalid_body(raised.value).detail == (
        "Nieprawidłowe dane żądania. Pola do poprawy: a, b, c, d, e."
    )


def test_jd_message_states_the_limits_the_schema_enforces() -> None:
    low, high = (
        int(n.replace(" ", "")) for n in re.findall(r"\d[\d ]*", RAW_DESCRIPTION_LIMITS)
    )
    for length, accepted in (
        (low - 1, False),
        (low, True),
        (high, True),
        (high + 1, False),
    ):
        try:
            GenerateFromJdPayload(raw_description="x" * length)
        except ValidationError:
            assert not accepted, f"{length} znaków powinno przejść"
        else:
            assert accepted, f"{length} znaków powinno zostać odrzucone"


# ── 2. Strażnik: ręczna walidacja surowego ciała ─────────────────────────────

_RAW_BODY = re.compile(
    r"^(Annotated\[)?\s*(Optional\[)?\s*(dict|Dict|list|List|Any|Mapping)\b"
)
_CATCHING = {"ValidationError", "PydanticValidationError", "ValueError", "Exception"}
_VALIDATORS = {
    "model_validate",
    "model_validate_json",
    "validate_python",
    "validate_json",
}
_ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _caught_names(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"Exception"}
    names: set[str] = set()
    for node in ast.walk(handler.type):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _source_name(node: ast.AST) -> str | None:
    """Nazwa, z której powstaje wartość: `x`, `x or {}`, `dict(x)`, `{**x}`."""
    while True:
        if isinstance(node, ast.BoolOp):
            node = node.values[0]
        elif isinstance(node, ast.Await):
            node = node.value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"dict", "list"}
            and len(node.args) == 1
        ):
            node = node.args[0]
        elif (
            isinstance(node, ast.Dict) and len(node.keys) == 1 and node.keys[0] is None
        ):
            node = node.values[0]
        else:
            return node.id if isinstance(node, ast.Name) else None


def _reads_request_body(node: ast.AST) -> bool:
    """`request.json()` / `request.body()` — ciało czytane z pominięciem FastAPI."""
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in {"json", "body"}
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "request"
        for call in ast.walk(node)
    )


def _is_route(function: ast.AST) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in _ROUTE_METHODS
        for decorator in getattr(function, "decorator_list", [])
    )


def _raw_names(function: ast.AST) -> tuple[set[str], set[str]]:
    """(parametry o surowym typie i ich aliasy, nazwy z `request.json()`).

    Surowy typ = ``dict`` / ``list`` / ``Any`` / ``Mapping`` (także z ``None``
    i w ``Annotated[...]``): tak wygląda ciało żądania, którego FastAPI nie
    sprawdziło modelem.
    """
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    parameters = {
        a.arg
        for a in arguments
        if a.annotation is not None and _RAW_BODY.match(ast.unparse(a.annotation))
    }
    from_request: set[str] = set()
    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    ]
    changed = True
    while changed:
        changed = False
        for node in assignments:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            source = _source_name(node.value)
            if _reads_request_body(node.value) or source in from_request:
                group = from_request
            elif source in parameters:
                group = parameters
            else:
                continue
            if not names <= group:
                group |= names
                changed = True
    return parameters, from_request


def _unguarded_manual_validations(root: Path) -> list[str]:
    """Model budowany z surowego ciała żądania poza ``try``.

    Dwa zapisy: ``Model.model_validate(<surowe>)`` (także ``TypeAdapter``)
    w dowolnej funkcji oraz ``Model(**<surowe>)`` — ten drugi tylko dla ciała
    trasy i ``request.json()``, bo pomocnicy rozpakowują tak dane wewnętrzne.
    """
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        raw_by_function: dict[ast.AST, tuple[set[str], set[str]]] = {}
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            validated: list[ast.AST] = []
            unpacked: list[ast.AST] = []
            if isinstance(call.func, ast.Attribute):
                callee = call.func.attr
                if callee in _VALIDATORS and call.args:
                    validated.append(call.args[0])
            else:
                callee = getattr(call.func, "id", "")
            if callee[:1].isupper():
                unpacked = [k.value for k in call.keywords if not k.arg]
            if not validated and not unpacked:
                continue
            guarded = False
            function = None
            node: ast.AST = call
            while node in parents:
                parent = parents[node]
                if (
                    isinstance(parent, ast.Try)
                    and node in parent.body
                    and any(_caught_names(h) & _CATCHING for h in parent.handlers)
                ):
                    guarded = True
                if function is None and isinstance(parent, _FUNCTIONS):
                    function = parent
                node = parent
            if guarded or function is None:
                continue
            if function not in raw_by_function:
                raw_by_function[function] = _raw_names(function)
            parameters, from_request = raw_by_function[function]
            body = parameters | from_request
            route_body = (parameters if _is_route(function) else set()) | from_request
            if (
                any(_reads_request_body(value) for value in (*validated, *unpacked))
                or {_source_name(value) for value in validated} & body
                or {_source_name(value) for value in unpacked} & route_body
            ):
                hits.append(f"{path.relative_to(root)}:{call.lineno} {function.name}()")
    return hits


def test_no_handler_validates_a_raw_body_outside_the_helper() -> None:
    hits = _unguarded_manual_validations(BACKEND / "app" / "api")
    assert hits == [], (
        "Model budowany z surowego słownika poza `try` (app/api/…). Dane "
        "z żądania sprawdzaj przez `validated_body` — inaczej błędne ciało "
        "kończy się 500 zamiast 422. Dane wewnętrzne: złap `ValidationError` "
        "i zostaw błąd serwera.\n  " + "\n  ".join(hits)
    )


def test_the_guard_sees_an_unguarded_call(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "async def handler(payload: dict | None = None):\n"
        "    return Model.model_validate(payload or {})\n"
        "async def fine(payload: dict):\n"
        "    try:\n"
        "        return Model.model_validate(payload)\n"
        "    except ValidationError:\n"
        "        raise\n"
        "async def internal(row: Row):\n"
        "    return Model.model_validate(row)\n",
        encoding="utf-8",
    )
    hits = _unguarded_manual_validations(tmp_path)
    assert len(hits) == 1 and hits[0].endswith(":2 handler()")


def test_the_guard_sees_the_other_ways_of_building_a_model(tmp_path: Path) -> None:
    """Zapisy, których strażnik do 02.10.2026 nie widział."""
    (tmp_path / "bad.py").write_text(
        "@router.post('/a')\n"
        "async def unpacked(payload: dict):\n"
        "    return Model(**payload)\n"
        "@router.post('/b')\n"
        "async def annotated(payload: Annotated[dict, Body()]):\n"
        "    return Model.model_validate(payload)\n"
        "@router.post('/c')\n"
        "async def from_request(request: Request):\n"
        "    raw = await request.json()\n"
        "    return Model(**raw)\n"
        "@router.post('/d')\n"
        "async def aliased(payload: dict | None = None):\n"
        "    data = payload or {}\n"
        "    return Model.model_validate(data)\n"
        "@router.post('/e')\n"
        "async def adapter(payload: list):\n"
        "    return TypeAdapter(list[Item]).validate_python(payload)\n"
        "@router.post('/inline')\n"
        "async def inline(request: Request):\n"
        "    return Model(**(await request.json()))\n"
        "@router.post('/f')\n"
        "async def fine(request: Request):\n"
        "    try:\n"
        "        return Model(**(await request.json()))\n"
        "    except ValidationError:\n"
        "        raise\n"
        "def helper(result: dict):\n"
        "    return Response(**result)\n"
        "@router.post('/g')\n"
        "async def declared(body: Model, db: Any = None):\n"
        "    return Other(**body.model_dump())\n",
        encoding="utf-8",
    )
    hits = _unguarded_manual_validations(tmp_path)
    assert [hit.split(" ")[1] for hit in hits] == [
        "unpacked()",
        "annotated()",
        "from_request()",
        "aliased()",
        "adapter()",
        "inline()",
    ], hits


# ── 3. Trasy (baza) ──────────────────────────────────────────────────────────


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _login_as(
    app_client: AsyncClient, role: UserRole, *, profile_completed: bool = True
) -> tuple[dict[str, str], int]:
    tag = _tag()
    password = f"T3st_{tag}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"body-422-{role.value}-{tag}@example.com",
            password_hash=hash_password(password),
            name=f"Body {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=profile_completed,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
        email = user.email
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user_id


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = _tag()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Body 422 Demo {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Body 422 {tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    tag = _tag()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Body",
            lastname=f"Przykladowa-{tag}",
            email=f"body-422-cand-{tag}@example.com",
            status=CandidateStatus("active"),
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


def _refused(resp, *fields: str) -> None:
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and detail.startswith(INVALID_BODY), detail
    for field in fields:
        assert field in detail, detail


async def test_linking_a_note_refuses_a_malformed_body(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.note import Note, NoteType

    job_id = await _seed_job()
    async with AsyncSessionLocal() as db:
        note = Note(content="# Spotkanie\nTreść.", note_type=NoteType.meeting)
        db.add(note)
        await db.commit()
        note_id = note.id

    url = f"/api/notes/{note_id}/link-job"
    for body in ({"job_id": "abc"}, {"job_id": 0}, {}):
        _refused(
            await app_client.post(url, headers=app_auth_headers, json=body), "job_id"
        )
    _refused(await app_client.post(url, headers=app_auth_headers), "job_id")

    async with AsyncSessionLocal() as db:
        assert (await db.get(Note, note_id)).job_id is None
    # Poprawne ciało przechodzi walidację i idzie dalej — tu do 404, bo takiej
    # notatki nie ma.
    passed = await app_client.post(
        f"/api/notes/{note_id + 10_000_000}/link-job",
        headers=app_auth_headers,
        json={"job_id": job_id},
    )
    assert passed.status_code == 404, passed.text


async def test_champion_draft_from_jd_refuses_text_outside_the_limits(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.champion_suggestion import ChampionProfileSuggestion

    job_id = await _seed_job()
    url = f"/api/jobs/{job_id}/champion-profile/generate-from-jd"
    for body in (
        {"raw_description": "za krótki opis"},
        {"raw_description": "x" * 50_001},
        {},
    ):
        resp = await app_client.post(url, headers=app_auth_headers, json=body)
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == RAW_DESCRIPTION_LIMITS

    async with AsyncSessionLocal() as db:
        drafts = await db.scalar(
            select(func.count())
            .select_from(ChampionProfileSuggestion)
            .where(ChampionProfileSuggestion.job_id == job_id)
        )
    assert drafts == 0


async def test_champion_draft_from_history_refuses_out_of_range_options(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.champion_suggestion import ChampionProfileSuggestion

    job_id = await _seed_job()
    url = f"/api/jobs/{job_id}/champion-profile/generate-from-history"
    _refused(
        await app_client.post(url, headers=app_auth_headers, json={"top_k": 99}),
        "top_k",
    )
    _refused(
        await app_client.post(
            url, headers=app_auth_headers, json={"cross_client": "może"}
        ),
        "cross_client",
    )
    async with AsyncSessionLocal() as db:
        drafts = await db.scalar(
            select(func.count())
            .select_from(ChampionProfileSuggestion)
            .where(ChampionProfileSuggestion.job_id == job_id)
        )
    assert drafts == 0


async def test_history_previews_refuse_a_body_without_a_title(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    for url in (
        "/api/jobs/champion-profile/historical-matches",
        "/api/jobs/request-history/preview",
    ):
        for body in ({}, {"title": ""}, {"title": "Java", "top_k": 0}):
            resp = await app_client.post(url, headers=app_auth_headers, json=body)
            _refused(resp, "top_k" if "top_k" in body else "title")
        _refused(await app_client.post(url, headers=app_auth_headers), "title")


async def test_adding_a_candidate_from_history_refuses_a_malformed_body(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.recruitment_pipeline import CandidateStage

    job_id = await _seed_job()
    candidate_id = await _seed_candidate()
    url = f"/api/jobs/{job_id}/candidates"
    for body in (
        {"candidate_id": "abc"},
        {"candidate_id": 0},
        {},
        {"candidate_id": candidate_id, "source_job_id": -1},
    ):
        resp = await app_client.post(url, headers=app_auth_headers, json=body)
        _refused(resp, "source_job_id" if "source_job_id" in body else "candidate_id")

    async with AsyncSessionLocal() as db:
        stages = await db.scalar(
            select(func.count())
            .select_from(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )
    assert stages == 0


@pytest.mark.parametrize(
    ("role", "field"),
    [
        (UserRole.recruiter, "active_job_ids"),
        (UserRole.delivery_lead, "priority_job_ids"),
    ],
)
async def test_onboarding_refuses_a_malformed_body_and_stays_open(
    app_client: AsyncClient, role: UserRole, field: str
) -> None:
    headers, user_id = await _login_as(app_client, role, profile_completed=False)
    url = "/api/users/me/onboarding"

    truncated = await app_client.post(
        url,
        headers={**headers, "content-type": "application/json"},
        content=b'{"' + field.encode(),
    )
    _refused(truncated)
    _refused(await app_client.post(url, headers=headers))
    _refused(await app_client.post(url, headers=headers, json=[1, 2]))
    _refused(await app_client.post(url, headers=headers, json={field: "x"}), field)
    _refused(await app_client.post(url, headers=headers, json={field: ["a"]}), field)

    async with AsyncSessionLocal() as db:
        assert (await db.get(User, user_id)).profile_completed is False
    # Odmowa niczego nie zużywa: poprawne ciało nadal kończy onboarding.
    done = await app_client.post(url, headers=headers, json={field: []})
    assert done.status_code == 200, done.text
    assert done.json()["user"]["profile_completed"] is True


async def _seed_stage_def() -> tuple[int, int]:
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )

    async with AsyncSessionLocal() as db:
        template = PipelineTemplate(name=f"Body 422 {_tag()}")
        db.add(template)
        await db.flush()
        stage = PipelineStageDef(
            template_id=template.id,
            name="Rozmowa",
            order=1,
            category=StageCategoryEnum.internal,
        )
        db.add(stage)
        await db.commit()
        return template.id, stage.id


_BROKEN_RULE_PATCHES = (
    # Jedyny włączony kanał wyłączony.
    {"notify_inapp": False},
    # Konkretna osoba bez wskazania osoby (i z rolą z poprzedniego stanu).
    {"recipient_type": "specific_user"},
    # Rola spoza słownika.
    {"role": "prezes"},
)


async def test_patching_a_stage_rule_into_an_inconsistent_state_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.api.stage_notification_rules import INCONSISTENT_RULE
    from app.models.stage_notification import RecipientType, StageNotificationRule

    template_id, stage_id = await _seed_stage_def()
    async with AsyncSessionLocal() as db:
        rule = StageNotificationRule(
            stage_def_id=stage_id,
            recipient_type=RecipientType.role,
            role="recruiter",
            notify_inapp=True,
            notify_email=False,
        )
        db.add(rule)
        await db.commit()
        rule_id = rule.id

    url = (
        f"/api/pipeline-templates/{template_id}/stages/{stage_id}"
        f"/notification-rules/{rule_id}"
    )
    for patch in _BROKEN_RULE_PATCHES:
        resp = await app_client.patch(url, headers=app_auth_headers, json=patch)
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == INCONSISTENT_RULE

    async with AsyncSessionLocal() as db:
        kept = await db.get(StageNotificationRule, rule_id)
        assert (kept.recipient_type, kept.role) == (RecipientType.role, "recruiter")
        assert (kept.notify_inapp, kept.notify_email) == (True, False)
    # Spójna zmiana nadal się zapisuje.
    saved = await app_client.patch(
        url, headers=app_auth_headers, json={"notify_email": True}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["notify_email"] is True


async def test_patching_a_client_override_into_an_inconsistent_state_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.api.stage_notification_rules import INCONSISTENT_RULE
    from app.models.client import Client
    from app.models.stage_notification import (
        ClientStageNotificationOverride,
        RecipientType,
    )

    _template_id, stage_id = await _seed_stage_def()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Body 422 Demo {_tag()}")
        db.add(client)
        await db.flush()
        override = ClientStageNotificationOverride(
            client_id=client.id,
            stage_def_id=stage_id,
            recipient_type=RecipientType.role,
            role="recruiter",
            notify_inapp=True,
            notify_email=False,
        )
        db.add(override)
        await db.commit()
        client_id, override_id = client.id, override.id

    url = f"/api/clients/{client_id}/notification-overrides/{override_id}"
    for patch in _BROKEN_RULE_PATCHES:
        resp = await app_client.patch(url, headers=app_auth_headers, json=patch)
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == INCONSISTENT_RULE

    async with AsyncSessionLocal() as db:
        kept = await db.get(ClientStageNotificationOverride, override_id)
        assert (kept.recipient_type, kept.role) == (RecipientType.role, "recruiter")
        assert (kept.notify_inapp, kept.notify_email) == (True, False)


async def test_chat_reaction_with_a_non_text_emoji_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.candidate_chat import CandidateChatMessage
    from app.models.chat_reaction import (
        CandidateChatMessageReaction,
        JobChatMessageReaction,
    )
    from app.models.job_chat import JobChatMessage

    job_id = await _seed_job()
    candidate_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        job_message = JobChatMessage(job_id=job_id, content="Kto ma ruch?")
        candidate_message = CandidateChatMessage(
            candidate_id=candidate_id, content="Kto dzwoni?"
        )
        db.add_all([job_message, candidate_message])
        await db.commit()
        job_message_id, candidate_message_id = job_message.id, candidate_message.id

    cases = (
        (
            f"/api/jobs/{job_id}/chat/messages/{job_message_id}/reactions",
            JobChatMessageReaction,
            job_message_id,
        ),
        (
            f"/api/candidates/{candidate_id}/chat/messages/{candidate_message_id}"
            "/reactions",
            CandidateChatMessageReaction,
            candidate_message_id,
        ),
    )
    for url, model, message_id in cases:
        for emoji in (5, None, ["👍"], {"emoji": "👍"}, True):
            resp = await app_client.post(
                url, headers=app_auth_headers, json={"emoji": emoji}
            )
            assert resp.status_code == 400, resp.text
            assert resp.json()["detail"] == "Emoji jest wymagane (max 16 znaków)."
        async with AsyncSessionLocal() as db:
            reactions = await db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.message_id == message_id)
            )
        assert reactions == 0
        added = await app_client.post(
            url, headers=app_auth_headers, json={"emoji": " 👍 "}
        )
        assert added.status_code == 200, added.text
        assert [r["emoji"] for r in added.json()["reactions"]] == ["👍"]


async def test_champion_import_refuses_a_sync_field_that_is_not_a_name(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.job import Job

    job_id = await _seed_job()
    url = f"/api/jobs/{job_id}/champion-profile/apply-import"
    for fields in ([{}], [["budget"]], [None], [5]):
        resp = await app_client.post(
            url,
            headers=app_auth_headers,
            json={
                "expected_fingerprint": "a" * 64,
                "profile": {},
                "sync_fields": fields,
            },
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "Nieznane pole uzgodnienia rekrutacji."

    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).champion_profile is None
