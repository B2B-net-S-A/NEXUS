"""Central CV presentation contract, shared by both generation pipelines."""


def instructions(language: str) -> str:
    target = "English (en)" if language == "en" else "Polish (pl)"
    return (
        "\nCentral CV standard: preserve all employment history, facts and seniority. "
        "Use at most four evidence-backed summary points, fewer if warranted; never pad. "
        f"The output document language is {target}. Extend the output JSON object with "
        f"the REQUIRED string field presentation_position, written in {target}. "
        "Translate the provided presentation role; do not merely copy it in its input "
        "language. For example, in English 'Programistka Python' becomes 'Python Developer'; "
        "in Polish 'Business Analyst' becomes 'Analityk biznesowy'. Preserve technology "
        "names and seniority exactly; never add qualifications. This field is the document "
        "heading and filename role, not an employment-history entry. Keep the source-backed "
        "candidate position and historical roles separate and unchanged. If no presentation "
        "role was provided, use the candidate's source-supported position in the output "
        "language. Do not write General CV, CV ogólne, Considered for or equivalent labels "
        "in any document content; workflow status is displayed only in the application."
    )
