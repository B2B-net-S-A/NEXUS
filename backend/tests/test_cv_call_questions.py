"""Pytania pod CV w ściądze: mapa wymagania × role i co wolno pokazać z modelu.

Dane fikcyjne. Trasy i zapis sprawdza ``test_cv_call_questions_api.py``.
"""

from __future__ import annotations

import json

import pytest

from app.services import cv_call_questions as cq
from app.services import dz_review as dz


def _req(label: str) -> dz.Requirement:
    return dz.Requirement(label=label, alternatives=(label,), terms=(label.casefold(),))


def _role(
    company: str,
    desc: str = "",
    technologies: tuple[str, ...] = (),
    detail: bool = True,
) -> dz.Role:
    return dz.Role(
        label=f"Developer · {company}",
        company=company,
        text=desc,
        title="Developer",
        desc=desc,
        technologies=technologies,
        detail=detail,
    )


ROLES = [
    _role("Alfa", "Budował hurtownię w Oracle i migrował procesy ETL.", ("Kafka",)),
    _role("Beta", "Prowadził zespół analityków."),
]


class TestRequirementMap:
    def _state(self, label: str, *, cv_text: str = "") -> cq.RequirementRow:
        return cq.requirement_map([_req(label)], ROLES, cv_text)[0]

    def test_description_in_any_role_means_described(self) -> None:
        row = self._state("Oracle")
        assert row.state == cq.DESCRIBED
        assert row.roles == (cq.DESCRIBED, cq.ABSENT)

    def test_technology_list_alone_is_not_a_description(self) -> None:
        row = self._state("Kafka", cv_text="Kafka")
        assert row.state == cq.LISTED
        assert row.roles == (cq.LISTED, cq.ABSENT)

    def test_found_only_outside_roles(self) -> None:
        assert self._state("Python", cv_text="Języki: Python").state == cq.UNROLED

    def test_not_in_cv_at_all(self) -> None:
        assert self._state("Liquibase", cv_text="Języki: Python").state == cq.ABSENT

    def test_role_without_description_is_unverified_not_absent(self) -> None:
        roles = [_role("Gamma", detail=False)]
        row = cq.requirement_map([_req("Oracle")], roles, "")[0]
        assert row.roles == (cq.UNVERIFIED,)
        assert row.state == cq.ABSENT

    def test_described_wins_over_listing_in_another_role(self) -> None:
        roles = [
            _role("Alfa", "Inne zadania.", ("Oracle",)),
            _role("Beta", "Pisał procedury w Oracle."),
        ]
        row = cq.requirement_map([_req("Oracle")], roles, "")[0]
        assert row.state == cq.DESCRIBED
        assert row.roles == (cq.LISTED, cq.DESCRIBED)


class TestPromptPayload:
    def test_only_gaps_and_roles_reach_the_model(self) -> None:
        rows = cq.requirement_map([_req("Oracle"), _req("Kafka")], ROLES, "")
        payload = cq.prompt_payload("Programista", rows, ROLES)
        assert [w["nazwa"] for w in payload["wymagania"]] == ["Kafka"]
        assert payload["wymagania"][0]["role_tylko_lista"] == ["Alfa"]
        assert [s["firma"] for s in payload["stanowiska"]] == ["Alfa", "Beta"]

    def test_long_role_description_is_cut(self) -> None:
        role = _role("Alfa", "x" * (cq.ROLE_DESC_CHARS + 50))
        rows = cq.requirement_map([_req("Kafka")], [role], "")
        payload = cq.prompt_payload(None, rows, [role])
        assert len(payload["stanowiska"][0]["opis"]) == cq.ROLE_DESC_CHARS


class TestParseQuestions:
    ROWS = cq.requirement_map(
        [_req("Kafka"), _req("Liquibase"), _req("Oracle")], ROLES, ""
    )

    def _parse(self, *items: dict) -> list[dict]:
        return cq.parse_questions(
            json.dumps({"questions": list(items)}), self.ROWS, ROLES
        )

    def _item(self, requirement: str = "Kafka", **extra: str) -> dict:
        return {
            "requirement": requirement,
            "company": "Alfa",
            "question": "Jak wyglądała Twoja praca z tym narzędziem w Alfie?",
            **extra,
        }

    def test_state_comes_from_the_map_not_from_the_model(self) -> None:
        out = self._parse(self._item(state=cq.ABSENT))
        assert out[0]["state"] == cq.LISTED
        assert out[0]["company"] == "Alfa"

    def test_requirement_outside_the_gaps_is_dropped(self) -> None:
        out = self._parse(
            self._item("Oracle"), self._item("COBOL"), self._item("Liquibase")
        )
        assert [q["requirement"] for q in out] == ["Liquibase"]

    def test_company_outside_the_roles_is_cleared(self) -> None:
        out = self._parse(self._item(company="Firma klienta"))
        assert out[0]["company"] == ""

    @pytest.mark.parametrize(
        "question",
        [
            "Co konkretnie robiłeś/aś w tym projekcie?",
            "Czy używałeś tego narzędzia w Alfie?",
            "Czy robiłaś to na co dzień w Alfie?",
            "Jaka jest Twoja stawka 150 PLN/h w tej roli?",
            "Czy jesteś dostępny od zaraz w tym projekcie?",
            "Krótkie",
            "x" * (cq.QUESTION_MAX_CHARS + 1),
        ],
    )
    def test_unusable_question_is_dropped(self, question: str) -> None:
        out = self._parse(self._item(question=question), self._item("Liquibase"))
        assert [q["requirement"] for q in out] == ["Liquibase"]

    def test_one_question_per_requirement_in_map_order(self) -> None:
        out = self._parse(
            self._item("Liquibase"),
            self._item("Kafka"),
            self._item("Kafka", question="Do czego służyła Kafka w Twoim projekcie?"),
        )
        assert [q["requirement"] for q in out] == ["Kafka", "Liquibase"]
        assert out[0]["question"].startswith("Jak wyglądała")

    def test_list_is_capped(self) -> None:
        labels = [f"Narzędzie{i}" for i in range(cq.MAX_QUESTIONS + 2)]
        rows = cq.requirement_map([_req(x) for x in labels], ROLES, "")
        raw = json.dumps({"questions": [self._item(x) for x in labels]})
        assert len(cq.parse_questions(raw, rows, ROLES)) == cq.MAX_QUESTIONS

    @pytest.mark.parametrize(
        "raw",
        [
            '{"questions": []}',
            '{"questions": [{"requirement": "Kafka", "company": "Alfa", '
            '"question": "Czy używałeś Kafki w Firmie Alfa?"}]}',
        ],
    )
    def test_gaps_without_a_usable_question_raise(self, raw: str) -> None:
        with pytest.raises(ValueError):
            cq.parse_questions(raw, self.ROWS, ROLES)

    def test_no_gaps_and_no_questions_is_a_valid_empty_list(self) -> None:
        rows = cq.requirement_map([_req("Oracle")], ROLES, "")
        assert cq.parse_questions('{"questions": []}', rows, ROLES) == []

    @pytest.mark.parametrize("raw", ["nie json", "[]", '{"inne": 1}'])
    def test_broken_response_raises_instead_of_empty_list(self, raw: str) -> None:
        with pytest.raises(ValueError):
            cq.parse_questions(raw, self.ROWS, ROLES)
