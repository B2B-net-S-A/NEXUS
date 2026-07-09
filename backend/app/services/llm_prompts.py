"""Versioned LLM prompt templates (Phase D2).

Centralizes every LLM-facing prompt so:
  - Revisions are trivially diffable in git
  - A/B testing can flip a single `version` field
  - The same template is reused across services (recommendations, screenings,
    CV parser, interview prep)

Design
------
Each template is a frozen dataclass with:
  - `name`              stable identifier (used in logs)
  - `version`           monotonically increasing int; bump when the prompt
                        changes semantically
  - `system_prompt`     optional preamble for chat-style models
  - `template`          f-string-shaped body with named `{placeholders}`
  - `expected_format`   short hint for the caller (JSON schema, plaintext…)

Call `PromptTemplate.render(**kwargs)` to produce the final string. Missing
placeholders raise a KeyError — caller bugs surface loudly instead of sending
corrupt prompts to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: int
    template: str
    system_prompt: Optional[str] = None
    expected_format: str = "plaintext"

    def render(self, **kwargs) -> str:  # noqa: ANN003
        """Return the final prompt string, substituting {placeholders}."""
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise KeyError(
                f"Prompt {self.name!r} v{self.version} missing placeholder: {e.args[0]!r}"
            ) from e


# ── Job criteria extraction (was inline in recommendations.py) ──────────────

JOB_CRITERIA_FROM_DESCRIPTION = PromptTemplate(
    name="job_criteria_from_description",
    version=1,
    expected_format="json",
    system_prompt=(
        "You are a technical recruiter for a Polish IT staffing agency. "
        "Extract structured requirements from job descriptions."
    ),
    template=(
        "Based on the job title and description below, output a JSON object with two lists:\n"
        '  "must_skills": hard requirements mentioned explicitly (up to 8)\n'
        '  "nice_skills": preferred but optional skills (up to 6)\n\n'
        'Each item is an object {{"name": "<skill>", "level": null}}. '
        "Respond with ONLY the raw JSON, no prose.\n\n"
        "Title: {title}\n"
        "Description: {description}\n"
        "Requirements: {requirements}\n"
    ),
)


# ── CV enrichment (Phase D3) ────────────────────────────────────────────────

CV_ENRICHMENT = PromptTemplate(
    name="cv_enrichment",
    version=4,
    expected_format="json",
    system_prompt=(
        "You are a recruitment assistant. Extract structured facts from CVs "
        "for a Polish IT staffing ATS. Use canonical technology names "
        "(e.g. 'React' not 'ReactJS', 'Kubernetes' not 'K8s'). Never invent "
        "information that is not in the CV — when unsure, return null and "
        "lower the confidence for that field."
    ),
    template=(
        "From the CV below, produce a JSON object with these fields:\n"
        '  "first_name": candidate\'s first name as it appears in the CV, or null\n'
        '  "last_name": candidate\'s last name (surname) as it appears in the CV, or null\n'
        '  "email": candidate\'s contact email (primary), exactly as written, lowercase, or null\n'
        '  "phone": candidate\'s contact phone number in international format when possible '
        '(e.g. "+48 600 123 456"); keep raw digits/spaces/dashes otherwise. null if none.\n'
        '  "city": candidate\'s city of residence (e.g. "Warszawa", "Kraków") or null. '
        "Do NOT guess from employer address — use only if the CV explicitly states the candidate's location.\n"
        '  "years_it_experience": integer, best estimate of total IT experience\n'
        '  "current_position": short string (e.g. "Senior Python Developer") or null\n'
        '  "skills": list of {{"name": "<canonical>", "level": "expert|senior|mid|junior", "years": int|null}}\n'
        '  "education": list of {{"degree": str, "field": str|null, "school": str, "year": int|null}}\n'
        '  "languages": list of {{"name": "<language>", "level": "A1|A2|B1|B2|C1|C2|native"}}\n'
        '  "companies": list of strings — past employers in chronological order, '
        "most recent first, unique (max 15). Use official company names as they appear in the CV.\n"
        '  "linkedin_url": the candidate\'s LinkedIn profile URL exactly as it '
        "appears in the CV (e.g. 'linkedin.com/in/jane-doe' or 'https://www.linkedin.com/in/jane-doe'), "
        "or null if no LinkedIn URL is present.\n"
        '  "career_summary": short Polish paragraph (3-4 zdania) describing the candidate\'s '
        "trajectory: years in IT, main stack, seniority progression and industries. "
        "Do not add knowledge that is not in the CV. Null if the CV is too short to summarize.\n"
        '  "_confidence": object mapping each field name above to a float 0.0–1.0 '
        "representing how certain you are. Use 0.95+ when the value is explicit and unambiguous; "
        "0.60–0.85 when inferred from context (e.g. full name from an email signature); "
        "0.0–0.4 when guessing or missing. Include keys for ALL top-level fields you filled in.\n\n"
        "Respond with ONLY the raw JSON, no prose.\n\n"
        "CV:\n{cv_text}\n"
    ),
)


# ── Interview prep kit (already in prep_kit.py; here for version tracking) ──

INTERVIEW_PREP = PromptTemplate(
    name="interview_prep",
    version=1,
    expected_format="json",
    system_prompt=(
        "You are a senior technical recruiter preparing a client interview. "
        "Produce concise, actionable talking points in Polish."
    ),
    template=(
        "Candidate facts:\n{candidate_summary}\n\n"
        "Job facts:\n{job_summary}\n\n"
        "Produce a JSON object with:\n"
        '  "strengths": list of <= 5 strings — what to highlight\n'
        '  "risks": list of <= 5 strings — gaps or concerns\n'
        '  "questions": list of <= 8 strings — recruiter questions to ask\n\n'
        "Respond with ONLY the raw JSON, no prose."
    ),
)


# ── Champion Profile AI Intake (Phase 14) ───────────────────────────────────

CHAMPION_PROFILE_FROM_JD = PromptTemplate(
    name="champion_profile_from_jd",
    version=1,
    expected_format="json",
    system_prompt=(
        "Jesteś senior rekruterem IT w polskiej agencji staffing. "
        "Twoim zadaniem jest ekstrahowanie ustrukturyzowanego Profilu Championa "
        "z opisu stanowiska dostarczonego przez klienta. "
        "NAJWAŻNIEJSZE REGUŁY: "
        "(1) Jeśli informacji NIE MA w źródle — pozostaw pole puste "
        '(null / "" / []) i ustaw confidence=0 dla tej sekcji. '
        "(2) Nigdy nie wymyślaj ani nie zgaduj danych. "
        "(3) Odpowiedź MUSI być czystym JSON bez prose, bez code fences."
    ),
    template=(
        "Kontekst oferty:\n"
        "  Tytuł stanowiska: {job_title}\n"
        "  Klient: {client_name}\n\n"
        "Opis od klienta:\n"
        "---\n"
        "{raw_description}\n"
        "---\n\n"
        "Wygeneruj JSON zgodny z poniższą strukturą (wszystkie pola wymagane, "
        "ale mogą być puste):\n"
        "{{\n"
        '  "basics": {{\n'
        '    "onsite_days_per_week": int|null,\n'
        '    "candidate_location_pref": str|null,\n'
        '    "language": str|null\n'
        "  }},\n"
        '  "project_context": {{\n'
        '    "about": "cel projektu, zespół, harmonogram (po polsku)",\n'
        '    "responsibilities": "obowiązki stanowiska (po polsku)",\n'
        '    "selling_points": "co przekona kandydata (po polsku)"\n'
        "  }},\n"
        '  "screening_questions": [\n'
        '    {{"id": "q1", "question": "...", "ideal_answer": "...", "deal_breaker": ""}}\n'
        "  ],\n"
        '  "historical_client_questions": "",\n'
        '  "internal_consultant_insight": "",\n'
        '  "sourcing": {{\n'
        '    "sources": ["internal_base"|"linkedin"|"ad"|"referrals"|"other"],\n'
        '    "keywords": "słowa kluczowe do search",\n'
        '    "target_companies": "firmy skąd warto sourcować",\n'
        '    "notes": ""\n'
        "  }},\n"
        '  "_confidence": {{\n'
        '    "basics": 0.0,\n'
        '    "project_context": 0.0,\n'
        '    "screening_questions": 0.0,\n'
        '    "historical_client_questions": 0.0,\n'
        '    "internal_consultant_insight": 0.0,\n'
        '    "sourcing": 0.0\n'
        "  }}\n"
        "}}\n\n"
        "Limity: screening_questions max 8 pozycji, każda z krótkim ideal_answer; "
        "deal_breaker wypełnij TYLKO gdy klient wyraźnie wskazał dyskwalifikator. "
        "W polu sourcing.sources zaznacz TYLKO kanały EXPLICIT sugerowane w opisie — "
        "jeśli brak wzmianki, zostaw []. "
        "Confidence: 0.0 gdy sekcja pusta, 0.3–0.6 gdy wywnioskowane, "
        "0.8–1.0 gdy explicit w opisie."
    ),
)


CHAMPION_PROFILE_ENRICH_FROM_MEETING = PromptTemplate(
    name="champion_profile_enrich_from_meeting",
    version=1,
    expected_format="json",
    system_prompt=(
        "Jesteś senior rekruterem IT. Analizujesz transkrypt rozmowy "
        "Delivery Lead z Hiring Managerem (u klienta) lub wewnętrznym "
        "konsultantem technicznym. Twoim zadaniem jest wyłącznie "
        "UZUPEŁNIENIE istniejącego Profilu Championa — NIE duplikuj informacji "
        "które już są zapisane. Proponuj zmiany TYLKO dla faktów EXPLICIT "
        "wspomnianych w transkrypcie. Odpowiedź MUSI być czystym JSON."
    ),
    template=(
        "Obecny Profil Championa (JSON):\n"
        "---\n"
        "{current_profile_json}\n"
        "---\n\n"
        "Kontekst oferty:\n"
        "  Tytuł: {job_title}\n"
        "  Klient: {client_name}\n\n"
        "Spotkanie — tytuł: {meeting_title}\n"
        "Spotkanie — podsumowanie:\n"
        "{meeting_summary}\n\n"
        "Spotkanie — fragmenty transkryptu:\n"
        "---\n"
        "{meeting_transcript}\n"
        "---\n\n"
        "Zwróć delta-patch JSON — tylko sekcje do aktualizacji:\n"
        "{{\n"
        '  "basics": {{ "value": {{...}}|null, "confidence": 0..1, "rationale": "cytat" }},\n'
        '  "project_context": {{ "value": {{...}}|null, "confidence": 0..1, "rationale": "cytat" }},\n'
        '  "screening_questions": {{ "value": [{{...}}]|null, "confidence": 0..1, "rationale": "..." }},\n'
        '  "historical_client_questions": {{ "value": "..."|null, "confidence": 0..1, "rationale": "..." }},\n'
        '  "internal_consultant_insight": {{ "value": "..."|null, "confidence": 0..1, "rationale": "..." }},\n'
        '  "sourcing": {{ "value": {{...}}|null, "confidence": 0..1, "rationale": "..." }}\n'
        "}}\n\n"
        "Dla sekcji których NIE chcesz aktualizować — pomiń całkowicie. "
        "rationale = krótki cytat/fragment z transkryptu uzasadniający zmianę "
        "(1-2 zdania, po polsku). "
        "Dla screening_questions.value dodawaj TYLKO nowe pytania których brak "
        "w obecnym profilu — nie powielaj."
    ),
)


CHAMPION_PROFILE_ENRICH_FROM_CALL = PromptTemplate(
    name="champion_profile_enrich_from_call",
    version=1,
    expected_format="json",
    system_prompt=(
        "Jesteś senior rekruterem IT. Analizujesz krótki transkrypt rozmowy "
        "telefonicznej Delivery Lead (CloudTalk). Kontekst może być "
        "fragmentaryczny — wyciągaj tylko to co explicit wspomniane. "
        "NIE uzupełniaj braków zgadywaniem. "
        "Odpowiedź MUSI być czystym JSON bez prose, bez code fences."
    ),
    template=(
        "Obecny Profil Championa (JSON):\n"
        "---\n"
        "{current_profile_json}\n"
        "---\n\n"
        "Kontekst oferty:\n"
        "  Tytuł: {job_title}\n"
        "  Klient: {client_name}\n\n"
        "Rozmowa telefoniczna — uczestnicy: {call_participants}\n"
        "Rozmowa telefoniczna — podsumowanie:\n"
        "{call_summary}\n\n"
        "Rozmowa telefoniczna — transkrypt:\n"
        "---\n"
        "{call_transcript}\n"
        "---\n\n"
        "Zwróć delta-patch JSON z TYLKO sekcjami do aktualizacji "
        "(format identyczny jak dla meeting enrichment). "
        "Ze względu na krótki format rozmowy ogranicz confidence do max 0.8. "
        "Dla sekcji których NIE chcesz aktualizować — pomiń całkowicie."
    ),
)


CHAMPION_PROFILE_FROM_HISTORICAL_JOBS = PromptTemplate(
    name="champion_profile_from_historical_jobs",
    version=1,
    expected_format="json",
    system_prompt=(
        "Jesteś senior rekruterem IT w polskiej agencji staffing. "
        "Otrzymujesz listę PODOBNYCH historycznych ról (zamkniętych) z już "
        "wypełnionymi Profilami Championa — Twoim zadaniem jest WYKORZYSTAĆ "
        "tę historię, aby wygenerować DRAFT profilu dla nowej roli. "
        "NAJWAŻNIEJSZE REGUŁY: "
        "(1) PREFERUJ DOSŁOWNE KOPIOWANIE (verbatim) tekstu z najbliższego "
        "matcha dla pól narracyjnych (project_context.about, selling_points, "
        "responsibilities). Nie przepisuj — Delivery Lead musi rozpoznać "
        "źródło. W `rationale` ZAWSZE wpisz: 'skopiowano z Job #<id> "
        "(<klient> — <tytuł>, podobieństwo <score>)'. "
        "(2) Dla `sourcing.keywords` i `sourcing.target_companies` zrób UNION "
        "wartości z top-K matches + deduplikację. "
        "(3) Dla `screening_questions` wybierz 3-5 pytań które pojawiają się "
        "najczęściej (dosłownie lub bardzo podobnie) w historycznych rolach. "
        "W `rationale` wpisz 'użyte w X/Y podobnych rolach'. "
        "(4) Dla sekcji dla której historia nie daje jednoznacznego sygnału — "
        "POMIŃ całkowicie (nie umieszczaj w output). NIE HALUCYNUJ. "
        "(5) Skill frequency podany osobno (consistent_must / consistent_nice) "
        "— używaj go do walidacji: jeśli jakiś skill pojawia się <60%, "
        "nie wspominaj go w skopiowanym tekście. "
        "(6) Odpowiedź MUSI być czystym JSON bez prose, bez code fences."
    ),
    template=(
        "Kontekst nowej roli:\n"
        "  Tytuł stanowiska: {job_title}\n"
        "  Klient: {client_name}\n"
        "  Train/program (opcjonalne): {train_name}\n"
        "  Opis od klienta (opcjonalnie):\n"
        "---\n"
        "{raw_description}\n"
        "---\n\n"
        "Top-K podobnych zamkniętych ról (z populated champion_profile):\n"
        "---\n"
        "{historical_profiles_json}\n"
        "---\n\n"
        "Frequency analysis skilli (across top-K):\n"
        "---\n"
        "{skill_frequency_json}\n"
        "---\n\n"
        "Zwróć delta-patch JSON — TYLKO sekcje dla których historia daje "
        "jednoznaczny sygnał. Format identyczny jak dla enrichment:\n"
        "{{\n"
        '  "basics": {{ "value": {{...}}, "confidence": 0..1, "rationale": "..." }},\n'
        '  "project_context": {{ "value": {{...}}, "confidence": 0..1, "rationale": "skopiowano z Job #..." }},\n'
        '  "screening_questions": {{ "value": [{{...}}], "confidence": 0..1, "rationale": "użyte w X/Y podobnych rolach" }},\n'
        '  "historical_client_questions": {{ "value": "...", "confidence": 0..1, "rationale": "..." }},\n'
        '  "internal_consultant_insight": {{ "value": "...", "confidence": 0..1, "rationale": "..." }},\n'
        '  "sourcing": {{ "value": {{...}}, "confidence": 0..1, "rationale": "union top-K" }}\n'
        "}}\n\n"
        "Dla sekcji których NIE uzupełniasz — pomiń klucz całkowicie. "
        "Confidence: 0.8-1.0 dla verbatim copy z pojedynczego matcha o "
        "similarity >= 0.85; 0.5-0.8 dla kompozycji/unionu; 0.3-0.5 gdy "
        "sygnał słaby (tylko 1-2 matches). "
        "screening_questions.value: max 5 pozycji; jeśli historia nie pokrywa "
        "pytania wystarczająco często (>=60% matches) — nie dodawaj go."
    ),
)


CHAMPION_RECOMMENDED_SEARCHES = PromptTemplate(
    name="champion_recommended_searches",
    version=1,
    expected_format="json",
    system_prompt=(
        "Jesteś senior sourcerem IT w polskiej agencji staffing. "
        "Na podstawie Profilu Championa i opisu rekrutacji projektujesz "
        "konkretne wyszukiwania w wewnętrznej bazie kandydatów (ATS). "
        "REGUŁY: "
        "(1) Używaj WYŁĄCZNIE pól z podanego schematu — żadnych innych filtrów. "
        "(2) Skille pisz kanonicznie (np. 'Java', 'Spring Boot', 'AWS', "
        "'PostgreSQL') — pojedyncze technologie, nie zdania. "
        "(3) q_all/q_any_groups/q_none to frazy full-text po CV (mogą być "
        "wielowyrazowe, np. 'system bankowy'). "
        "(4) Strategie mają się RÓŻNIĆ zakresem: pierwsza precyzyjna "
        "(must-have), druga szersza (synonimy/alternatywy technologii), "
        "opcjonalna trzecia eksperymentalna (np. ludzie z firm docelowych). "
        "(5) Nie wymyślaj wymagań, których nie ma w profilu/opisie. "
        "(6) Odpowiedź MUSI być czystym JSON bez prose, bez code fences."
    ),
    template=(
        "Rekrutacja:\n"
        "  Tytuł: {job_title}\n"
        "  Klient: {client_name}\n"
        "  Wymagania (z oferty): {requirements}\n"
        "  Must-have skills (z oferty): {must_skills}\n"
        "  Nice-to-have skills (z oferty): {nice_skills}\n\n"
        "Profil Championa (zweryfikowany przez Delivery Leada):\n"
        "---\n"
        "{champion_profile_json}\n"
        "---\n\n"
        "Zaprojektuj 2-3 wyszukiwania. Zwróć JSON:\n"
        "{{\n"
        '  "searches": [\n'
        "    {{\n"
        '      "name": "krótka nazwa strategii (po polsku, max 80 znaków)",\n'
        '      "rationale": "1-2 zdania: czemu ten zestaw filtrów (po polsku)",\n'
        '      "params": {{\n'
        '        "q_all": ["fraza wymagana w CV", ...],\n'
        '        "q_any_groups": [["wariant A", "wariant B"], ...],\n'
        '        "q_none": ["fraza wykluczająca", ...],\n'
        '        "skills_must": ["Skill1", ...],\n'
        '        "skills_any": ["SkillAlt1", ...],\n'
        '        "skills_none": [],\n'
        '        "experience_years_min": int|null,\n'
        '        "experience_years_max": int|null,\n'
        '        "location_cities": ["Miasto", ...]\n'
        "      }}\n"
        "    }}\n"
        "  ]\n"
        "}}\n\n"
        "Każde pole params jest opcjonalne (pusta lista/null gdy nieużywane), "
        "ale każdy search musi mieć przynajmniej jeden niepusty filtr."
    ),
)


# ── Match scoring justification ("Dopasowanie" tab) ─────────────────────────

MATCH_JUSTIFICATION = PromptTemplate(
    name="match_justification",
    version=1,
    expected_format="json",
    system_prompt=(
        "Jesteś senior rekruterem IT w polskiej agencji staffing. Wyjaśniasz, "
        "DLACZEGO dany kandydat otrzymał konkretny wynik dopasowania (0-100) do "
        "oferty. Wynik liczbowy JUŻ policzył deterministyczny silnik — Twoim "
        "zadaniem jest UZASADNIENIE tej punktacji zrozumiałym językiem, nie jej "
        "zmiana.\n\n"
        "NAJWAŻNIEJSZE REGUŁY:\n"
        "(1) Opieraj się WYŁĄCZNIE na dostarczonych danych (CV, wymagania, "
        "rozbicie punktacji). NIGDY nie wymyślaj doświadczenia, technologii, "
        "firm, certyfikatów ani lat pracy, których nie ma w źródle.\n"
        "(2) Nie zawyżaj: jeśli czegoś brakuje lub jest niepewne — nazwij to w "
        "`watchouts`, nie udawaj że jest spełnione.\n"
        "(3) Bądź konkretny — cytuj realne fakty z CV (np. „5 lat w roli DevOps”, "
        "„AWS + Terraform”), a nie ogólniki.\n"
        "(4) Ton: rzeczowy, po polsku, bez marketingowego lania wody.\n"
        "(5) Odpowiedź MUSI być czystym JSON — bez prose przed/po, bez code "
        "fences."
    ),
    template=(
        "OFERTA\n"
        "  Stanowisko: {job_title}\n"
        "  Wymagania (must-have / nice-to-have i opis):\n"
        "  ---\n"
        "  {job_requirements}\n"
        "  ---\n"
        "  Kontekst od klienta / Profil Championa:\n"
        "  {champion_context}\n\n"
        "KANDYDAT\n"
        "  Kategoria kompetencji: {competence_category}\n"
        "  Podsumowanie AI: {candidate_summary}\n"
        "  Umiejętności (z profilu): {candidate_skills}\n"
        "  Treść CV (skrócona):\n"
        "  ---\n"
        "  {candidate_cv}\n"
        "  ---\n\n"
        "ROZBICIE PUNKTACJI (deterministyczny silnik — to jest źródło prawdy "
        "o wyniku {score}/100):\n"
        "{score_breakdown}\n\n"
        "Na tej podstawie zwróć JSON dokładnie w tej strukturze:\n"
        "{{\n"
        '  "summary": "2-4 zdania po polsku: ogólny werdykt — jak mocno kandydat '
        "pasuje i dlaczego wynik jest taki a nie inny. Wspomnij zarówno mocne "
        'strony jak i główne zastrzeżenia.",\n'
        '  "pros": ["3-6 krótkich punktów: dlaczego może być dobrym wyborem — '
        'każdy poparty konkretem z CV/wymagań"],\n'
        '  "watchouts": ["1-5 punktów: luki, ryzyka i rzeczy do potwierdzenia na '
        'screeningu. Pusta lista [] tylko gdy naprawdę brak zastrzeżeń"]\n'
        "}}"
    ),
)


# ── Registry (for logging + future A/B) ─────────────────────────────────────

ALL_TEMPLATES: dict[str, PromptTemplate] = {
    t.name: t
    for t in (
        JOB_CRITERIA_FROM_DESCRIPTION,
        CV_ENRICHMENT,
        INTERVIEW_PREP,
        CHAMPION_PROFILE_FROM_JD,
        CHAMPION_PROFILE_ENRICH_FROM_MEETING,
        CHAMPION_PROFILE_ENRICH_FROM_CALL,
        CHAMPION_PROFILE_FROM_HISTORICAL_JOBS,
        CHAMPION_RECOMMENDED_SEARCHES,
        MATCH_JUSTIFICATION,
    )
}
