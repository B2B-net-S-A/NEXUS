"""Lock the Talent-Pool name → Competence Category classifier.

The classifier is a deterministic ruleset whose ordering is load-bearing, so we
pin the expected slug for the FULL live pool catalogue (104 pools pulled from
production 2026-06-01) plus a few synthetic edge cases. If a rule change shifts
any of these, the diff makes the intent explicit and reviewable.
"""

import pytest

from app.services.talent_pool_cc import classify_pool_name_to_cc_slug

INFRA = "infrastructure_operations"
SW = "software_development"
DATA = "data_ai"
SEC = "security_quality"
MGMT = "management_delivery"

# (pool_name, expected_slug_or_None) — exact names from the prod catalogue.
LIVE_POOLS: list[tuple[str, str | None]] = [
    ("Senior Angular", SW),
    ("DevOps Engineers", INFRA),
    ("QA Automation", SEC),
    ("Java Backend Senior", SW),
    ("Targ kandydatów", None),
    ("PM", MGMT),
    ("POWER CALLING", None),
    ("Data Scientist", DATA),
    ("Data Architect", DATA),
    ("Data Engineer", DATA),
    ("AI Engineer", DATA),
    ("ML Infrastructure Engineer", DATA),
    ("MLOps Engineer", DATA),
    ("Helpdesk L3", INFRA),
    ("Helpdesk L2", INFRA),
    ("Helpdesk L1", INFRA),
    ("Service Desk", INFRA),
    ("SOC", SEC),
    ("IAM Engineer, Vulnerability Management", SEC),
    ("Security Engineer", SEC),
    ("Oracle DBA", INFRA),
    ("MS DBA", INFRA),
    ("NOC Engineer", INFRA),
    ("Network Administrator", INFRA),
    ("Network Architect", INFRA),
    ("Network Engineer", INFRA),
    ("Virtualization Engineer", INFRA),
    ("Windows Admin", INFRA),
    ("Linux Admin", INFRA),
    ("RPA", SW),
    ("SRE/DevOps (bez chmury)", INFRA),
    ("DevOps Engineer - Azure", INFRA),
    ("DevOps Engineer AWS", INFRA),
    ("Infrastructure Engineer", INFRA),
    ("Platform Engineer", INFRA),
    ("Enterprise Architect", SW),
    ("System Architect", SW),
    ("Cloud Architect", INFRA),
    ("Cloud Engineer", INFRA),
    ("SAP Consultant", SW),
    ("Compliance Specialist", MGMT),
    ("DORA Specialist", MGMT),
    ("Lead IT Analyst", MGMT),
    ("IT Analyst - Data Focus", MGMT),
    ("IT Analyst - Systems / Integration Focus", MGMT),
    ("IT Analyst - Business Focus", MGMT),
    ("Subject Matter Expert (SME)", None),
    ("Product Owner", MGMT),
    ("Business Analyst - Regulatory / Compliance", MGMT),
    ("Business Analyst - Financial Crime / AML", MGMT),
    ("Business Analyst - Payments", MGMT),
    ("Business Analyst - Mortgage / Credit", MGMT),
    ("Business Analyst - General", MGMT),
    ("Project Assistant", MGMT),
    ("PMO", MGMT),
    ("Risk / GRC Manager", MGMT),
    ("RTE - Release Train Engineer", MGMT),
    ("Scrum Master / Agile Coach", MGMT),
    ("Service Manager", MGMT),
    ("Transition Manager", MGMT),
    ("Change Manager", MGMT),
    ("Migration Manager", MGMT),
    ("Rollout / Release Manager", MGMT),
    ("Program Manager", MGMT),
    ("IT Project Manager", MGMT),
    ("Test Architect", SEC),
    ("Test Lead", SEC),
    ("Test Manager", SEC),
    ("Pentester (blue+red)", SEC),
    ("Performance Tester (jMeter, Loadrunner, Gatling)", SEC),
    ("Manual Tester - bazy danych", SEC),
    ("Manual Tester (web, mob, sys (bankowość)", SEC),
    ("Tester embedded", SEC),
    ("Tester Automatyzujący (Cypress, JavaScript)", SEC),
    ("Tester Automatyzujący (Playwright, TypeScript)", SEC),
    ("Tester Automatyzujący (C#, Selenium)", SEC),
    ("Tester Automatyzujący (Python, PyTest)", SEC),
    ("Tester Automatyzujący (ETL, bazy danych)", SEC),
    ("Tester Automatyzujący (Python, Robot Framework)", SEC),
    ("Tester Automatyzujący (Java, Selenium)", SEC),
    ("FullStack .NET", SW),
    ("FullStack JS", SW),
    ("FullStack Java", SW),
    ("Low Code", SW),
    ("PEGA", SW),
    ("COBOL", SW),
    ("GO", SW),
    ("ABAP DEV", SW),
    ("Powerapps (Power Platform, Dynamics)", SW),
    ("BIG DATA (Hadoop)", DATA),
    ("ERP", SW),
    ("Vue.js", SW),
    ("Android", SW),
    ("iOS", SW),
    ("UX/UI", SW),
    ("Angular", SW),
    ("React", SW),
    ("C/C++", SW),
    ("PHP", SW),
    ("Python", SW),
    ("Node.Js", SW),
    (".NET (C#)", SW),
    ("Java", SW),
    ("Mainframe", INFRA),
]


@pytest.mark.parametrize("name,expected", LIVE_POOLS, ids=[p[0] for p in LIVE_POOLS])
def test_classify_live_pool_catalogue(name: str, expected: str | None) -> None:
    assert classify_pool_name_to_cc_slug(name) == expected


def test_live_catalogue_has_full_coverage() -> None:
    """Of the 104 live pools only the 3 non-role buckets stay uncategorised."""
    categorised = [n for n, slug in LIVE_POOLS if slug is not None]
    uncategorised = [n for n, slug in LIVE_POOLS if slug is None]
    assert len(LIVE_POOLS) == 104
    assert len(categorised) == 101
    assert sorted(uncategorised) == [
        "POWER CALLING",
        "Subject Matter Expert (SME)",
        "Targ kandydatów",
    ]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("", None),
        ("   ", None),
        (None, None),
        # ordering: a tester whose name also mentions a data tool stays QA
        ("Tester (ETL, Spark)", SEC),
        # ordering: "Service Manager" is management, "Service Desk" is infra
        ("Service Manager", MGMT),
        ("Service Desk", INFRA),
        # generic architect → software; domain architects keep their domain
        ("Solution Architect", SW),
        ("Data Architect", DATA),
        # word-boundary guard: "ai" inside a word must not trigger data_ai
        ("Mainframe Specialist", INFRA),
        # case/whitespace insensitivity
        ("  pYtHoN  ", SW),
    ],
    ids=[
        "empty", "blank", "none", "tester-with-etl", "service-manager",
        "service-desk", "solution-architect", "data-architect",
        "mainframe-no-false-ai", "case-insensitive",
    ],
)
def test_classify_edge_cases(name: str | None, expected: str | None) -> None:
    assert classify_pool_name_to_cc_slug(name) == expected
