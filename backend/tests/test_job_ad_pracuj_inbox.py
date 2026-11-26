"""Link do Pracuj.pl z maila Pracuj.pl (26.11.2026) — czyste funkcje, bez bazy."""

from __future__ import annotations

import pytest

from app.services.job_ad import pracuj_inbox
from app.services.job_ad.pracuj_inbox import Candidate, decide, title_key

_GID = "00000000-0000-4000-8000-000000000001"


def test_the_group_id_comes_from_the_offer_link_in_the_mail():
    html = (
        '<a href="https://www.pracuj.pl/praca?groupId=' + _GID.upper() + '">'
        'Zobacz ogłoszenie</a> <a href="https://www.pracuj.pl/">Pracuj.pl</a>'
    )
    assert pracuj_inbox.group_id(html) == _GID
    assert (
        pracuj_inbox.public_url(_GID) == f"https://www.pracuj.pl/praca?groupId={_GID}"
    )


@pytest.mark.parametrize(
    "html",
    [
        None,
        "",
        '<a href="https://www.pracuj.pl/">Pracuj.pl</a>',
        # Dwa różne ogłoszenia w jednym mailu — nie zgadujemy, które.
        f"groupId={_GID} groupId=00000000-0000-4000-8000-000000000002",
        # Ucięty identyfikator nie jest identyfikatorem.
        f"groupId={_GID}0",
    ],
)
def test_no_single_offer_link_means_no_link(html):
    assert pracuj_inbox.group_id(html) is None


def test_two_links_to_the_same_offer_are_one_link():
    assert pracuj_inbox.group_id(f"groupId={_GID} i groupId={_GID.upper()}") == _GID


@pytest.mark.parametrize(
    "subject,title",
    [
        ("Publikacja ogłoszenia na Tester Manualny (k/m/x)", "Tester Manualny (k/m/x)"),
        ("publikacja ogłoszenia na  Data Engineer ", "Data Engineer"),
        ("Pracuj.pl - ogłoszenie Tester kończy się za 2 dni?", None),
        ("RE: Publikacja ogłoszenia na Tester", None),
        ("Publikacja ogłoszenia na ", None),
        (None, None),
    ],
)
def test_only_the_publication_mail_has_a_title(subject, title):
    assert pracuj_inbox.mail_title(subject) == title


@pytest.mark.parametrize(
    "portal,nexus",
    [
        # Pary z danych 26.11.2026: tytuł na portalu i w NEXUSIE.
        ("Tester Manualny (k/m/x)", "Tester Manualny x4"),
        (
            "Kierownik / Kierowniczka projektu (k/m/x)",
            "Kierownik/Kierowniczka projektu",
        ),
        ("Senior IT Project Manager (K/M/N)", "Senior IT Project Manager"),
        ("Konsultant SAP FI/TR (f/m/x)", "konsultant sap fi / tr"),
        (
            "Release Manager – Cloud Migration (m/k)",
            "Release Manager - Cloud Migration",
        ),
    ],
)
def test_the_same_ad_has_the_same_title_key(portal, nexus):
    assert title_key(portal) == title_key(nexus)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Tester", "Tester Automatyczny"),
        ("Java Developer (Spring)", "Java Developer"),
        ("Tester x4", "Tester 4"),
    ],
)
def test_different_ads_keep_different_title_keys(a, b):
    assert title_key(a) != title_key(b)


def test_one_request_with_the_same_title_links_by_itself():
    match = decide(
        "Tester Manualny (k/m/x)",
        [
            Candidate(1, ("Tester Manualny x4",)),
            Candidate(2, ("Tester Automatyczny",)),
            Candidate(3, ("Tester",)),
        ],
    )
    assert match.auto == 1
    assert match.suggested == ()


def test_the_ad_title_counts_like_the_recruitment_title():
    match = decide(
        "Data Engineer (k/m/x)",
        [Candidate(7, ("PL - DE TP#1 (43151)", "Data Engineer"))],
    )
    assert match.auto == 7


def test_two_recruitments_with_the_same_title_are_asked_about():
    match = decide(
        "Tester (k/m/x)", [Candidate(1, ("Tester",)), Candidate(2, ("Tester",))]
    )
    assert match.auto is None
    assert match.suggested == (1, 2)


def test_the_only_request_with_a_similar_title_is_asked_about():
    match = decide(
        "Starszy Analityk Danych (k/m/x)", [Candidate(5, ("Analityk Danych",))]
    )
    assert match.auto is None
    assert match.suggested == (5,)


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        # Jedyna prośba, ale o zupełnie inne stanowisko.
        [Candidate(5, ("Kierownik projektu",))],
        # Kilka próśb, żadna z tym tytułem — nie zgadujemy.
        [Candidate(5, ("Analityk Danych",)), Candidate(6, ("Analityk Biznesowy",))],
    ],
)
def test_without_a_fitting_request_nothing_happens(candidates):
    match = decide("Starszy Analityk Danych (k/m/x)", candidates)
    assert match.auto is None
    assert match.suggested == ()
