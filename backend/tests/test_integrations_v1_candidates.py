"""API v1 — odczyt kandydatów (``integrations_v1/candidates``, 15.10.2026).

Dwie części:

* bez bazy — projekcje i parsery ``services/integration_candidate_reads``
  (``?ids=``, umiejętności, preferencje, schowanie kontaktu i kosztów, odczyt
  CV bez kluczy spoza CV, podpis autora notatki, arkusz screeningu, pola karty
  bez narodowości);
* na bazie — trasy z prawdziwym kluczem: filtry listy, kontakt tylko
  z ``candidates:contact``, stawki tylko z ``amounts:read``, pliki tylko
  z ``candidates:cv`` (pobranie zostawia ślad w dzienniku kandydata),
  notatki tylko z ``notes:read``, kwarantanna tożsamości, 404.

Dane są zmyślone (repo jest publiczne): „Anna Przykładowa”, „Jan Testowy”.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note, NoteType
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services import candidate_audit, note_kinds
from app.services import integration_candidate_reads as reads
from tests._job_factory import competence_category_id
from tests.test_service_accounts import _account_with_key

V1 = "/api/integrations/v1"
_MISSING_ID = 2_000_000_000


# ── Bez bazy ─────────────────────────────────────────────────────────────────


class TestParseIds:
    def test_empty_means_no_filter(self):
        assert reads.parse_ids(None) == []
        assert reads.parse_ids("") == []
        assert reads.parse_ids(" , ") == []

    def test_dedupes_and_sorts(self):
        assert reads.parse_ids(" 3, 1,3 ,") == [1, 3]

    @pytest.mark.parametrize(
        "raw",
        ["1,a", "0", "-1", "1.5", "１", str(2**31), ",".join(["1"] * 201)],
    )
    def test_rejects_what_is_not_an_id_list(self, raw: str):
        with pytest.raises(reads.InvalidIds):
            reads.parse_ids(raw)

    def test_two_hundred_ids_are_accepted(self):
        assert len(reads.parse_ids(",".join(str(i) for i in range(1, 201)))) == 200


class TestListConditions:
    def _sql(self, filters: reads.CandidateListFilters) -> str:
        conditions = reads.candidate_list_conditions(filters)
        return " AND ".join(
            str(c.compile(dialect=postgresql.dialect())) for c in conditions
        )

    def test_email_is_an_exact_case_insensitive_match(self):
        sql = self._sql(reads.CandidateListFilters(email="Anna@Example.com"))
        assert "lower(candidates.email)" in sql
        assert "ILIKE" not in sql.upper()

    def test_name_alone_never_touches_the_email_column(self):
        sql = self._sql(reads.CandidateListFilters(name="Anna Przykładowa"))
        assert "candidates.email" not in sql
        assert "candidates.name" in sql and "candidates.lastname" in sql

    def test_name_uses_at_most_five_words(self):
        conditions = reads.candidate_list_conditions(
            reads.CandidateListFilters(name="a b c d e f g")
        )
        assert len(conditions) == reads.MAX_NAME_TOKENS

    def test_no_filters_no_conditions(self):
        assert reads.candidate_list_conditions(reads.CandidateListFilters()) == []


def test_email_phrase_is_recognized_by_the_at_sign():
    assert reads.looks_like_email("anna@example.com")
    assert not reads.looks_like_email("Anna Przykładowa")


def test_skills_are_normalized_from_both_jsonb_shapes():
    raw = [
        "SQL",
        {"name": "Python", "level": "senior", "years": 5},
        {"name": " ", "level": "mid"},
        {"name": "Go", "years": True},
        42,
    ]
    assert reads.skills_out(raw) == [
        {"name": "SQL", "level": None, "years": None},
        {"name": "Python", "level": "senior", "years": 5},
        {"name": "Go", "level": None, "years": None},
    ]
    assert reads.skills_out(None) == []
    assert reads.skills_out({"name": "Python"}) == []


def test_work_preferences_skip_internal_preference_keys():
    candidate = SimpleNamespace(
        preferences={
            "remote_modes": ["remote", "hybrid", 3],
            "contract_types": ["b2b"],
            "excluded_clients": [7],
            "monthly_rate": 20000,
        },
        max_onsite_days_per_week=1,
        b2b_willingness="b2b",
        work_time_preference=None,
    )
    out = reads.work_preferences(candidate)
    assert out == {
        "work_modes": ["remote", "hybrid"],
        "contract_types": ["b2b"],
        "max_onsite_days_per_week": 1,
        "b2b_willingness": "b2b",
        "work_time_preference": None,
    }


def test_contact_fields_are_null_without_the_contact_scope():
    candidate = SimpleNamespace(
        email="anna@example.com",
        phone="+48 600 000 001",
        linkedin="https://www.linkedin.com/in/anna-przykladowa",
        nip="0000000000",
        regon="000000000",
        legal_name="Anna Przykładowa Usługi IT",
    )
    hidden = reads.contact_fields(candidate, visible=False)
    assert hidden["contact_redacted"] is True
    assert all(hidden[key] is None for key in hidden if key != "contact_redacted")
    shown = reads.contact_fields(candidate, visible=True)
    assert shown["contact_redacted"] is False
    assert shown["email"] == "anna@example.com"
    assert shown["legal_name"] == "Anna Przykładowa Usługi IT"


class TestProfileRates:
    def _candidate(self, currency: str = "PLN") -> SimpleNamespace:
        return SimpleNamespace(
            expected_rate_hourly=Decimal("150.00"),
            expected_rate_currency=currency,
            rate_from_computed_at=None,
        )

    def test_costs_are_null_without_amounts_read(self):
        out = reads.profile_rates(self._candidate(), show_costs=False)
        assert out["costs_redacted"] is True
        assert all(out[key] is None for key in out if key != "costs_redacted")

    def test_rate_from_comes_from_rate_summary(self):
        out = reads.profile_rates(self._candidate(), show_costs=True)
        assert out["costs_redacted"] is False
        assert out["rate_from_hourly"] == Decimal("150.00")

    def test_a_rate_in_another_currency_is_not_comparable(self):
        out = reads.profile_rates(self._candidate("EUR"), show_costs=True)
        assert out["rate_from_hourly"] is None


def test_cv_extracted_data_keeps_only_cv_keys():
    data = {
        "skills": ["Python"],
        "cv_highlights": {"source_document_id": 12},
        "_notes_insights": {"expected_rate": {"value": 150}},
        "_manual_override_city": True,
        "_field_provenance": {"skills": {}},
        "traffit_Stawka": "150 zł/h",
        "legacy_source": "traffit",
    }
    assert reads.public_cv_extracted(data) == {
        "skills": ["Python"],
        "cv_highlights": {"source_document_id": 12},
    }
    assert reads.public_cv_extracted(["not", "a", "dict"]) is None


def test_projected_document_id_reads_cv_highlights_only():
    assert (
        reads.projected_document_id({"cv_highlights": {"source_document_id": 5}}) == 5
    )
    assert (
        reads.projected_document_id({"cv_highlights": {"source_document_id": True}})
        is None
    )
    assert reads.projected_document_id({"cv_highlights": "x"}) is None
    assert reads.projected_document_id(None) is None


@pytest.mark.parametrize(
    "author_name,source_ref,external_source,expected",
    [
        ("Ewa Rekruterka", None, None, ("Ewa Rekruterka", "user")),
        (
            None,
            "integration:rozliczenia-n8n",
            "system",
            ("Integracja: rozliczenia-n8n", "integration"),
        ),
        (None, "integration:", None, ("Integracja", "integration")),
        (None, None, "system", (None, "system")),
        (None, "fireflies:abc", "traffit", (None, "none")),
    ],
)
def test_note_author_label(author_name, source_ref, external_source, expected):
    assert (
        reads.note_author(
            author_name, source_ref=source_ref, external_source=external_source
        )
        == expected
    )


def test_screening_sheet_has_a_stable_shape_without_recruiter_keywords():
    sheet = {
        "answers": [
            {
                "question_id": "q1",
                "question_text": "Ile lat z Pythonem?",
                "response": "Pięć lat",
                "deal_breaker_hit": False,
                "keywords": "python 5 lat",
                "origin": "phrased",
            },
            "zepsuty wpis",
        ],
        "experience_checks": [
            {"kind": "domains", "name": "Bankowość", "status": "confirmed"}
        ],
        "overall_fit": "fit",
        "notes": "Dobra rozmowa",
        "answered_at": "nie-data",
        "answered_by": 7,
    }
    out = reads.screening_sheet_out(sheet, user_names={7: "Ewa Rekruterka"})
    assert out is not None
    assert out["answers"] == [
        {
            "question_id": "q1",
            "question_text": "Ile lat z Pythonem?",
            "response": "Pięć lat",
            "deal_breaker_hit": False,
            "skipped": False,
            "origin": "phrased",
        }
    ]
    assert out["experience_checks"][0]["note"] == ""
    assert out["answered_at"] is None
    assert out["answered_by_name"] == "Ewa Rekruterka"
    assert reads.screening_sheet_out(None, user_names={}) is None
    assert reads.screening_sheet_out({}, user_names={}) is None


class TestCardFields:
    _AT = "2041-03-01T10:00:00+00:00"

    def _current(self) -> dict:
        return {
            "nationality": {"raw": "polska", "at": self._AT, "source": "note"},
            "rate": {"raw": "150 zł/h", "value": 150, "at": self._AT, "source": "note"},
            "recommendation": {
                "raw": "Mocny kandydat",
                "at": self._AT,
                "source": "manual",
                "by": 3,
            },
            "availability": {"raw": "od zaraz", "at": self._AT, "source": "note"},
        }

    def test_nationality_never_leaves_the_api(self):
        for show_costs in (False, True):
            keys = [
                f["key"]
                for f in reads.card_fields(self._current(), show_costs=show_costs)
            ]
            assert "nationality" not in keys

    def test_candidate_rate_only_with_costs(self):
        without = [
            f["key"] for f in reads.card_fields(self._current(), show_costs=False)
        ]
        with_costs = [
            f["key"] for f in reads.card_fields(self._current(), show_costs=True)
        ]
        assert "rate" not in without
        assert "rate" in with_costs

    def test_fields_follow_the_card_order_and_drop_author_ids(self):
        fields = reads.card_fields(self._current(), show_costs=True)
        assert [f["key"] for f in fields] == ["rate", "availability", "recommendation"]
        recommendation = fields[-1]
        assert recommendation["label"] == "Dlaczego ten kandydat"
        assert recommendation["source"] == "manual"
        assert "by" not in recommendation
        assert recommendation["at"] == datetime(2041, 3, 1, 10, tzinfo=timezone.utc)


# ── Na bazie ─────────────────────────────────────────────────────────────────


async def _key(
    app_client: AsyncClient, headers: dict, scopes: list[str]
) -> tuple[dict, str]:
    account, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return account, api_key


def _h(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def _seed(app_client: AsyncClient) -> dict:
    """Anna (w rekrutacji, z CV, notatkami i kartą) i Jan (poza nią)."""
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    category_id = await competence_category_id()
    admin_email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        admin_id = await db.scalar(select(User.id).where(User.email == admin_email))
        client = Client(name=f"V1 Kandydaci {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Analityk danych {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        anna = Candidate(
            name="Anna",
            lastname=f"Przykładowa{tag}",
            email=f"anna-{tag}@example.com",
            phone="+48 600 000 001",
            linkedin=f"https://www.linkedin.com/in/anna-przykladowa-{tag}",
            nip="0000000000",
            city="Kraków",
            country="PL",
            availability_status=AvailabilityStatus.actively_looking,
            competence_category_id=category_id,
            expected_rate_hourly=Decimal("150.00"),
            expected_rate_currency="PLN",
            skills=[{"name": "Python", "level": "senior", "years": 5}, "SQL"],
            preferences={"remote_modes": ["remote"], "excluded_clients": [1]},
            raw_cv_text="Anna Przykładowa — Python, SQL",
            cv_extracted_data={
                "skills": ["Python"],
                "_notes_insights": {"expected_rate": {"value": 150}},
                "traffit_Stawka": "150 zł/h",
            },
        )
        jan = Candidate(
            name="Jan",
            lastname=f"Testowy{tag}",
            email=f"jan-{tag}@example.com",
            city="Gdańsk",
            availability_status=AvailabilityStatus.not_looking,
            raw_cv_text="Jan Testowy — Java",
        )
        db.add_all([job, anna, jan])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=anna.id,
                job_id=job.id,
                stage=PipelineStage.screening,
                moved_at=now - timedelta(hours=1),
                expected_rate_value=Decimal("150"),
                expected_rate_unit="hourly",
                expected_rate_currency="PLN",
                screening_answers={
                    "answers": [
                        {
                            "question_id": "q1",
                            "question_text": "Ile lat z Pythonem?",
                            "response": "Pięć lat w bankowości",
                            "deal_breaker_hit": False,
                        }
                    ],
                    "overall_fit": "fit",
                    "notes": "Konkretna rozmowa",
                    "answered_at": now.isoformat(),
                    "answered_by": admin_id,
                },
            )
        )
        cv = CandidateDocument(
            candidate_id=anna.id,
            filename="cv-anna-przykladowa.pdf",
            file_content=b"%PDF-1.4 fikcyjne CV",
            content_type="application/pdf",
            size_bytes=20,
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            uploaded_at=now,
        )
        foreign = CandidateDocument(
            candidate_id=anna.id,
            filename="cv-innej-osoby.pdf",
            file_content=b"%PDF-1.4 cudze CV",
            content_type="application/pdf",
            document_kind=CandidateDocumentKind.other,
            uploaded_at=now,
        )
        removed = CandidateDocument(
            candidate_id=anna.id,
            filename="usuniete.pdf",
            file_content=b"%PDF-1.4 usuniete",
            content_type="application/pdf",
            document_kind=CandidateDocumentKind.other,
            uploaded_at=now,
            source_deleted_at=now,
        )
        talk = Note(
            content="Rozmowa: zainteresowana projektem",
            note_type=NoteType.call,
            candidate_id=anna.id,
            job_id=job.id,
            author_id=admin_id,
        )
        general = Note(
            content="Ogólna notatka bez rekrutacji",
            note_type=NoteType.general,
            candidate_id=anna.id,
        )
        dl_rate = Note(
            content="Wyślijmy za 161 zł/h",
            note_type=NoteType.general,
            candidate_id=anna.id,
            job_id=job.id,
            kind=note_kinds.DL_RATE,
        )
        foreign_note = Note(
            content="Notatka o innej osobie",
            note_type=NoteType.general,
            candidate_id=anna.id,
        )
        db.add_all([cv, foreign, removed, talk, general, dl_rate, foreign_note])
        await db.flush()
        reply = Note(
            content="Odpowiedź do rozmowy",
            note_type=NoteType.general,
            candidate_id=anna.id,
            job_id=job.id,
            parent_note_id=talk.id,
        )
        db.add(reply)
        for kind, source_id in (
            ("document", foreign.id),
            ("note", foreign_note.id),
            ("legacy_cv", jan.id),
        ):
            db.add(
                CandidateSourceIdentityReview(
                    candidate_id=anna.id if kind != "legacy_cv" else jan.id,
                    source_kind=kind,
                    source_id=source_id,
                    decision="confirmed_mismatch",
                    provenance="pytest",
                    detector_version="pytest",
                    evidence={},
                    reviewed_at=now,
                )
            )
        at = (now - timedelta(minutes=30)).isoformat()
        db.add(
            RecommendationCard(
                candidate_id=anna.id,
                job_id=job.id,
                fields_notes={
                    "nationality": {"raw": "polska", "at": at},
                    "rate": {
                        "raw": "150 zł/h",
                        "value": 150,
                        "currency": "PLN",
                        "period": "h",
                        "at": at,
                    },
                    "availability": {"raw": "od zaraz", "at": at},
                },
            )
        )
        await db.flush()
        ids = {
            "tag": tag,
            "category_id": category_id,
            "admin_id": admin_id,
            "job_id": job.id,
            "anna": anna.id,
            "jan": jan.id,
            "cv": cv.id,
            "foreign_doc": foreign.id,
            "removed_doc": removed.id,
            "talk": talk.id,
            "general": general.id,
            "dl_rate": dl_rate.id,
            "foreign_note": foreign_note.id,
            "reply": reply.id,
        }
        await db.commit()
    return ids


class TestCandidateList:
    async def test_name_search_folds_polish_letters_and_hides_contact(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            f"{V1}/candidates",
            headers=_h(api_key),
            params={"q": f"anna przykladowa{seed['tag']}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [item["id"] for item in body["items"]] == [seed["anna"]]
        item = body["items"][0]
        assert item["first_name"] == "Anna"
        assert item["availability_status"] == "actively_looking"
        assert "email" not in item and "phone" not in item

    async def test_filters_and_stable_order_by_id(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        both = f"{seed['jan']},{seed['anna']}"

        async def ids_for(**params) -> list[int]:
            resp = await app_client.get(
                f"{V1}/candidates", headers=_h(api_key), params={"ids": both, **params}
            )
            assert resp.status_code == 200, resp.text
            return [item["id"] for item in resp.json()["items"]]

        assert await ids_for() == sorted([seed["anna"], seed["jan"]])
        assert await ids_for(city="Krakow") == [seed["anna"]]
        assert await ids_for(availability="actively_looking") == [seed["anna"]]
        assert await ids_for(competence_category_id=seed["category_id"]) == [
            seed["anna"]
        ]

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Candidate)
                .where(Candidate.id == seed["jan"])
                .values(updated_at=datetime(2001, 1, 1, tzinfo=timezone.utc))
            )
            await db.commit()
        assert await ids_for(updated_since="2020-01-01T00:00:00Z") == [seed["anna"]]

    async def test_page_size_and_has_more(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            f"{V1}/candidates",
            headers=_h(api_key),
            params={"ids": f"{seed['anna']},{seed['jan']}", "page_size": 1},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2 and body["has_more"] is True
        assert [item["id"] for item in body["items"]] == [
            min(seed["anna"], seed["jan"])
        ]

    async def test_bad_ids_are_422_in_the_envelope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            f"{V1}/candidates", headers=_h(api_key), params={"ids": "1,abc"}
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "validation_error"

    async def test_email_lookup_needs_the_contact_scope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        email = f"ANNA-{seed['tag']}@example.com"
        _, read_only = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            f"{V1}/candidates", headers=_h(read_only), params={"q": email}
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

        _, contact = await _key(
            app_client, app_auth_headers, ["candidates:read", "candidates:contact"]
        )
        resp = await app_client.get(
            f"{V1}/candidates", headers=_h(contact), params={"q": email}
        )
        assert resp.status_code == 200, resp.text
        assert [item["id"] for item in resp.json()["items"]] == [seed["anna"]]

    async def test_list_needs_candidates_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:cv"])
        resp = await app_client.get(f"{V1}/candidates", headers=_h(api_key))
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"


class TestCandidateProfile:
    async def test_profile_without_contact_and_costs(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["first_name"] == "Anna"
        assert body["contact_redacted"] is True
        for key in ("email", "phone", "linkedin", "nip", "regon", "legal_name"):
            assert body[key] is None, key
        assert body["costs_redacted"] is True
        assert body["rate_from_hourly"] is None
        assert body["competence_category"]["id"] == seed["category_id"]
        assert body["skills"][0] == {"name": "Python", "level": "senior", "years": 5}
        assert body["work_preferences"]["work_modes"] == ["remote"]
        assert "excluded_clients" not in body["work_preferences"]
        assert body["added_to_base_at"] is not None
        assert body["employment_marker"] is None
        assert body["active_recruitments"] == [
            {
                "job_id": seed["job_id"],
                "job_title": f"Analityk danych {seed['tag']}",
                "client_id": body["active_recruitments"][0]["client_id"],
                "client_name": f"V1 Kandydaci {seed['tag']}",
                "stage": "screening",
                "in_progress": True,
                "moved_at": body["active_recruitments"][0]["moved_at"],
            }
        ]

    async def test_contact_scope_shows_contact_fields(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(
            app_client, app_auth_headers, ["candidates:read", "candidates:contact"]
        )
        body = (
            await app_client.get(f"{V1}/candidates/{seed['anna']}", headers=_h(api_key))
        ).json()
        assert body["contact_redacted"] is False
        assert body["email"] == f"anna-{seed['tag']}@example.com"
        assert body["phone"] == "+48 600 000 001"
        assert body["nip"] == "0000000000"
        assert body["costs_redacted"] is True

    async def test_amounts_read_shows_the_candidate_rate(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, sales = await _key(
            app_client, app_auth_headers, ["candidates:read", "sales_amounts:read"]
        )
        body = (
            await app_client.get(f"{V1}/candidates/{seed['anna']}", headers=_h(sales))
        ).json()
        # Stawka kandydata to koszt — kwoty sprzedaży jej nie odsłaniają.
        assert body["costs_redacted"] is True
        assert body["rate_from_hourly"] is None

        _, costs = await _key(
            app_client, app_auth_headers, ["candidates:read", "amounts:read"]
        )
        body = (
            await app_client.get(f"{V1}/candidates/{seed['anna']}", headers=_h(costs))
        ).json()
        assert body["costs_redacted"] is False
        assert body["rate_from_hourly"] == "150.00"
        assert body["contact_redacted"] is True

    async def test_missing_candidate_is_404(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            f"{V1}/candidates/{_MISSING_ID}", headers=_h(api_key)
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"


class TestDocuments:
    async def test_documents_need_the_cv_scope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(
            app_client, app_auth_headers, ["candidates:read", "candidates:contact"]
        )
        for path in (
            f"/candidates/{seed['anna']}/documents",
            f"/candidates/{seed['anna']}/documents/{seed['cv']}/file",
            f"/candidates/{seed['anna']}/cv-text",
        ):
            resp = await app_client.get(f"{V1}{path}", headers=_h(api_key))
            assert resp.status_code == 403, (path, resp.text)
            assert resp.json()["error"]["code"] == "insufficient_scope"

    async def test_list_skips_removed_and_foreign_files(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:cv"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/documents", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert [item["id"] for item in items] == [seed["cv"]]
        assert items[0]["kind"] == "cv"
        assert items[0]["is_primary"] is True
        assert items[0]["file_name"] == "cv-anna-przykladowa.pdf"
        assert items[0]["mime_type"] == "application/pdf"

    async def test_download_returns_bytes_and_leaves_an_audit_row(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        account, api_key = await _key(app_client, app_auth_headers, ["candidates:cv"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/documents/{seed['cv']}/file",
            headers=_h(api_key),
        )
        assert resp.status_code == 200, resp.text
        assert resp.content == b"%PDF-1.4 fikcyjne CV"
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.headers["content-disposition"].startswith("attachment")

        async with AsyncSessionLocal() as db:
            rows = (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "candidate",
                        Activity.entity_id == seed["anna"],
                        Activity.action == candidate_audit.DOCUMENT_DOWNLOADED,
                    )
                )
            ).all()
        assert len(rows) == 1
        assert rows[0].user_id is None
        assert rows[0].details["doc_id"] == seed["cv"]
        assert rows[0].details["via"] == f"integration:{account['slug']}"

    async def test_foreign_removed_and_missing_files_are_404(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:cv"])
        for candidate_id, doc_id in (
            (seed["anna"], seed["foreign_doc"]),
            (seed["anna"], seed["removed_doc"]),
            (seed["jan"], seed["cv"]),
            (seed["anna"], _MISSING_ID),
        ):
            resp = await app_client.get(
                f"{V1}/candidates/{candidate_id}/documents/{doc_id}/file",
                headers=_h(api_key),
            )
            assert resp.status_code == 404, (candidate_id, doc_id, resp.text)
            assert resp.json()["error"]["code"] == "not_found"
        resp = await app_client.get(
            f"{V1}/candidates/{_MISSING_ID}/documents", headers=_h(api_key)
        )
        assert resp.status_code == 404, resp.text
        async with AsyncSessionLocal() as db:
            audit = await db.scalar(
                select(Activity.id).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == seed["anna"],
                    Activity.action == candidate_audit.DOCUMENT_DOWNLOADED,
                )
            )
        assert audit is None

    async def test_cv_text_drops_keys_outside_the_cv(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:cv"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/cv-text", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["quarantined"] is False
        assert body["raw_cv_text"] == "Anna Przykładowa — Python, SQL"
        assert body["cv_extracted_data"] == {"skills": ["Python"]}

    async def test_cv_text_of_a_quarantined_cv_is_withheld(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:cv"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['jan']}/cv-text", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["quarantined"] is True
        assert body["raw_cv_text"] is None
        assert body["cv_extracted_data"] is None
        resp = await app_client.get(
            f"{V1}/candidates/{_MISSING_ID}/cv-text", headers=_h(api_key)
        )
        assert resp.status_code == 404, resp.text


class TestNotes:
    async def test_notes_need_notes_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(
            app_client, app_auth_headers, ["candidates:read", "candidates:cv"]
        )
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/notes", headers=_h(api_key)
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

    async def test_notes_hide_client_rate_and_foreign_notes(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["notes:read"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/notes", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        notes = {item["id"]: item for item in resp.json()["items"]}
        assert set(notes) == {
            seed["talk"],
            seed["general"],
            seed["dl_rate"],
            seed["reply"],
        }
        assert notes[seed["dl_rate"]]["content"] is None
        assert notes[seed["dl_rate"]]["content_hidden"] is True
        talk = notes[seed["talk"]]
        assert talk["content"] == "Rozmowa: zainteresowana projektem"
        assert talk["author_kind"] == "user" and talk["author_name"]
        assert talk["job_title"] == f"Analityk danych {seed['tag']}"
        assert notes[seed["reply"]]["reply_to"] == seed["talk"]

    async def test_sales_amounts_reveal_the_client_rate_note(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(
            app_client, app_auth_headers, ["notes:read", "sales_amounts:read"]
        )
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/notes", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        notes = {item["id"]: item for item in resp.json()["items"]}
        assert notes[seed["dl_rate"]]["content"] == "Wyślijmy za 161 zł/h"
        assert notes[seed["dl_rate"]]["content_hidden"] is False

    async def test_job_filter_and_404(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["notes:read"])
        resp = await app_client.get(
            f"{V1}/candidates/{seed['anna']}/notes",
            headers=_h(api_key),
            params={"job_id": seed["job_id"]},
        )
        assert resp.status_code == 200, resp.text
        assert {item["id"] for item in resp.json()["items"]} == {
            seed["talk"],
            seed["dl_rate"],
            seed["reply"],
        }
        resp = await app_client.get(
            f"{V1}/candidates/{_MISSING_ID}/notes", headers=_h(api_key)
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"


class TestScreening:
    def _path(self, job_id: int, candidate_id: int) -> str:
        return f"{V1}/recruitments/{job_id}/candidates/{candidate_id}/screening"

    async def test_screening_needs_notes_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(
            self._path(seed["job_id"], seed["anna"]), headers=_h(api_key)
        )
        assert resp.status_code == 403, resp.text

    async def test_answers_and_card_without_nationality_or_costs(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["notes:read"])
        resp = await app_client.get(
            self._path(seed["job_id"], seed["anna"]), headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stage"] == "screening"
        answers = body["screening"]["answers"]
        assert answers[0]["response"] == "Pięć lat w bankowości"
        assert body["screening"]["overall_fit"] == "fit"
        assert body["screening"]["answered_by_name"]
        keys = [field["key"] for field in body["recommendation_card"]["fields"]]
        assert keys == ["availability"]
        assert body["costs_redacted"] is True
        assert body["candidate_rate"] is None
        assert "polska" not in resp.text

    async def test_amounts_read_shows_the_rate_but_never_nationality(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(
            app_client, app_auth_headers, ["notes:read", "amounts:read"]
        )
        resp = await app_client.get(
            self._path(seed["job_id"], seed["anna"]), headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        keys = [field["key"] for field in body["recommendation_card"]["fields"]]
        assert keys == ["rate", "availability"]
        assert body["costs_redacted"] is False
        assert body["candidate_rate"]["amount_hourly"] == "150.00"
        assert "polska" not in resp.text

    async def test_missing_job_and_candidate_outside_the_job_are_404(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seed = await _seed(app_client)
        _, api_key = await _key(app_client, app_auth_headers, ["notes:read"])
        for job_id, candidate_id in (
            (_MISSING_ID, seed["anna"]),
            (seed["job_id"], _MISSING_ID),
            (seed["job_id"], seed["jan"]),
        ):
            resp = await app_client.get(
                self._path(job_id, candidate_id), headers=_h(api_key)
            )
            assert resp.status_code == 404, (job_id, candidate_id, resp.text)
            assert resp.json()["error"]["code"] == "not_found"
