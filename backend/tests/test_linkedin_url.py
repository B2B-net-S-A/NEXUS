"""Kanoniczny adres profilu LinkedIn (`app.services.linkedin_url`)."""

from app.services.linkedin_url import normalize_linkedin_url


def test_normalize_linkedin_url_strips_query_and_trailing_slash() -> None:
    variants = [
        "https://linkedin.com/in/jane-doe",
        "https://www.linkedin.com/in/jane-doe/",
        "https://pl.linkedin.com/in/jane-doe/?trk=foo",
        "linkedin.com/in/jane-doe",
        "LINKEDIN.COM/in/jane-doe",
    ]
    for v in variants:
        assert normalize_linkedin_url(v) == "https://linkedin.com/in/jane-doe"


def test_normalize_linkedin_url_rejects_non_profile_paths() -> None:
    bad = [
        "https://linkedin.com/company/acme",
        "https://linkedin.com/jobs/view/42",
        "https://google.com/in/nope",
        "",
        None,
        "garbage text",
    ]
    for v in bad:
        assert normalize_linkedin_url(v) is None
