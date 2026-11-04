"""Link aplikacyjny ogłoszenia na portalu niesie znacznik portalu (UTM).

Strona kariery zapisuje ``utm_*`` w źródle kandydata — bez znacznika
zgłoszenie z JustJoin.IT/RocketJobs nie różniłoby się od wejścia z LinkedIna.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.models.job_posting import Portal
from app.services.job_portals.service import portal_apply_url


def test_apply_url_carries_portal_utm():
    url = portal_apply_url(
        "https://kariera.dynaminds.pl/r/java-dev", Portal.rocketjobs, 42
    )
    parsed = urlparse(url)
    assert parsed.path == "/r/java-dev"
    assert parse_qs(parsed.query) == {
        "utm_source": ["rocketjobs"],
        "utm_medium": ["job_board"],
        "utm_campaign": ["nexus-job-42"],
    }


def test_each_portal_gets_its_own_source():
    base = "https://kariera.dynaminds.pl/r/java-dev"
    jjit = portal_apply_url(base, Portal.justjoinit, 1)
    rj = portal_apply_url(base, Portal.rocketjobs, 1)
    assert "utm_source=justjoinit" in jjit
    assert "utm_source=rocketjobs" in rj


def test_existing_query_is_kept():
    url = portal_apply_url("https://kariera.test/r/a?x=1", Portal.justjoinit, 7)
    assert url.startswith("https://kariera.test/r/a?x=1&utm_source=justjoinit")
