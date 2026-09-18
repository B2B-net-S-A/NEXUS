"""Niezależna kontrola AI gotowego CV — DODATEK, nigdy bramka.

Recenzentem jest INNY model niż generator (`cv_factual_verification` = GPT Luna
wobec `cv_generator` = Sonnet 5). Badanie modeli z 16.09.2026 zmierzyło, że
sędzia LLM faworyzuje własne wyjście, więc model oceniający własne CV jest
systematycznie zbyt łagodny — niezależność recenzenta jest tu CAŁĄ funkcją,
nie szczegółem konfiguracji.

Kontrakt tego modułu: **`run_final_review` nigdy nie rzuca**. Trzy awarie
generatora w dwa dni (09–10.09.2026) miały jeden mechanizm — wywołanie modelu
wstawione jako WARUNEK wykonania ścieżki, która wcześniej działała
deterministycznie. Wynik recenzji może wzbogacić dokument i ostrzec rekrutera;
nie może zabrać CV, za które już zapłacono. Twarda bramka istnieje osobno
(`CV_SOURCE_EVIDENCE_ENFORCED`) i ma zostać domyślnie wyłączona do czasu
pomiaru, ile z uwag to fałszywe alarmy.

Wyłącznik: `CV_FINAL_REVIEW_ENABLED` (domyślnie ON). Budżet całej recenzji:
`CV_FINAL_REVIEW_TIMEOUT` (domyślnie 120 s, dzielony między paczki).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for
from app.services.ai_quota import QuotaState, declared_call
from app.services.claude_client import env_number
from app.services.cv_generator_b2b.factual_verification import (
    FactualVerificationError,
    VERIFIER_VERSION,
    factual_projection,
    verify_final_cv,
)
from app.services.cv_generator_b2b.provider import CVGeneratorAIError

logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT = 120.0

# Ten sam prefiks co `_fabrication_warnings` — front rozpoznaje po nim
# ostrzeżenie „pewne" (`CV_CERTAIN_WARNING_PREFIXES` w lib/cv-generator.ts)
# i sam rozwija wiersz CV wysyłanego do klienta. Rozjazd tych stringów nie
# wywala niczego: po prostu uwagi przestają się rozwijać i nikt ich nie czyta.
_HIGH_PREFIX = {"pl": "BRAK POKRYCIA", "en": "NOT IN SOURCE"}
_SOFT_PREFIX = {"pl": "WERYFIKUJ", "en": "VERIFY"}

# Przeniesione ze `standalone_service` (gałąź egzekwowania), żeby obie ścieżki
# nazywały pola tak samo — inaczej ten sam defekt czyta się inaczej w zależności
# od tego, czy bramka jest włączona.
FIELD_LABELS: dict[str, dict[str, str]] = {
    "pl": {
        "why_points": "podsumowanie",
        "experience": "doświadczenie",
        "certifications": "certyfikaty",
        "skills": "umiejętności",
        "languages": "języki",
        "education": "edukacja",
        "name": "imię i nazwisko",
        "first_name": "imię",
        "position": "stanowisko",
    },
    "en": {
        "why_points": "summary",
        "experience": "experience",
        "certifications": "certifications",
        "skills": "skills",
        "languages": "languages",
        "education": "education",
        "name": "full name",
        "first_name": "first name",
        "position": "position",
    },
}
_FALLBACK_LABEL = {"pl": "dane kandydata", "en": "candidate data"}

_REASON_SUFFIX = {
    "pl": {
        "unsupported": "brak potwierdzenia w CV i notatkach",
        "contradicted": "sprzeczne ze źródłem",
        "invalid_evidence": "recenzent nie wskazał poprawnego cytatu",
        "private": "treść z notatek prywatnych / ocen rekrutera",
    },
    "en": {
        "unsupported": "not confirmed in the CV or notes",
        "contradicted": "contradicts the source",
        "invalid_evidence": "the reviewer gave no valid citation",
        "private": "content from private notes / recruiter assessment",
    },
}


def final_review_enabled() -> bool:
    """Czy niezależna kontrola AI treści CV ma się w ogóle wykonać.

    Domyślnie ON — decyzja Artura z 18.09.2026. Wyłączenie zdejmuje wydatek
    i wszystkie uwagi, nie zmieniając niczego innego w generacji.
    """

    return os.getenv("CV_FINAL_REVIEW_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def final_review_timeout() -> float:
    """Budżet czasu na CAŁĄ recenzję (wszystkie paczki razem)."""

    return env_number("CV_FINAL_REVIEW_TIMEOUT", _DEFAULT_TIMEOUT, float)


_REVIEW_DECLARATION: ContextVar[tuple[int | None, QuotaState] | None] = ContextVar(
    "cv_final_review_declaration", default=None
)


@contextmanager
def review_declaration(*, user_id: int | None, state: QuotaState):
    """Zadeklaruj NALICZONY już kubełek recenzenta dla pracy w tle.

    Wchodzi się w to w korutynie, która zaraz wywoła `run_in_threadpool`:
    anyio kopiuje mapę contextvarów do wątku, więc synchroniczny pipeline
    widzi deklarację, a tokeny recenzenta lądują na JEGO operacji zamiast na
    operacji generatora. Bez tego funkcja działa, ale w Ustawieniach → AI
    kubełek `cv_factual_verification` stoi na zerze i nie da się odpowiedzieć,
    ile kosztuje samo sprawdzanie.
    """

    token = _REVIEW_DECLARATION.set((user_id, state))
    try:
        yield
    finally:
        _REVIEW_DECLARATION.reset(token)


def _lang(language: str | None) -> str:
    return "en" if (language or "").lower().startswith("en") else "pl"


def _claim_snippet(projection: dict[str, Any], path: str) -> str:
    """Wartość twierdzenia spod ścieżki JSON — z DOKUMENTU, nigdy ze źródeł."""

    node: Any = projection
    for part in path.strip("/").split("/"):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
    if not isinstance(node, str):
        return ""
    text = " ".join(node.split())
    return text if len(text) <= 90 else text[:89].rstrip() + "…"


def _field_label(path: str, lang: str) -> str:
    key = path.strip("/").split("/")[0] if path.strip("/") else ""
    return FIELD_LABELS[lang].get(key, _FALLBACK_LABEL[lang])


def review_warnings(
    report: dict[str, Any], data: dict[str, Any], language: str | None = None
) -> list[str]:
    """Uwagi recenzenta w kształcie, który front już umie pokazać."""

    status = report.get("status")
    lang = _lang(language)
    high = _HIGH_PREFIX[lang]
    soft = _SOFT_PREFIX[lang]
    if status == "unavailable":
        reason = report.get("reason") or "unknown"
        return [
            f"{soft}: niezależna kontrola AI treści CV nie wykonała się "
            f"({reason}) — sprawdź CV ręcznie z oryginałem."
            if lang == "pl"
            else f"{soft}: the independent AI review did not run ({reason}) — "
            "check the CV against the original by hand."
        ]
    if status != "advisory":
        return []

    projection = factual_projection(data)
    statuses = report.get("statuses") or {}
    issues: list[str] = []
    for path in report.get("paths") or []:
        verdict = statuses.get(path, "unsupported")
        label = _field_label(path, lang)
        snippet = _claim_snippet(projection, path)
        suffix = _REASON_SUFFIX[lang].get(verdict, _REASON_SUFFIX[lang]["unsupported"])
        prefix = soft if verdict == "private" else high
        quoted = (
            f" „{snippet}”"
            if snippet and lang == "pl"
            else (f' "{snippet}"' if snippet else "")
        )
        issues.append(
            f"{prefix} (kontrola AI): {label} —{quoted} ({suffix})"
            if lang == "pl"
            else f"{prefix} (AI review): {label} —{quoted} ({suffix})"
        )
    if not issues:
        # Odrzucenie protokolarne (np. model oddał niepoprawny JSON): nie ma
        # pojedynczych twierdzeń do wypisania, ale milczenie czytałoby się
        # jak „recenzja przeszła".
        reason = report.get("reason") or "unknown"
        return [
            f"{soft}: niezależna kontrola AI treści CV nie potwierdziła "
            f"dokumentu ({reason}) — sprawdź CV ręcznie z oryginałem."
            if lang == "pl"
            else f"{soft}: the independent AI review did not confirm the "
            f"document ({reason}) — check it against the original by hand."
        ]

    issues.sort(key=lambda msg: 0 if msg.startswith(high) else 1)
    if len(issues) > 8:
        more = len(issues) - 8
        issues = issues[:8]
        issues.append(
            f"… i {more} kolejnych pozycji do weryfikacji"
            if lang == "pl"
            else f"… and {more} more items to verify"
        )
    return issues


def _declaration():
    declared = _REVIEW_DECLARATION.get()
    if declared is None:
        # Dopuszczalne: recenzja policzy się na kubełku generatora. Nie jest to
        # błąd — ale jeśli zdarza się na ścieżce produkcyjnej, licznik
        # `cv_factual_verification` kłamie zerem.
        logger.info(
            "[cv_final_review] brak deklaracji kubełka — metering na cv_generator"
        )
        return nullcontext()
    user_id, state = declared
    return declared_call(
        AIFeatureKey.cv_factual_verification, user_id=user_id, state=state
    )


def run_final_review(
    data: dict[str, Any],
    *,
    cv_text: str,
    screening_notes: str,
    identity: str,
    request_id: str,
    language: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Zrecenzuj gotowe CV i zwróć `(raport, ostrzeżenia)`. NIGDY nie rzuca."""

    # Ustalony PRZED wywołaniem: raport awaryjny też ma mówić, który recenzent
    # zawiódł — inaczej „unavailable" nie da się powiązać z dostawcą.
    model = model_for(AIFeatureKey.cv_factual_verification)
    try:
        with _declaration():
            report = verify_final_cv(
                data,
                cv_text=cv_text,
                screening_notes=screening_notes,
                identity=identity,
                request_id=request_id,
                model=model,
                total_timeout=final_review_timeout(),
            )
        logger.info(
            "[cv_final_review][%s] verified model=%s claims=%d",
            request_id,
            report.get("model"),
            len(report.get("claims") or []),
        )
        return report, []
    except FactualVerificationError as err:
        # Kształt jest NADZBIOREM gałęzi doradczej v10 (status/reason/paths),
        # żeby dane zapisane wcześniej dalej dawały się czytać.
        report = {
            "status": "advisory",
            "version": VERIFIER_VERSION,
            "model": model,
            "reason": err.reason,
            "paths": list(err.paths),
            "statuses": dict(err.statuses),
        }
        logger.info(
            "[cv_final_review][%s] advisory reason=%s field_count=%d",
            request_id,
            err.reason,
            len(err.paths),
        )
        return report, review_warnings(report, data, language)
    except CVGeneratorAIError as err:
        report = {
            "status": "unavailable",
            "version": VERIFIER_VERSION,
            "model": model,
            "reason": type(err).__name__,
        }
        logger.warning(
            "[cv_final_review][%s] unavailable reason=%s",
            request_id,
            type(err).__name__,
        )
        return report, review_warnings(report, data, language)
    except Exception:
        # Ostatnia linia obrony kontraktu „nigdy nie rzuca": defekt recenzenta
        # nie może zabrać dokumentu, za który już zapłacono.
        report = {
            "status": "unavailable",
            "version": VERIFIER_VERSION,
            "model": model,
            "reason": "internal_error",
        }
        logger.exception("[cv_final_review][%s] internal error", request_id)
        return report, review_warnings(report, data, language)


def summarize_review(report: Any) -> dict[str, Any] | None:
    """Kompaktowe podsumowanie dla listy CV — bez ścieżek i bez cytatów."""

    if not isinstance(report, dict):
        return None
    status = report.get("status")
    if status not in {"verified", "advisory", "unavailable"}:
        return None
    return {
        "status": status,
        "findings": len(report.get("paths") or []),
        "model": report.get("model"),
        "reason": report.get("reason"),
    }
