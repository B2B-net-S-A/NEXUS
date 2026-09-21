"""Central CV presentation contract, shared by both generation pipelines."""


def instructions(language: str) -> str:
    target = "English (en)" if language == "en" else "Polish (pl)"
    examples = (
        "For example, 'Programistka Python' becomes 'Python Developer'. "
        if language == "en"
        else "Translate occupational nouns into Polish even when English IT titles are "
        "common in Poland: 'Python Developer' becomes 'Programista Python', "
        "'Business Analyst' becomes 'Analityk biznesowy', 'Data Platform Developer' "
        "becomes 'Programista platformy danych', 'QA Engineer' becomes 'Inżynier QA'. "
    )
    return (
        "\nCentral CV standard: preserve all employment history, facts and seniority. "
        "Use at most four evidence-backed summary points, fewer if warranted; never pad. "
        f"The output document language is {target}. Extend the output JSON object with "
        f"the REQUIRED string field presentation_position, written in {target}. "
        "Translate the provided presentation role; do not merely copy it in its input "
        f"language. {examples}Preserve technology "
        "names and seniority exactly; never add qualifications. This field is the document "
        "heading and filename role, not an employment-history entry. Keep the source-backed "
        "candidate position and historical roles separate and unchanged. If no presentation "
        "role was provided, use the candidate's source-supported position in the output "
        "language. Do not write General CV, CV ogólne, Considered for or equivalent labels "
        "in any document content; workflow status is displayed only in the application."
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
