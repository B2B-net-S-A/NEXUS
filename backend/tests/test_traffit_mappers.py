"""Unit testy dla pure-function mappers Traffit→Nexus.

Fixtures: backend/tests/fixtures/traffit/ (anonymized w Faza 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.traffit.mappers import (
    map_traffit_state_to_pipeline,
    normalize_candidate_status,
    normalize_client_status,
    normalize_job_status,
    normalize_traffit_role,
    select_all_files_with_priority,
    select_primary_cv_file,
    strip_employment_marker,
    traffit_activity_to_activity,
    traffit_client_to_nexus,
    traffit_crm_person_to_nexus,
    traffit_employee_to_candidate,
    traffit_recruitment_history_to_stage,
    traffit_recruitment_to_job,
    traffit_source_to_candidate_tag,
    traffit_talent_to_pool,
    traffit_user_to_nexus,
    traffit_workflow_state_to_stage_def,
    traffit_workflow_to_template,
)

FIXTURES = Path(__file__).parent / "fixtures" / "traffit"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


class TestNormalizeClientStatus:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Aktywny", "active"),
            ("aktywny", "active"),
            ("active", "active"),
            ("Active", "active"),
            ("Nieaktywny", "inactive"),
            ("inactive", "inactive"),
            ("Prospekt", "prospect"),
            ("Lead", "prospect"),
            ("nieznany_status", "active"),  # fallback
            ("", "active"),
            (None, "active"),
        ],
    )
    def test_known_and_unknown(self, raw, expected):
        assert normalize_client_status(raw) == expected


class TestTraffitClientToNexus:
    def test_minimal_fixture(self):
        # clients_detail.json: id=26, name="Sample", status="Aktywny"
        payload = _load("clients_detail.json")
        result = traffit_client_to_nexus(payload)
        assert result["external_id"] == "26"
        assert result["external_source"] == "traffit"
        assert result["name"] == "Sample"
        assert result["status"] == "active"
        assert result["notes"] is None  # "Aktywny" maps cleanly, no audit hint

    def test_unknown_status_lands_in_notes(self):
        payload = {"id": 99, "name": "ACME", "status": "OnHold"}
        result = traffit_client_to_nexus(payload)
        assert result["status"] == "active"
        assert result["notes"] == "[traffit] status: OnHold"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_client_to_nexus({"name": "ACME"})

    def test_empty_name_falls_back(self):
        payload = {"id": 7, "name": "", "status": "active"}
        result = traffit_client_to_nexus(payload)
        assert result["name"] == "Klient bez nazwy #7"

    def test_long_name_truncated(self):
        payload = {"id": 1, "name": "x" * 500, "status": "active"}
        result = traffit_client_to_nexus(payload)
        assert len(result["name"]) == 255


class TestTraffitCrmPersonToNexus:
    def test_full_fixture(self):
        # crm_persons_detail.json: id=24, name=Sample, lastname=User, email=user@example.com,
        # client.id=8, status=active
        payload = _load("crm_persons_detail.json")
        client_map = {"8": 100}  # Traffit client_id=8 → Nexus client.id=100
        orphan_id = 999

        result = traffit_crm_person_to_nexus(payload, client_map, orphan_id)
        assert result["external_id"] == "24"
        assert result["external_source"] == "traffit"
        assert result["client_id"] == 100  # mapped from client_map
        assert result["name"] == "Sample User"  # name + lastname concat
        assert result["email"] == "user@example.com"

    def test_orphan_when_no_client(self):
        payload = {
            "id": 50,
            "name": "John",
            "lastname": "Doe",
            "email": "john@example.com",
            "client": None,  # explicit no client
        }
        result = traffit_crm_person_to_nexus(payload, {}, orphan_client_nexus_id=999)
        assert result["client_id"] == 999

    def test_orphan_when_unknown_client(self):
        payload = {
            "id": 50,
            "name": "John",
            "lastname": "Doe",
            "client": {"id": 9999},  # not in client_map
        }
        result = traffit_crm_person_to_nexus(
            payload, {"1": 10}, orphan_client_nexus_id=999
        )
        assert result["client_id"] == 999

    def test_name_fallback_to_email_localpart(self):
        payload = {
            "id": 50,
            "name": "",
            "lastname": "",
            "email": "alice@example.com",
            "client": {"id": 1},
        }
        result = traffit_crm_person_to_nexus(payload, {"1": 10}, 999)
        assert result["name"] == "alice"

    def test_name_fallback_to_question_mark(self):
        payload = {
            "id": 50,
            "name": "",
            "lastname": "",
            "email": "",
            "client": {"id": 1},
        }
        result = traffit_crm_person_to_nexus(payload, {"1": 10}, 999)
        assert result["name"] == "?"

    def test_phone_picks_first_nonempty_from_phone_or_mobile(self):
        # phone empty, mobile has value
        payload = {
            "id": 1,
            "name": "X",
            "lastname": "Y",
            "phone": "",
            "mobile": "+48123",
            "client": {"id": 1},
        }
        result = traffit_crm_person_to_nexus(payload, {"1": 10}, 999)
        assert result["phone"] == "+48123"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_crm_person_to_nexus({"name": "X"}, {}, 999)


# ── Faza 5: workflow + state mapping ────────────────────────────────────────


class TestMapTraffitStateToPipeline:
    @pytest.mark.parametrize(
        "state_type,expected_legacy,expected_terminal",
        [
            ("start", "new", False),
            ("screening", "screening", False),
            ("initial_accept", "verified", False),
            ("technical_verification", "interview", False),
            ("client_verification", "cv_sent", False),
            ("interview", "interview", False),
            ("end-good", "hired", True),
            ("end-bad", "rejected", True),
            ("wait", "withdrawn", True),
            ("custom_unknown_xyz", "screening", False),  # default fallback
        ],
    )
    def test_basic_type_mapping(self, state_type, expected_legacy, expected_terminal):
        result = map_traffit_state_to_pipeline({"type": state_type})
        assert result["legacy"] == expected_legacy
        assert result["is_terminal"] == expected_terminal

    def test_is_rejection_overrides_to_rejected(self):
        result = map_traffit_state_to_pipeline(
            {"type": "screening", "is_rejection": True}
        )
        assert result["legacy"] == "rejected"
        assert result["category"] == "terminal"
        assert result["is_terminal"] is True
        assert result["terminal_type"] == "rejected"

    def test_terminal_types(self):
        assert (
            map_traffit_state_to_pipeline({"type": "end-good"}).get("terminal_type")
            == "hired"
        )
        assert (
            map_traffit_state_to_pipeline({"type": "end-bad"}).get("terminal_type")
            == "rejected"
        )
        assert (
            map_traffit_state_to_pipeline({"type": "wait"}).get("terminal_type")
            == "withdrawn"
        )


class TestTraffitWorkflowToTemplate:
    def test_minimal(self):
        result = traffit_workflow_to_template({"id": 4, "name": "B2B"})
        assert result["external_id"] == "4"
        assert result["external_source"] == "traffit"
        assert result["name"] == "B2B"
        assert result["is_default"] is False

    def test_empty_name_falls_back(self):
        result = traffit_workflow_to_template({"id": 7, "name": ""})
        assert result["name"] == "Traffit Workflow #7"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_workflow_to_template({"name": "X"})


class TestTraffitWorkflowStateToStageDef:
    def test_full_fixture_b2b(self):
        # Pierwszy state z workflows_4_detail.json: id=19, type=start, sid=Nowy
        wf = _load("workflows_4_detail.json")
        first = wf["states"][0]
        result = traffit_workflow_state_to_stage_def(first, order_index=0)
        assert result["traffit_state_id"] == "19"
        assert result["order"] == 0
        assert result["category"] == "internal"
        assert result["is_terminal"] is False
        assert result["legacy_enum_value"] == "new"

    def test_terminal_state(self):
        result = traffit_workflow_state_to_stage_def(
            {"id": 21, "name": "Sample", "sid": "Odrzucenie", "type": "end-bad"},
            order_index=12,
        )
        assert result["is_terminal"] is True
        assert result["terminal_type"] == "rejected"
        assert result["legacy_enum_value"] == "rejected"

    def test_name_fallback_to_sid(self):
        result = traffit_workflow_state_to_stage_def(
            {"id": 99, "name": "", "sid": "MyStage", "type": "screening"},
            order_index=2,
        )
        assert result["name"] == "MyStage"


# ── Faza 5: employee → candidate ─────────────────────────────────────────────


class TestNormalizeCandidateStatus:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("active", "active"),
            ("Aktywny", "active"),
            ("inactive", "passive"),
            ("Nieaktywny", "passive"),
            ("blacklisted", "blacklisted"),
            ("blacklist", "blacklisted"),
            ("", "active"),
            (None, "active"),
            ("unknown_xyz", "active"),
        ],
    )
    def test_mapping(self, raw, expected):
        assert normalize_candidate_status(raw) == expected


class TestTraffitEmployeeToCandidate:
    def test_full_fixture(self):
        payloads = _load("employees_list.json")
        result = traffit_employee_to_candidate(payloads[0])
        assert result["external_id"] == "1246"
        assert result["external_source"] == "traffit"
        assert result["name"] == "Sample"
        assert result["lastname"] == "User"
        assert result["email"] == "user@example.com"
        assert result["phone"] == "+48000000000"
        assert result["status"] == "active"
        assert result["cv_filename"] == "file.pdf"
        # Custom fields all None in fixture → cv_extracted_data empty
        assert result["cv_extracted_data"] == {}
        assert result["source"] == "traffit"

    def test_custom_fields_preserved(self):
        payload = {
            "id": 1,
            "name": "John",
            "lastname": "Doe",
            "_Position": "Senior Backend Engineer",
            "_certificates": "AWS Solutions Architect",
            "_education": None,  # null skipped
        }
        result = traffit_employee_to_candidate(payload)
        assert result["cv_extracted_data"] == {
            "traffit_Position": "Senior Backend Engineer",
            "traffit_certificates": "AWS Solutions Architect",
        }

    def test_identity_snapshot_timestamp_is_normalized_to_utc_aware_iso(self):
        result = traffit_employee_to_candidate(
            {
                "id": 1,
                "name": "Anna",
                "lastname": "Kowalska",
                "updated_at": "2026-08-28 10:15:00",
            }
        )

        assert result["traffit_source_updated_at"] == "2026-08-28T10:15:00+00:00"
        assert result["traffit_raw_name"] == "Anna"
        assert result["traffit_raw_lastname"] == "Kowalska"

    def test_user_id_map_lookup(self):
        payload = {
            "id": 1,
            "name": "X",
            "lastname": "Y",
            "created_by": {"id": 43},
        }
        result = traffit_employee_to_candidate(payload, {"43": 100})
        assert result["created_by"] == 100

    def test_user_not_in_map_no_attribution(self):
        payload = {
            "id": 1,
            "name": "X",
            "lastname": "Y",
            "created_by": {"id": 999},
        }
        result = traffit_employee_to_candidate(payload, {"43": 100})
        assert result["created_by"] is None

    def test_name_fallback_email_localpart(self):
        payload = {
            "id": 1,
            "name": "",
            "lastname": "",
            "email": "alice@example.com",
        }
        result = traffit_employee_to_candidate(payload)
        assert result["name"] == "alice"
        assert result["lastname"] == "?"

    def test_languages_string_normalized_to_list(self):
        payload = {"id": 1, "name": "X", "candidate_languages": "Polish, English"}
        result = traffit_employee_to_candidate(payload)
        assert result["languages"] == [{"lang": "Polish, English", "level": None}]

    def test_location_blob_is_normalized_to_city_country_projection(self):
        payload = {
            "id": 1,
            "name": "X",
            "candidate_location": {
                "locality": "Warszawa",
                "country": "Polska",
                "region1": "Mazowieckie",
            },
        }
        result = traffit_employee_to_candidate(payload)
        assert result["city"] == "Warszawa"
        assert result["country"] == "PL"
        assert result["location"] == "Warszawa, PL"

    def test_no_files(self):
        payload = {"id": 1, "name": "X", "files": []}
        result = traffit_employee_to_candidate(payload)
        assert result["cv_filename"] is None

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_employee_to_candidate({"name": "X"})

    def test_strips_legacy_employed_marker_from_name(self):
        payload = {"id": 1, "name": "Jan", "lastname": "Kowalski [zatrudniony]"}
        result = traffit_employee_to_candidate(payload)
        assert result["name"] == "Jan"
        assert result["lastname"] == "Kowalski"

    def test_marker_only_lastname_falls_back_to_placeholder(self):
        # Field held nothing but the marker → mapper's empty-name fallback.
        payload = {"id": 1, "name": "[ZATRUDNIONY]", "lastname": "", "email": "a@b.pl"}
        result = traffit_employee_to_candidate(payload)
        assert result["name"] == "a"
        assert result["lastname"] == "?"


class TestStripEmploymentMarker:
    def test_bracketed_suffix(self):
        assert strip_employment_marker("Kowalski [zatrudniony]") == "Kowalski"

    def test_parenthesized(self):
        assert strip_employment_marker("Nowak (zatrudniona)") == "Nowak"

    def test_bare_with_dash_separator(self):
        assert strip_employment_marker("Kowalski - zatrudniony") == "Kowalski"

    def test_case_insensitive_and_prefix(self):
        assert strip_employment_marker("[ZATRUDNIONY] Jan") == "Jan"

    def test_embedded_between_tokens(self):
        assert strip_employment_marker("Jan zatrudniony Kowalski") == "Jan Kowalski"

    def test_declension_variants(self):
        assert strip_employment_marker("Anna [zatrudniona]") == "Anna"
        assert strip_employment_marker("Jan [zatrudnionego]") == "Jan"

    def test_marker_only_returns_empty(self):
        assert strip_employment_marker("[zatrudniony]") == ""

    def test_no_marker_is_unchanged(self):
        assert strip_employment_marker("Jan Kowalski") == "Jan Kowalski"

    def test_empty_input_is_unchanged(self):
        assert strip_employment_marker("") == ""

    def test_does_not_eat_glued_surname(self):
        # Bounded declension suffix must not greedily swallow a joined surname.
        assert strip_employment_marker("zatrudnionyNowak") == "Nowak"


# ── Faza 5: recruitment → job ───────────────────────────────────────────────


class TestNormalizeJobStatus:
    def test_is_closed_overrides(self):
        assert normalize_job_status("active", is_closed=True) == "closed"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("active", "published"),
            ("open", "published"),
            ("otwarta", "published"),
            ("draft", "draft"),
            ("closed", "closed"),
            ("zamknięta", "closed"),
            # 0270: nieznana wartość i BRAK wartości znaczą „otwarta", nie
            # „szkic" — patrz `test_absent_status_means_open`.
            ("unknown", "published"),
            (None, "published"),
        ],
    )
    def test_mapping(self, raw, expected):
        assert normalize_job_status(raw) == expected

    def test_absent_status_means_open_not_draft(self):
        """Regresja na 291 rekrutacji ukrytych przed całym systemem.

        Odpowiedź LISTY `/recruitments/` — jedyna, którą czyta importer — nie
        ma klucza `status`; potwierdza to fixture `recruitments_list.json`
        oraz produkcja, gdzie `custom_fields.traffit_raw_status` jest NULL na
        4206 z 4206 zaimportowanych wierszy. Dawne `draft` nie było więc
        informacją ze źródła, tylko wartością domyślną — a ponad dwadzieścia
        powierzchni pyta o `status == published`, żeby ustalić, czy rekrutacja
        jest otwarta. Na produkcji zostawało im 14 rekordów seeda demo.
        """
        assert normalize_job_status(None, is_closed=False) == "published"

    def test_is_closed_still_wins_over_everything(self):
        """Zamknięcie jest jedynym stanem, który źródło podaje wiarygodnie."""
        assert normalize_job_status(None, is_closed=True) == "closed"
        assert normalize_job_status("active", is_closed=True) == "closed"


class TestTraffitRecruitmentToJob:
    def test_full_fixture(self):
        payload = _load("recruitments_detail.json")
        client_map = {str(payload["client"]["id"]): 50}
        workflow_map = {str(payload["workflow_id"]): 200}

        result = traffit_recruitment_to_job(
            payload, client_map, workflow_map, user_id_map={}
        )
        assert result["external_id"] == str(payload["id"])
        assert result["external_source"] == "traffit"
        assert result["client_id"] == 50
        assert result["pipeline_template_id"] == 200
        assert result["title"]  # not empty
        assert result["custom_fields"]["traffit_is_confidential"] in (False, True)

    def test_unknown_client_returns_none(self):
        payload = {"id": 1, "name": "X", "client": {"id": 999}}
        result = traffit_recruitment_to_job(payload, {"1": 50}, {}, None)
        assert result["client_id"] is None

    def test_is_closed_overrides_status(self):
        payload = {"id": 1, "name": "X", "status": "active", "is_closed": True}
        result = traffit_recruitment_to_job(payload, {}, {}, None)
        assert result["status"] == "closed"

    def test_closing_date_parsed_to_date_object(self):
        from datetime import date

        payload = {"id": 1, "name": "X", "closing_date": "2026-12-31 00:00:00"}
        result = traffit_recruitment_to_job(payload, {}, {}, None)
        assert result["deadline"] == date(2026, 12, 31)

    def test_invalid_closing_date_returns_none(self):
        payload = {"id": 1, "name": "X", "closing_date": "not-a-date"}
        result = traffit_recruitment_to_job(payload, {}, {}, None)
        assert result["deadline"] is None

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_recruitment_to_job({"name": "X"}, {}, {}, None)

    def test_opened_at_comes_from_the_source_not_from_import_time(self):
        """Bez tego mediana czasu realizacji wynosi 0 dni.

        `jobs.created_at` jest stemplowane `NOW()` przez `_UPSERT_JOB`, więc dla
        4206 zaimportowanych rekrutacji opisuje moment migracji, a nie start
        u klienta. Prawdziwa data jest w odpowiedzi LISTY i nic nie kosztuje.
        """
        from datetime import datetime, timezone

        payload = _load("recruitments_list.json")[0]
        result = traffit_recruitment_to_job(payload, {}, {}, None)

        assert result["opened_at"] == datetime(
            2022, 8, 9, 9, 59, 10, tzinfo=timezone.utc
        )
        # tz-aware, bo kolumna jest `timestamp with time zone`, a asyncpg
        # odrzuca naiwne wartości.
        assert result["opened_at"].tzinfo is not None

    def test_closed_at_is_set_only_for_a_closed_recruitment(self):
        """`closing_date` otwartej rekrutacji to PLANOWANY termin.

        Wpisanie go do `closed_at` twierdziłoby, że rekrutacja się zamknęła —
        i wpuszczałoby ją do okien czasowych raportów, które filtrują po tej
        kolumnie.
        """
        from datetime import date, datetime, timezone

        payload = dict(_load("recruitments_list.json")[0])
        assert payload["is_closed"] is True
        closed = traffit_recruitment_to_job(payload, {}, {}, None)
        assert closed["closed_at"] == datetime(
            2023, 2, 22, 9, 54, 21, tzinfo=timezone.utc
        )

        payload["is_closed"] = False
        still_open = traffit_recruitment_to_job(payload, {}, {}, None)
        assert still_open["closed_at"] is None
        # Termin zostaje — to dwie różne informacje.
        assert still_open["deadline"] == date(2023, 2, 22)

    def test_missing_source_dates_are_none_not_now(self):
        """Brak daty w źródle nie może zostać podmieniony na „dzisiaj".

        `None` jest sygnałem dla `job_data_trust.duration_available`, żeby
        metryki czasu odpowiedziały „brak danych źródłowych".
        """
        result = traffit_recruitment_to_job({"id": 7, "name": "X"}, {}, {}, None)
        assert result["opened_at"] is None
        assert result["closed_at"] is None


# ── Faza 5: talent → talent_pool ────────────────────────────────────────────


class TestTraffitTalentToPool:
    def test_minimal(self):
        result = traffit_talent_to_pool({"id": 5, "name": "Frontend"})
        assert result["external_id"] == "5"
        assert result["external_source"] == "traffit"
        assert result["name"] == "Frontend"

    def test_empty_name_falls_back(self):
        result = traffit_talent_to_pool({"id": 7, "name": ""})
        assert result["name"] == "Pula #7"

    def test_user_id_map(self):
        result = traffit_talent_to_pool(
            {"id": 1, "name": "X", "created_by": {"id": 42}}, {"42": 100}
        )
        assert result["created_by"] == 100

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_talent_to_pool({"name": "X"})


# ── Faza 5b: select_primary_cv_file ─────────────────────────────────────────


class TestSelectPrimaryCvFile:
    def test_empty(self):
        assert select_primary_cv_file([]) is None

    def test_no_id(self):
        # Files without `id` are not downloadable
        assert select_primary_cv_file([{"name": "cv.pdf"}]) is None

    def test_pdf_preferred_over_docx(self):
        files = [
            {"id": 1, "name": "old.docx"},
            {"id": 2, "name": "new.pdf"},
        ]
        result = select_primary_cv_file(files)
        assert result["id"] == 2

    def test_docx_preferred_over_doc(self):
        files = [
            {"id": 1, "name": "old.doc"},
            {"id": 2, "name": "new.docx"},
        ]
        result = select_primary_cv_file(files)
        assert result["id"] == 2

    def test_unknown_extension_lowest_priority(self):
        files = [
            {"id": 1, "name": "scan.jpg"},
            {"id": 2, "name": "cv.pdf"},
        ]
        result = select_primary_cv_file(files)
        assert result["id"] == 2

    def test_only_unknown_returns_first(self):
        files = [{"id": 7, "name": "scan.jpg"}, {"id": 8, "name": "other.tif"}]
        result = select_primary_cv_file(files)
        assert result is not None
        assert result["id"] == 7


# ── Faza 5b: recruitment_history → candidate_stages ─────────────────────────


class TestTraffitRecruitmentHistoryToStage:
    def test_full_fixture(self):
        # recruitment_history_list[0]: id=19, employee.id=6708, recruitment.id=52,
        # workflow_state.id=19 (type=start)
        history = _load("recruitment_history_list.json")
        record = history[0]

        cand_map = {"6708": 1000}  # Traffit emp 6708 → Nexus candidate 1000
        job_map = {"52": 200}  # Traffit recruitment 52 → Nexus job 200
        sd_id_map = {"19": 50}  # Traffit state 19 → Nexus stage_def 50
        sd_legacy_map = {"19": "new"}

        result = traffit_recruitment_history_to_stage(
            record, cand_map, job_map, sd_id_map, sd_legacy_map, user_id_map={"40": 5}
        )
        assert result is not None
        assert result["external_id"] == "19"
        assert result["candidate_id"] == 1000
        assert result["job_id"] == 200
        assert result["stage_def_id"] == 50
        assert result["stage_legacy_enum"] == "new"
        assert result["moved_by"] == 5

    def test_missing_employee_returns_none(self):
        record = {
            "id": 1,
            "recruitment": {"id": 52},
            "workflow_state": {"id": 19},
            # employee field missing
        }
        result = traffit_recruitment_history_to_stage(record, {}, {}, {}, {}, None)
        assert result is None

    def test_unknown_candidate_returns_none(self):
        record = {
            "id": 1,
            "employee": {"id": 999},
            "recruitment": {"id": 52},
            "workflow_state": {"id": 19},
        }
        result = traffit_recruitment_history_to_stage(
            record, {}, {"52": 200}, {"19": 50}, {"19": "new"}, None
        )
        assert result is None

    def test_unknown_state_falls_back_to_screening(self):
        record = {
            "id": 1,
            "employee": {"id": 100},
            "recruitment": {"id": 200},
            "workflow_state": {"id": 999},  # state not in map
            "date": "2024-01-01 00:00:00",
        }
        result = traffit_recruitment_history_to_stage(
            record, {"100": 1}, {"200": 2}, {}, {}, None
        )
        assert result is not None
        assert result["stage_def_id"] is None
        assert result["stage_legacy_enum"] == "screening"  # default

    def test_contact_tuple_prefers_created_at_over_legacy_move_date(self):
        record = {
            "id": 201,
            "employee": {"id": 100},
            "recruitment": {"id": 200},
            "workflow_state": {"id": 19},
            "date": "2026-07-28 08:00:00",
            "created_at": "2026-07-28 09:00:00",
        }
        result = traffit_recruitment_history_to_stage(
            record,
            {"100": 1},
            {"200": 2},
            {"19": 3},
            {"19": "new"},
            None,
        )
        assert result is not None
        assert result["moved_at"].hour == 8
        assert result["contact_source_created_at"].hour == 9

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_recruitment_history_to_stage(
                {"employee": {"id": 1}}, {}, {}, {}, {}, None
            )


# ── Faza 5b: activity → activity ────────────────────────────────────────────


class TestTraffitActivityToActivity:
    def test_full_fixture(self):
        # employee_activities_list[0]: id=1558, type.id=91, type.value=Sample,
        # content=Sample content, created_by.id=43
        # NOTE: fixture nie ma `employee` field — to global activities listing.
        # Sprawdzę handcrafted payload.
        record = {
            "id": 1558,
            "activity_date": "2022-07-19 06:59:26",
            "type": {"id": 91, "value": "Import - dodany"},
            "content": "Sample content",
            "employee": {"id": 1246},  # global endpoint zawiera employee
            "created_by": {"id": 43},
            "updated_by": {"id": 51},
        }
        result = traffit_activity_to_activity(
            record, {"1246": 500}, user_id_map={"43": 7}
        )
        assert result is not None
        assert result["external_id"] == "1558"
        assert result["entity_type"] == "candidate"
        assert result["entity_id"] == 500
        assert result["action"] == "traffit:Import - dodany"
        assert result["details"]["traffit_type_value"] == "Import - dodany"
        assert result["details"]["content"] == "Sample content"
        assert result["user_id"] == 7
        # Faza A: raw Traffit user IDs in details for SQL-only re-attribution
        assert result["details"]["traffit_created_by_id"] == 43
        assert result["details"]["traffit_updated_by_id"] == 51

    def test_preserves_traffit_user_id_when_user_not_in_map(self):
        # Even if user not in user_id_map, raw Traffit ID should be preserved
        record = {
            "id": 99,
            "type": {"value": "Notatka"},
            "employee": {"id": 1},
            "created_by": {"id": 999},  # not in map
        }
        result = traffit_activity_to_activity(record, {"1": 100}, user_id_map={})
        assert result is not None
        assert result["user_id"] is None
        assert result["details"]["traffit_created_by_id"] == 999

    def test_missing_employee_returns_none(self):
        result = traffit_activity_to_activity(
            {"id": 1, "type": {"id": 1, "value": "X"}}, {}, None
        )
        assert result is None

    def test_unknown_candidate_returns_none(self):
        result = traffit_activity_to_activity(
            {"id": 1, "employee": {"id": 999}, "type": {"value": "X"}},
            {"1": 100},
            None,
        )
        assert result is None

    def test_unknown_type_falls_back_to_unknown(self):
        result = traffit_activity_to_activity(
            {"id": 1, "employee": {"id": 1}}, {"1": 100}, None
        )
        assert result is not None
        assert result["action"] == "traffit:unknown"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_activity_to_activity({"employee": {"id": 1}}, {}, None)


# ── Faza 5b: source → candidate.tags ────────────────────────────────────────


class TestTraffitSourceToCandidateTag:
    def test_full_payload(self):
        record = {
            "id": 5001,
            "employee": {"id": 1246},
            "dictionary_item": {"id": 150, "value": "LinkedIn"},
            "domain": "linkedin.com",
            "url": "https://linkedin.com/in/sample",
        }
        result = traffit_source_to_candidate_tag(record, {"1246": 500})
        assert result["candidate_id"] == 500
        tag = result["tag"]
        assert tag["type"] == "traffit_source"
        assert tag["source_id"] == 5001
        assert tag["value"] == "LinkedIn"
        assert tag["domain"] == "linkedin.com"

    def test_unknown_employee(self):
        result = traffit_source_to_candidate_tag(
            {"id": 1, "employee": {"id": 999}}, {"1": 100}
        )
        assert result is None

    def test_missing_id_returns_none(self):
        result = traffit_source_to_candidate_tag({"employee": {"id": 1}}, {})
        assert result is None


# ── Faza A: select_all_files_with_priority ──────────────────────────────────


class TestSelectAllFilesWithPriority:
    def test_empty_returns_empty_list(self):
        assert select_all_files_with_priority([]) == []

    def test_single_file_marked_primary(self):
        result = select_all_files_with_priority([{"id": 1, "name": "cv.pdf"}])
        assert len(result) == 1
        assert result[0]["is_primary"] is True

    def test_priority_ordering_pdf_then_docx_then_doc(self):
        files = [
            {"id": 3, "name": "letter.doc"},
            {"id": 2, "name": "cv.docx"},
            {"id": 1, "name": "resume.pdf"},
        ]
        result = select_all_files_with_priority(files)
        assert [f["id"] for f in result] == [1, 2, 3]
        assert result[0]["is_primary"] is True
        assert result[1]["is_primary"] is False
        assert result[2]["is_primary"] is False

    def test_unknown_extension_goes_last(self):
        files = [
            {"id": 1, "name": "scan.png"},
            {"id": 2, "name": "cv.pdf"},
        ]
        result = select_all_files_with_priority(files)
        assert result[0]["id"] == 2
        assert result[1]["id"] == 1

    def test_files_without_id_skipped(self):
        result = select_all_files_with_priority(
            [{"name": "noid.pdf"}, {"id": 5, "name": "ok.pdf"}]
        )
        assert len(result) == 1
        assert result[0]["id"] == 5

    def test_does_not_mutate_input(self):
        files = [{"id": 1, "name": "cv.pdf"}, {"id": 2, "name": "x.docx"}]
        result = select_all_files_with_priority(files)
        # Mutation happens only on result copies
        assert "is_primary" not in files[0]
        assert "is_primary" not in files[1]
        assert result[0]["is_primary"] is True


# ── Faza A: traffit_user_to_nexus + normalize_traffit_role ──────────────────


class TestNormalizeTraffitRole:
    @pytest.mark.parametrize(
        "group_name,expected",
        [
            ("Rekruterzy", "recruiter"),
            ("Recruiters", "recruiter"),
            ("Admin", "admin"),
            ("Administratorzy", "admin"),
            ("Manager", "delivery_lead"),
            ("Lead Delivery", "delivery_lead"),
            ("Sourcerzy", "sourcer"),
            ("TAC", "tac"),
            (None, "recruiter"),
            ("", "recruiter"),
            ("Nieznana grupa XYZ", "recruiter"),  # default fallback
        ],
    )
    def test_known_and_unknown(self, group_name, expected):
        assert normalize_traffit_role(group_name) == expected


class TestTraffitUserToNexus:
    def test_full_payload(self):
        payload = {
            "id": 28,
            "username": "jakub.petryna@b2bnetwork.pl",
            "email": "jakub.petryna@b2bnetwork.pl",
            "is_active": False,
            "permission_group": {"id": 3, "name": "Rekruterzy"},
        }
        result = traffit_user_to_nexus(payload)
        assert result["external_id"] == "28"
        assert result["external_source"] == "traffit"
        assert result["email"] == "jakub.petryna@b2bnetwork.pl"
        assert result["name"] == "Jakub Petryna"  # email-localpart fallback
        assert result["role"] == "recruiter"
        assert result["is_active"] is False
        assert result["password_hash"] == "!imported-from-traffit-no-login!"

    def test_with_explicit_name_lastname(self):
        payload = {
            "id": 39,
            "email": "hubert@b2bnetwork.pl",
            "name": "Hubert",
            "lastname": "Balcerowicz",
            "is_active": True,
            "permission_group": {"name": "Admin"},
        }
        result = traffit_user_to_nexus(payload)
        assert result["name"] == "Hubert Balcerowicz"
        assert result["role"] == "admin"
        assert result["is_active"] is True

    def test_missing_email_raises(self):
        with pytest.raises(ValueError, match="missing or invalid email"):
            traffit_user_to_nexus({"id": 1})

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_user_to_nexus({"email": "x@y.pl"})

    def test_username_fallback_to_email(self):
        # Some Traffit tenants store email only in `username`
        payload = {
            "id": 5,
            "username": "user@b2bnetwork.pl",
            "is_active": True,
            "permission_group": {"name": "Rekruterzy"},
        }
        result = traffit_user_to_nexus(payload)
        assert result["email"] == "user@b2bnetwork.pl"

    def test_email_lowercased(self):
        result = traffit_user_to_nexus(
            {"id": 1, "email": "FOO@B2B.pl", "is_active": True}
        )
        assert result["email"] == "foo@b2b.pl"


class TestStateNameMapping:
    """Semantyka, której `state.type` nie niesie.

    Traffit nie ma typu odpowiadającego „rozmowa u klienta" ani „klient
    zaakceptował": `client_verification` mapuje na `cv_sent`, a `initial_accept`
    na `verified`. Fakt żyje w NAZWIE stanu — i to ją widzi rekruter. Bez tego
    mapowania `acceptance` miał 7 wystąpień w 2026 (same ręczne ruchy) wobec
    228 placementów, przez co kafel pokazywał 3257,1%.
    """

    def test_client_interview_comes_from_the_state_name(self):
        mapping = map_traffit_state_to_pipeline(
            {"type": "interview", "name": "Interview u klienta"}
        )
        assert mapping["legacy"] == "client_interview"
        assert mapping["category"] == "external"

    def test_client_acceptance_comes_from_the_state_name(self):
        mapping = map_traffit_state_to_pipeline(
            {"type": "initial_accept", "name": "Zaakceptowany"}
        )
        assert mapping["legacy"] == "acceptance"

    def test_duplicate_suffix_added_by_the_importer_does_not_break_matching(self):
        """Importer dokleja `(#41)` przy zdublowanych nazwach w jednym workflow."""
        mapping = map_traffit_state_to_pipeline(
            {"type": "screening", "name": "Zaakceptowany (#41)"}
        )
        assert mapping["legacy"] == "acceptance"

    def test_diacritics_and_case_do_not_matter(self):
        assert (
            map_traffit_state_to_pipeline({"name": "ZAAKCEPTOWANY"})["legacy"]
            == "acceptance"
        )

    def test_verification_stage_is_not_swallowed_by_the_acceptance_rule(self):
        """„Kandydat Zweryfikowany" MUSI zostać `verified` — to kotwica KPI."""
        mapping = map_traffit_state_to_pipeline(
            {"type": "initial_accept", "name": "Kandydat Zweryfikowany"}
        )
        assert mapping["legacy"] == "verified"

    def test_unrelated_names_still_fall_through_to_the_type_map(self):
        mapping = map_traffit_state_to_pipeline(
            {"type": "client_verification", "name": "Wysłany do Klienta"}
        )
        assert mapping["legacy"] == "cv_sent"

    def test_rejection_flag_still_wins_over_the_name(self):
        """`is_rejection` jest nadrzędne — inaczej odrzucenie udawałoby akceptację."""
        mapping = map_traffit_state_to_pipeline(
            {"type": "initial_accept", "name": "Zaakceptowany", "is_rejection": True}
        )
        assert mapping["legacy"] == "rejected"
        assert mapping["terminal_type"] == "rejected"

    def test_sid_is_used_when_the_state_has_no_name(self):
        mapping = map_traffit_state_to_pipeline(
            {"type": "interview", "name": "", "sid": "Interview u klienta"}
        )
        assert mapping["legacy"] == "client_interview"
