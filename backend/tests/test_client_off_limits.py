"""Off-limits: reguły bez bazy (``services/client_off_limits.py``, 21.10.2026)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import client_off_limits as ol


def _candidate(**over):
    base = {
        "id": 7,
        "name": "Anna",
        "lastname": "Testowa",
        "linkedin_current_company": None,
        "experience": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


LABELS = sorted(
    [
        ("nordea", 1, "Nordea"),
        ("bnp paribas", 2, "BNP Paribas"),
        ("bnp paribas cardif", 3, "Cardif"),
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)


class TestConfirmationHeader:
    def test_reads_known_answers(self):
        raw = '{"12": "linkedin_inbound", "13": "skip"}'
        assert ol.parse_confirmation_header(raw) == {12: "linkedin_inbound", 13: "skip"}

    @pytest.mark.parametrize(
        "raw", [None, "", "nie-json", "[1, 2]", '{"x": "job_ad"}', '{"5": "cokolwiek"}']
    )
    def test_anything_else_means_no_confirmation(self, raw):
        assert ol.parse_confirmation_header(raw) == {}

    def test_keeps_valid_entries_next_to_invalid_ones(self):
        raw = '{"5": "referral", "6": 1, "abc": "job_ad"}'
        assert ol.parse_confirmation_header(raw) == {5: "referral"}

    @pytest.mark.parametrize(
        "raw", ["[" * 20_000, '{"1": ' * 20_000], ids=["lista", "slownik"]
    )
    def test_deeply_nested_json_means_no_confirmation(self, raw):
        # Audyt 22.10 (F111): json.loads rzucał RecursionError, którego parser
        # nie łapał — 500 na dowolnej trasie, także bez logowania. Python
        # 3.12 rzuca go od ok. 10 tys. poziomów, 20 tys. „[” mieści się
        # w limicie nagłówka (16 KB).
        assert ol.parse_confirmation_header(raw) == {}


class TestCompanyMatch:
    @pytest.mark.parametrize(
        "company",
        ["Nordea", "Nordea Bank Abp", "NORDEA Sp. z o.o.", "nordea-it centre"],
    )
    def test_company_starting_with_client_name_matches(self, company):
        assert ol._match_label(company, LABELS) == (1, "Nordea")

    @pytest.mark.parametrize("company", ["Nordeax", "Bank Nordea", "", "Comarch"])
    def test_other_companies_do_not_match(self, company):
        assert ol._match_label(company, LABELS) is None

    def test_longest_client_name_wins(self):
        assert ol._match_label("BNP Paribas Cardif Polska", LABELS) == (3, "Cardif")
        assert ol._match_label("BNP Paribas Bank Polska", LABELS) == (2, "BNP Paribas")


class TestCurrentCompanies:
    def test_linkedin_first_then_cv_entry_that_says_current(self):
        candidate = _candidate(
            linkedin_current_company="Nordea Bank Abp",
            experience=[
                {"company": "Alior", "start": "2021-01", "end": None},
                {"company": "Comarch", "start": "2018-01", "end": "2020-12"},
            ],
        )
        assert ol.current_companies(candidate) == [
            ("Nordea Bank Abp", "linkedin"),
            ("Alior", "cv"),
        ]

    def test_undated_cv_entry_is_an_import_artefact_not_a_current_job(self):
        candidate = _candidate(experience=[{"company": "Nordea", "end": None}])
        assert ol.current_companies(candidate) == []

    def test_present_word_counts_as_current(self):
        candidate = _candidate(experience=[{"company": "Nordea", "end": "obecnie"}])
        assert ol.current_companies(candidate) == [("Nordea", "cv")]

    def test_find_hit_names_client_and_source(self):
        candidate = _candidate(
            experience=[{"company": "Nordea Bank", "start": "2022-03", "end": ""}]
        )
        hit = ol.find_hit(candidate, LABELS)
        assert hit == ol.OffLimitsHit(
            client_id=1, client_name="Nordea", company="Nordea Bank", source="cv"
        )

    def test_no_labels_no_hit(self):
        candidate = _candidate(linkedin_current_company="Nordea")
        assert ol.find_hit(candidate, []) is None


class TestDetailAndBadge:
    def _person(self, candidate_id=7, name="Anna Testowa"):
        hit = ol.OffLimitsHit(
            client_id=1, client_name="Nordea", company="Nordea Bank", source="linkedin"
        )
        return ol.OffLimitsPerson(candidate_id=candidate_id, name=name, hit=hit)

    def test_detail_for_one_person_names_person_and_company(self):
        detail = ol.OffLimitsConfirmationRequired([self._person()]).detail()
        assert detail["code"] == ol.CONFIRMATION_REQUIRED_CODE
        assert "Anna Testowa" in detail["message"]
        assert "Nordea" in detail["message"]
        assert detail["candidates"] == [
            {
                "candidate_id": 7,
                "name": "Anna Testowa",
                "company": "Nordea Bank",
                "client_name": "Nordea",
                "source": "linkedin",
            }
        ]

    def test_detail_for_many_people_counts_them(self):
        detail = ol.OffLimitsConfirmationRequired(
            [self._person(1), self._person(2)]
        ).detail()
        assert detail["message"].startswith("2 osoby")
        assert [c["candidate_id"] for c in detail["candidates"]] == [1, 2]

    def test_badge_from_entry_meta(self):
        meta = {
            "kind": "auto_match",
            "off_limits": ol.confirmation_meta(
                self._person(), how="linkedin_inbound", actor_user_id=5
            ),
        }
        badge = ol.off_limits_badge(meta, {5: "Jan Rekruter"})
        assert badge is not None
        assert badge["client_name"] == "Nordea"
        assert badge["how_label"] == ol.HOW_LABELS["linkedin_inbound"]
        assert badge["confirmed_by_name"] == "Jan Rekruter"
        assert badge["confirmed_at"]

    @pytest.mark.parametrize(
        "meta",
        [None, "x", {}, {"off_limits": "x"}, {"off_limits": {"how": "skip"}}],
    )
    def test_no_badge_without_a_known_confirmation(self, meta):
        assert ol.off_limits_badge(meta) is None


@pytest.mark.asyncio
async def test_middleware_exposes_header_only_for_the_request():
    seen: list[dict[int, str]] = []

    async def app(scope, receive, send):
        seen.append(ol.current_confirmations())

    middleware = ol.OffLimitsConfirmationMiddleware(app)
    scope = {
        "type": "http",
        "headers": [(b"x-off-limits-confirmation", b'{"9": "job_ad"}')],
    }
    await middleware(scope, None, None)
    assert seen == [{9: "job_ad"}]
    assert ol.current_confirmations() == {}


@pytest.mark.asyncio
async def test_middleware_passes_request_with_deeply_nested_header():
    seen: list[dict[int, str]] = []

    async def app(scope, receive, send):
        seen.append(ol.current_confirmations())

    middleware = ol.OffLimitsConfirmationMiddleware(app)
    scope = {
        "type": "http",
        "headers": [(b"x-off-limits-confirmation", b"[" * 15_000)],
    }
    await middleware(scope, None, None)
    assert seen == [{}]
