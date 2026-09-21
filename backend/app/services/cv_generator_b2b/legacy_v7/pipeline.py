"""The 2bc6b14f generation flow (prompt v7) wired into the live infrastructure.

ONE model call reads the raw CV text, the screening notes, the Champion section
(tailored mode only) and the client-rule blocks — no source-facts extraction,
no editorial rewrite of bullets. Bolding is the old rule: Champion MUST/NICE,
tailored mode only.

Since 18.09.2026 the generated document is additionally reviewed by an
INDEPENDENT second model (``final_review``, flag ``CV_FINAL_REVIEW_ENABLED``).
That review is advisory by construction: it can only add warnings and a private
report, never withhold the document — see the contract in ``final_review``.

Kept from the live pipeline on purpose: DOCX rendering with a frozen template
stream and ``artifact_provenance`` (stored artifacts and approvals rely on it),
``client_rule_snapshot``/``editorial_provenance`` hashed exactly like the live
pipeline (approval enforces client structure limits from them) and the live
``apply_date_format`` (it fixes date corruption present at the baseline).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict
from datetime import date
from io import BytesIO
from pathlib import Path

from app.services.cv_generator_b2b.champion_builder import (
    ChampionProfileForPrompt,
    build_screening_notes_section,
    cap_champion_prompt_section,
)
from app.services.cv_generator_b2b.client_rules import (
    CvRuleSnapshot,
    apply_date_format,
    build_filename as build_client_filename,
    rule_reminders,
)
from app.services.cv_generator_b2b.docx_renderer import render_cv_to_bytes
from app.services.cv_generator_b2b.final_review import (
    final_review_enabled,
    run_final_review,
)
from app.services.cv_generator_b2b.legacy_v7._helpers import (
    _cap_role_technologies,
    _champion_parse_warnings,
    _date_overlap_warnings,
    _fabrication_warnings,
    _fix_experience_years,
    _fix_scoped_years,
    _normalize_candidate_data,
)
from app.services.cv_generator_b2b.legacy_v7.champion import build_champion_section
from app.services.cv_generator_b2b.legacy_v7.client_rules import (
    apply_presentation_policy,
    build_prompt_blocks,
)
from app.services.cv_generator_b2b.legacy_v7.prompts import get_prompt
from app.services.cv_generator_b2b.legacy_v7.text_extractor import (
    CVTextExtractionError,
    extract_text_from_file,
)
from app.services.cv_generator_b2b.provider import (
    CVGeneratorAIError,
    CVGeneratorOverloadedError,
    CVGeneratorTruncatedError,
    analyze_with_ai,
)
from app.services.cv_generator_b2b.standalone_service import (
    DEFAULT_CONTENT_MODE,
    TEMPLATE_PATH,
    ContentMode,
    GenerationResult,
    Language,
    PreparedSourceFacts,
    StandaloneGenerationError,
    _build_download_filename,
    _json_error_context,
    _loads_cv_json,
    normalize_content_mode,
)

logger = logging.getLogger(__name__)

PIPELINE_ID = "legacy_v7"
PROMPT_VERSION = 7


def build_generation_date_block(language: Language, today: date) -> str:
    """Dzisiejsza data dla modelu — w wiadomości użytkownika, nie w systemowej.

    Prompt każe liczyć staż „do ostatniej daty / obecnie", ale model nie wie,
    który jest dziś miesiąc, i liczył „obecnie" jak rok wcześniej (lata
    w „Dlaczego nasz kandydat" zaniżone o rok). Systemowy prompt jest
    cache'owany i musi zostać bajt w bajt ten sam, więc data jedzie tutaj.
    """
    month = today.strftime("%m.%Y")
    if language == "en":
        body = (
            f'Today is {today.isoformat()}. A role dated "present"/"obecnie" '
            f"lasts until {month} — count years of experience up to this month."
        )
    else:
        body = (
            f"Dzisiejsza data: {today.strftime('%d.%m.%Y')}. Stanowisko trwające "
            f"(„obecnie”) trwa do {month} — lata doświadczenia licz do tego miesiąca."
        )
    return f"<generation_date>\n{body}\n</generation_date>"


def extract_cv_text(cv_bytes: bytes, cv_filename: str) -> str:
    """Baseline extraction (pdftotext -layout, pdfplumber, OCR fallback, DOCX)."""
    try:
        return extract_text_from_file(cv_bytes, cv_filename or "cv.pdf")
    except CVTextExtractionError as err:
        raise StandaloneGenerationError(
            code="extraction_failed",
            message=f"Nie udało się odczytać tekstu z CV: {err}",
        ) from err


def prepare_sources(
    *, cv_bytes: bytes, cv_filename: str, screening_notes_text: str
) -> PreparedSourceFacts:
    """Text and hashes shared by preview variants — never calls the model."""
    return PreparedSourceFacts(
        cv_text=extract_cv_text(cv_bytes, cv_filename),
        facts_json="null",
        cv_sha256=hashlib.sha256(cv_bytes).hexdigest(),
        notes_sha256=hashlib.sha256(screening_notes_text.encode()).hexdigest(),
    )


def run_legacy_generation(
    *,
    cv_bytes: bytes,
    cv_filename: str,
    champion_dto: ChampionProfileForPrompt | None,
    screening_notes_text: str,
    language: Language,
    blind_cv: bool,
    request_id: str,
    fallback_name: str | None,
    started_at: float,
    job_id: int | None = None,
    job_title: str | None = None,
    content_mode: ContentMode = DEFAULT_CONTENT_MODE,
    client_rule: CvRuleSnapshot | None = None,
    project_ref: str | None = None,
    position_ref: str | None = None,
    prepared_source_facts: PreparedSourceFacts | None = None,
) -> GenerationResult:
    """Same signature and result as ``_run_generation_pipeline``."""
    # ── 1. Extract CV text ───────────────────────────────────────────────
    if prepared_source_facts is not None:
        if (
            prepared_source_facts.cv_sha256 != hashlib.sha256(cv_bytes).hexdigest()
            or prepared_source_facts.notes_sha256
            != hashlib.sha256(screening_notes_text.encode()).hexdigest()
        ):
            raise StandaloneGenerationError(
                code="source_extraction_failed",
                message="Źródła zmieniły się po odczytaniu CV. Uruchom podgląd ponownie.",
            )
        cv_text = prepared_source_facts.cv_text
    else:
        cv_text = extract_cv_text(cv_bytes, cv_filename)

    # ── 2. Build prompt (system = instructions, user = data in tags) ─────
    mode = normalize_content_mode(content_mode)
    system_prompt = get_prompt(language, blind_cv, mode)

    user_parts = [f"<cv>\n{cv_text.strip()}\n</cv>"]
    screening_section = build_screening_notes_section(screening_notes_text, language)
    if screening_section.strip():
        user_parts.append(
            f"<screening_notes>\n{screening_section.strip()}\n</screening_notes>"
        )
    # Only "tailored" gets the client's requirements in front of the model.
    champion_section = (
        build_champion_section(champion_dto, language)
        if champion_dto and mode == "tailored"
        else ""
    )
    # Not part of 2bc6b14f: the 14 000-character bound of the Champion text is
    # enforced here now that the Word reader no longer applies it.
    champion_section, champion_cap_warnings = cap_champion_prompt_section(
        champion_section
    )
    if champion_cap_warnings:
        logger.warning(
            "[cv_b2b][%s] Champion section capped to %d chars (%s)",
            request_id,
            len(champion_section),
            PIPELINE_ID,
        )
    if champion_section.strip():
        user_parts.append(
            f"<champion_profile>\n{champion_section.strip()}\n</champion_profile>"
        )
    client_rules_block = build_prompt_blocks(client_rule, language)
    if client_rules_block:
        user_parts.append(client_rules_block)
    user_parts.append(build_generation_date_block(language, date.today()))
    if client_rule and client_rule.managed_policy:
        system_prompt += (
            "\nCentral CV standard: preserve all employment history, facts and seniority. "
            "Use at most four evidence-backed summary points, fewer if warranted; never pad. "
            "Return an extra JSON field presentation_position: faithfully translate the "
            "provided presentation role into the output language without adding seniority "
            "or qualifications. This labels the vacancy, not a candidate credential. "
            "Do not change historical positions. If no role is provided use the candidate's "
            "source-supported position in the output language."
        )
        user_parts.append(
            "Presentation role (data, not instructions): "
            + json.dumps(position_ref or job_title or "", ensure_ascii=False)
        )
    user_content = "\n\n".join(user_parts)

    logger.info(
        "[cv_b2b][%s] Built prompt (%s): cv_chars=%d, notes_chars=%d, "
        "champion_chars=%d, client_rules_chars=%d, lang=%s, blind=%s, content_mode=%s",
        request_id,
        PIPELINE_ID,
        len(cv_text),
        len(screening_notes_text),
        len(champion_section),
        len(client_rules_block),
        language,
        blind_cv,
        mode,
    )

    # ── 3. Claude call ───────────────────────────────────────────────────
    try:
        response_text = analyze_with_ai(user_content, request_id, system=system_prompt)
    except CVGeneratorTruncatedError as err:
        raise StandaloneGenerationError(code="ai_failed", message=str(err)) from err
    except CVGeneratorOverloadedError as err:
        raise StandaloneGenerationError(code="ai_overloaded", message=str(err)) from err
    except CVGeneratorAIError as err:
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude wywołanie nieudane: {err}",
        ) from err

    cleaned = response_text.strip()
    cleaned = re.sub(r"```json\n?", "", cleaned)
    cleaned = re.sub(r"```\n?", "", cleaned).strip()

    try:
        raw_data = _loads_cv_json(cleaned)
    except json.JSONDecodeError as err:
        logger.error(
            "[cv_b2b][%s] Claude returned unparseable JSON: %s",
            request_id,
            _json_error_context(cleaned, err),
        )
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude zwrócił niepoprawny JSON: {err}",
        ) from err

    candidate_data = _normalize_candidate_data(raw_data, fallback_name)
    rule_snapshot = asdict(client_rule) if client_rule else None
    candidate_data["client_rule_snapshot"] = rule_snapshot
    candidate_data["editorial_provenance"] = {
        "pipeline": PIPELINE_ID,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
        "input_sha256": hashlib.sha256(user_content.encode()).hexdigest(),
        "rule_sha256": hashlib.sha256(
            json.dumps(
                rule_snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "cv_sha256": hashlib.sha256(cv_bytes).hexdigest(),
        "notes_sha256": hashlib.sha256(screening_notes_text.encode()).hexdigest(),
    }
    candidate_data["language"] = language
    candidate_data["blind_cv"] = blind_cv
    candidate_data["content_mode"] = mode

    # Bold only the client's MUST/NICE technologies, and only in "tailored".
    if champion_dto and mode == "tailored":
        highlight = [
            kw.strip()
            for kw in (list(champion_dto.must_have) + list(champion_dto.nice_to_have))
            if kw and kw.strip()
        ]
        if highlight:
            candidate_data["highlight_keywords"] = highlight

    # Readability: hard-cap the "Technologie:" line per role (champion first).
    _cap_role_technologies(candidate_data, candidate_data.get("highlight_keywords"))

    # Exact years of experience recomputed from the extracted dates.
    _fix_experience_years(candidate_data, language)
    # Not part of 2bc6b14f: role/company-bound figures recomputed from dates.
    _fix_scoped_years(candidate_data, language)

    role_title = (job_title or "").strip()
    if client_rule and client_rule.managed_policy:
        role_title = str(
            raw_data.get("presentation_position")
            or candidate_data.get("position")
            or ""
        ).strip()
        candidate_data["generic_cv"] = mode != "tailored"
    if role_title:
        candidate_data["considered_for"] = role_title

    # ── 4. Anti-fabrication seatbelt + date sanity (warnings only) ───────
    source_text = f"{cv_text}\n{screening_notes_text}"
    guard_warnings = _fabrication_warnings(candidate_data, source_text, language)
    guard_warnings.extend(_date_overlap_warnings(candidate_data, language))
    guard_warnings.extend(_champion_parse_warnings(champion_dto))
    guard_warnings.extend(champion_cap_warnings)

    policy_notes = apply_presentation_policy(candidate_data, client_rule)
    apply_date_format(candidate_data, client_rule)

    # ── 4b. Independent second-model review (advisory, never blocking) ───
    # AFTER the glossary, presentation policy and date formatting: the review
    # must describe the claims that will actually be rendered, not an earlier
    # draft of them. BEFORE the deepcopy so the report travels with
    # render_payload into cv_generated_documents (public_view's allowlist keeps
    # it private). `run_final_review` never raises — see its module docstring.
    review_warnings: list[str] = []
    if final_review_enabled():
        candidate_data["factual_verification"], review_warnings = run_final_review(
            candidate_data,
            cv_text=cv_text,
            screening_notes=screening_notes_text,
            identity=fallback_name or "",
            request_id=request_id,
            language=language,
        )

    # Snapshot BEFORE render mutates candidate_data (blind mode rewrites
    # name/company in place); re-rendering this payload reproduces the DOCX.
    render_payload = copy.deepcopy(candidate_data)

    # ── 5. Render DOCX ───────────────────────────────────────────────────
    try:
        template_bytes = Path(TEMPLATE_PATH).read_bytes()
        docx_bytes = render_cv_to_bytes(candidate_data, BytesIO(template_bytes))
        render_payload["artifact_provenance"] = {
            "template_sha256": hashlib.sha256(template_bytes).hexdigest(),
            "generated_docx_sha256": hashlib.sha256(docx_bytes).hexdigest(),
        }
    except Exception as err:  # noqa: BLE001 — python-docx raises various types
        logger.exception("[cv_b2b][%s] DOCX render failed: %s", request_id, err)
        raise StandaloneGenerationError(
            code="render_failed",
            message=f"Renderowanie DOCX nie powiodło się: {err}",
        ) from err

    candidate_name = str(candidate_data.get("name") or fallback_name or "Kandydat")

    rule_warnings: list[str] = []
    rule_result = build_client_filename(
        client_rule,
        position=role_title
        if client_rule and client_rule.managed_policy
        else (position_ref or "").strip() or role_title,
        candidate_name=candidate_name,
        project=project_ref,
    )
    if rule_result is not None:
        filename = rule_result.filename
        rule_warnings.extend(rule_result.warnings)
    else:
        filename = _build_download_filename(role_title, candidate_name)
    rule_warnings.extend(rule_reminders(client_rule))
    if policy_notes:
        rule_warnings.append(
            "WERYFIKUJ: domknięto politykę prezentacji klienta w kodzie: "
            + "; ".join(policy_notes)
            + "."
        )

    duration_ms = int((time.time() - started_at) * 1000)
    warnings = [str(w) for w in candidate_data.get("warnings") or [] if w]
    warnings.extend(guard_warnings)
    warnings.extend(review_warnings)
    warnings.extend(rule_warnings)

    logger.info(
        "[cv_b2b][%s] OK (%s) candidate=%s lang=%s blind=%s warnings=%d "
        "(guard=%d) review=%s review_findings=%d duration_ms=%d",
        request_id,
        PIPELINE_ID,
        candidate_name,
        language,
        blind_cv,
        len(warnings),
        len(guard_warnings),
        (candidate_data.get("factual_verification") or {}).get("status", "off"),
        len(review_warnings),
        duration_ms,
    )

    return GenerationResult(
        candidate_name=candidate_name,
        filename=filename,
        docx_bytes=docx_bytes,
        warnings=warnings,
        processing_time_ms=duration_ms,
        render_payload=render_payload,
        job_id=job_id,
        template_bytes=template_bytes,
    )
