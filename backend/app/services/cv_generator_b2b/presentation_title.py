"""Central CV presentation contract, shared by both generation pipelines."""


def instructions(language: str) -> str:
    """Instrukcja nagłówka CV dla polityki centralnej.

    D2 (decyzja Artura 13.10.2026): nagłówek to nazwa roli od klienta, bez
    tłumaczenia — „Data Platform Developer” nie staje się „Programistą platformy
    danych”. Rolę czyści i wpisuje kod (`job_working_title.cv_role_title`);
    model dostaje ją jako dane i przepisuje bez zmian.
    """
    target = "English (en)" if language == "en" else "Polish (pl)"
    return (
        "\nCentral CV standard: preserve all employment history, facts and seniority. "
        "Use at most four evidence-backed summary points, fewer if warranted; never pad. "
        f"The output document language is {target}. Extend the output JSON object with "
        "the REQUIRED string field presentation_position. Copy the provided presentation "
        "role into it EXACTLY as given — do not translate it, do not rephrase it, do not "
        "add or remove seniority. This field is the document heading and filename role, "
        "not an employment-history entry. Keep the source-backed candidate position and "
        "historical roles separate and unchanged. If no presentation role was provided, "
        f"use the candidate's source-supported position in {target}. Do not write General "
        "CV, CV ogólne, Considered for or equivalent labels in any document content; "
        "workflow status is displayed only in the application."
    )


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def considered_for_line(considered_for, header_position) -> str:
    """Legacy "Considered for" text, or "" when it only repeats the header.

    Payloads predating central policies carry both ``position`` and
    ``considered_for``; in production most of them hold the same vacancy, so
    the line printed the title twice. Compared case- and whitespace-blind.
    """
    text = str(considered_for or "").strip()
    if not text or _norm(text) == _norm(header_position):
        return ""
    return text
