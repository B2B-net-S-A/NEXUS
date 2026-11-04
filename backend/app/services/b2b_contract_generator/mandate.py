"""Umowa zlecenia z Generatora Umów (decyzje Artura 26.10.2026).

Ten sam rejestr co umowa B2B (``b2b_generated_contracts``,
``contract_kind = "mandate"``), ale własny formularz i wzór:
``templates/contract/umowa_zlecenie_pl.{docx,html}`` budowany skryptem
``scripts/build_mandate_contract_template.py`` ze wzoru działu.

* **Bez numeru** — zlecenia nie mają numerów (Excel działu, aneks
  i porozumienie zlecenia identyfikują umowę datą zawarcia). Wiersz rejestru
  nosi etykietę „Zlecenie z dnia DD.MM.RRRR” i nie zajmuje numeru z puli B2B.
* **PESEL, dowód i adres zamieszkania tylko w pliku** — ``stored_payload``
  ich nie zapisuje. Ponowne pobranie z rejestru wydaje plik z kropkami
  w tych miejscach (do wpisania ręcznie).
* **DPA (Załącznik nr 2) opcjonalne** — przełącznik i cel przetwarzania
  do edycji; domyślny cel to tekst wzoru.
* **Minimalna stawka godzinowa** — ta sama tabela co Płace
  (``payroll_rates``), sprawdzana dla każdego roku okresu zlecenia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.schemas.b2b_contract_generator import B2BMandateRenderRequest
from app.services.academy_documents import pesel_valid
from app.services.b2b_contract_generator.formatting import format_rate, pl_date
from app.services.b2b_contract_generator.gender import gender_forms
from app.services.b2b_contract_generator.number_words import rate_in_words
from app.services.b2b_documents.company_party import company_party
from app.services.b2b_documents.render import render_docx_file, render_html_file
from app.services.hr import payroll_rates

MANDATE_KIND = "mandate"

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "contract"
DOCX_TEMPLATE = _TEMPLATE_DIR / "umowa_zlecenie_pl.docx"
HTML_TEMPLATE = _TEMPLATE_DIR / "umowa_zlecenie_pl.html"

#: § 2 ust. 3 DPA ze wzoru z 04.09.2026 — pisany pod jedno zlecenie, więc
#: w formularzu jest do edycji.
DEFAULT_DPA_PURPOSE = (
    "wykonywanie czynności administracyjnych, wdrożeniowych, monitoringowych "
    "i utrzymaniowych dotyczących platformy AI oraz infrastruktury, określonych "
    "w § 1 Umowy Zlecenia."
)

#: Pola, które idą wyłącznie do pliku.
SENSITIVE_FIELDS = ("home_address", "id_document", "pesel")

_LETTERS = "abcdefghij"


class MandateError(ValueError):
    """Odmowa z komunikatem dla użytkownika (422)."""


def mandate_label(signing_date: date | None) -> str:
    """Etykieta wiersza rejestru w miejscu numeru umowy."""
    return f"Zlecenie z dnia {pl_date(signing_date)}"


def is_mandate(row: Any) -> bool:
    return (
        getattr(row, "contract_kind", None) == MANDATE_KIND
        and (getattr(row, "source", None) or "generator") == "generator"
    )


def validate(payload: B2BMandateRenderRequest, rates: dict[int, Decimal]) -> None:
    """PESEL z cyfrą kontrolną i stawka nie niższa niż minimum każdego roku
    okresu zlecenia (rok bez minimum w tabeli = bez kontroli, jak w Płacach)."""
    pesel = (payload.pesel or "").strip()
    if pesel and not pesel_valid(pesel):
        raise MandateError("PESEL ma 11 cyfr i poprawną cyfrę kontrolną.")
    rate = Decimal(str(payload.gross_hourly_rate))
    for year in range(payload.period_from.year, payload.period_to.year + 1):
        minimum = payroll_rates.mandate_minimum_shortfall(
            employment_type=payroll_rates.MANDATE_FORM,
            hourly_rate=rate,
            currency="PLN",
            year=year,
            rates=rates,
        )
        if minimum is not None:
            raise MandateError(
                f"Minimalna stawka na zleceniu w {year} to "
                f"{payroll_rates.format_pln(minimum)} zł/h brutto."
            )


def stored_payload(payload: B2BMandateRenderRequest) -> dict[str, Any]:
    """``render_payload`` wiersza: formularz bez danych wrażliwych."""
    data = payload.model_dump(mode="json", exclude=set(SENSITIVE_FIELDS))
    data["kind"] = MANDATE_KIND
    return data


def payload_from_row(render_payload: dict[str, Any]) -> B2BMandateRenderRequest:
    clean = {k: v for k, v in render_payload.items() if k != "kind"}
    return B2BMandateRenderRequest(**clean)


def _task_items(tasks: list[str]) -> list[dict[str, str]]:
    last = len(tasks) - 1
    return [
        {"letter": _LETTERS[i], "text": text, "sep": "." if i == last else ";"}
        for i, text in enumerate(tasks)
    ]


def _blank(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def build_context(payload: B2BMandateRenderRequest) -> dict[str, Any]:
    rate = payload.gross_hourly_rate
    purpose = _blank(payload.dpa_purpose) or DEFAULT_DPA_PURPOSE
    return {
        "company": company_party("pl"),
        "g": gender_forms(payload.gender),
        "partner": {
            "name": payload.partner_name,
            "name_instrumental": _blank(payload.partner_instrumental),
            "phone": _blank(payload.partner_phone),
            "email": _blank(payload.partner_email),
            "home_address": _blank(payload.home_address),
            "id_document": _blank(payload.id_document),
            "pesel": _blank(payload.pesel),
        },
        "doc": {
            "task_items": _task_items(payload.tasks),
            "period_from": pl_date(payload.period_from),
            "period_to": pl_date(payload.period_to),
            "gross_hourly_rate": format_rate(rate),
            "gross_hourly_rate_words": rate_in_words(rate, "pl", "PLN"),
            "with_dpa": payload.with_dpa,
            "dpa_purpose": purpose,
        },
        "document_date": pl_date(payload.signing_date),
    }


def render_docx(payload: B2BMandateRenderRequest) -> bytes:
    return render_docx_file(DOCX_TEMPLATE, build_context(payload))


def render_html(payload: B2BMandateRenderRequest) -> str:
    return render_html_file(HTML_TEMPLATE, build_context(payload))
