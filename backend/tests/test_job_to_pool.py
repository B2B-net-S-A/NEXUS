"""Tests for the deterministic Job/Candidate → Talent-Pool classifier.

Locks the title→pool expectation across a sample of real production
``cv_sent`` job titles, the candidate-skill fallback for ambiguous variants,
the precision-first skips, and the catalogue-name integrity contract (every
name a rule can emit must exist in the live pool catalogue).

Service module: app.services.job_to_pool
"""

from __future__ import annotations

from app.services.job_to_pool import (
    _RULES,
    _SKIP,
    classify_role_to_pool_name,
)

# The 101 imported Traffit role pools + the 5 manual ones present on prod.
# A rule must never emit a name outside this set, or the resolver's
# case-insensitive lookup would silently find nothing and skip the candidate.
CATALOGUE: frozenset[str] = frozenset(
    {
        # data & ai
        "AI Engineer", "BIG DATA (Hadoop)", "Data Architect", "Data Engineer",
        "Data Scientist", "ML Infrastructure Engineer", "MLOps Engineer",
        # infrastructure & operations
        "Cloud Architect", "Cloud Engineer", "DevOps Engineer - Azure",
        "DevOps Engineer AWS", "Helpdesk L1", "Helpdesk L2", "Helpdesk L3",
        "Infrastructure Engineer", "Linux Admin", "MS DBA", "Mainframe",
        "NOC Engineer", "Network Administrator", "Network Architect",
        "Network Engineer", "Oracle DBA", "Platform Engineer",
        "SRE/DevOps (bez chmury)", "Service Desk", "Virtualization Engineer",
        "Windows Admin",
        # management & delivery
        "Business Analyst - Financial Crime / AML", "Business Analyst - General",
        "Business Analyst - Mortgage / Credit", "Business Analyst - Payments",
        "Business Analyst - Regulatory / Compliance", "Change Manager",
        "Compliance Specialist", "DORA Specialist", "IT Analyst - Business Focus",
        "IT Analyst - Data Focus", "IT Analyst - Systems / Integration Focus",
        "IT Project Manager", "Lead IT Analyst", "Migration Manager", "PM", "PMO",
        "Product Owner", "Program Manager", "Project Assistant",
        "RTE - Release Train Engineer", "Risk / GRC Manager",
        "Rollout / Release Manager", "Scrum Master / Agile Coach",
        "Service Manager", "Transition Manager",
        # security & quality
        "IAM Engineer, Vulnerability Management",
        "Manual Tester (web, mob, sys (bankowość)", "Manual Tester - bazy danych",
        "Pentester (blue+red)",
        "Performance Tester (jMeter, Loadrunner, Gatling)", "SOC",
        "Security Engineer", "Test Architect", "Test Lead", "Test Manager",
        "Tester Automatyzujący (C#, Selenium)",
        "Tester Automatyzujący (Cypress, JavaScript)",
        "Tester Automatyzujący (ETL, bazy danych)",
        "Tester Automatyzujący (Java, Selenium)",
        "Tester Automatyzujący (Playwright, TypeScript)",
        "Tester Automatyzujący (Python, PyTest)",
        "Tester Automatyzujący (Python, Robot Framework)", "Tester embedded",
        # software development
        ".NET (C#)", "ABAP DEV", "Android", "Angular", "C/C++", "COBOL", "ERP",
        "Enterprise Architect", "FullStack .NET", "FullStack JS", "FullStack Java",
        "GO", "Java", "Low Code", "Node.Js", "PEGA", "PHP",
        "Powerapps (Power Platform, Dynamics)", "Python", "RPA", "React",
        "SAP Consultant", "System Architect", "UX/UI", "Vue.js", "iOS",
        # cc-null buckets
        "Architekci", "Data Engineers", "POWER CALLING",
        "Subject Matter Expert (SME)",
    }
)


def test_every_emittable_pool_name_exists_in_catalogue() -> None:
    """Catalogue-name integrity: no rule may emit a name absent from the
    live catalogue (case-insensitive lookup would otherwise silently skip)."""
    emittable = {name for name, _ in _RULES if name != _SKIP}
    catalogue_lower = {n.lower() for n in CATALOGUE}
    orphans = sorted(n for n in emittable if n.lower() not in catalogue_lower)
    assert orphans == [], f"rules emit names not in the catalogue: {orphans}"


# (title, skill_text, expected_pool) — sampled from the real cv_sent corpus.
TITLE_CASES: tuple[tuple[str, str | None, str | None], ...] = (
    # ── Software development — language tokens win, CC tag irrelevant ──────
    ("Java Developer", None, "Java"),
    ("Senior JAVA Developer, OBH project (30322)", None, "Java"),  # job CC was mgmt
    ("PKO BP Programista Java Senior ZOB-2343", None, "Java"),
    ("PL - 3 x Full Stack/ Java developers - TP 7843 (31201)", None, "FullStack Java"),
    ("PKO BP: Programista NET Senior ZOB-2147", None, ".NET (C#)"),  # dotless NET
    ("PKO BP: PROGRAMISTA .NET / ZOB-1814", None, ".NET (C#)"),
    ("PKO BP Programista Python ZOB-2329", None, "Python"),
    # Plain "JavaScript" names no specific JS pool (React/Angular/Vue/Node) →
    # precision skip rather than guessing.
    ("Programista Javascript PKO BP ZOB-1933", None, None),
    ("Regular Angular Developer - Corporate Netbank (31073)", None, "Angular"),
    ("Bank Pocztowy: Programista PowerApps", None, "Powerapps (Power Platform, Dynamics)"),
    # ── QA / security ──────────────────────────────────────────────────────
    (
        "Manual Tester for SD Consumer Finance & Technology (41370)",
        None,
        "Manual Tester (web, mob, sys (bankowość)",
    ),
    ("IT Tester for NCS - TP 1338 (29995)", None, "Manual Tester (web, mob, sys (bankowość)"),
    ("E2E Test Lead / Lead Tester for CT QA (40168)", None, "Test Lead"),
    ("Test Manager - TP 5254 (30299)", None, "Test Manager"),
    ("ON HOLD_Rozwój Departamentu Bezpieczeństwa - Pentesterzy", None, "Pentester (blue+red)"),
    ("Cybersecurity", None, "Security Engineer"),
    ("Senior Security Firewall Architect Zero Trust Initative (28228)", None, "Security Engineer"),
    # ── Infrastructure ─────────────────────────────────────────────────────
    ("DevOps Cloud", None, "SRE/DevOps (bez chmury)"),
    ("Senior DevOps Engineer - Azure - Data Hub (42077)", None, "DevOps Engineer - Azure"),
    ("Linux expert developer (41431)", None, "Linux Admin"),
    ("User Support Specialist", None, "Service Desk"),
    # ── Management & delivery ──────────────────────────────────────────────
    ("Analityk Systemowy", None, "IT Analyst - Systems / Integration Focus"),
    ("Business Analyst-PEP4304 (30394)", None, "Business Analyst - General"),
    ("Kierownik Projektu IT/Scrum Master", None, "Scrum Master / Agile Coach"),
    ("Nordea: Change Manager, CA Software Exit Programme (41659)", None, "Change Manager"),
    ("PL - Release Manager - XBAS (37907)", None, "Rollout / Release Manager"),
    ("PMO Specialist for Information Security Risk Reduction (40764)", None, "PMO"),
    ("Project Manager (projekt tradingowy)", None, "IT Project Manager"),
    # ── Data & AI ──────────────────────────────────────────────────────────
    ("Data Scientist", None, "Data Scientist"),
    ("KYC Big Data Developer to Backend Application team (33798)", None, "BIG DATA (Hadoop)"),
    # ── Ambiguous title alone → None (precision); skills recover the variant ─
    ("Front-end Developer", None, None),
    ("Front-end Developer", "React, Redux, TypeScript", "React"),
    ("4 x Senior BackEnd Developer in Corporate Area (42072)", None, None),
    ("Developer Fullstack 171957", None, None),
    ("Software Developer RITM03554491", None, None),
    ("Software Developer RITM0355", "Spring Boot, Java, Hibernate", "Java"),
    ("Test automation engineer - TP 6564 (30559)", None, None),
    ("Test automation engineer", "Cypress, JavaScript, Playwright", "Tester Automatyzujący (Cypress, JavaScript)"),
    ("QA Test Engineer Senior (automation) (36061)", None, None),
    ("QA Test Engineer Senior (automation)", "Selenium, Java, TestNG", "Tester Automatyzujący (Java, Selenium)"),
    # ── Non-role buckets → None ────────────────────────────────────────────
    ("ITVM-3331 Usługi kontraktorów na potrzeby TRIBE Rebel", None, None),
    ("Samodzielna Księgowa Senior i Junior", None, None),
    ("Zapytanie ofertowe nr 171180", None, None),
)


def test_title_to_pool_expectations() -> None:
    failures = []
    for title, skills, expected in TITLE_CASES:
        got = classify_role_to_pool_name(title, skill_text=skills)
        if got != expected:
            failures.append(f"{title!r} (skills={skills!r}) -> {got!r}, expected {expected!r}")
    assert not failures, "title→pool mismatches:\n" + "\n".join(failures)


def test_clear_title_not_overridden_by_unrelated_skills() -> None:
    """A clear title decides the role TYPE; skills only fill an undetermined
    variant. A manual-tester job stays manual even if the candidate knows
    Selenium."""
    assert (
        classify_role_to_pool_name("Manual Tester", skill_text="Selenium, Java")
        == "Manual Tester (web, mob, sys (bankowość)"
    )
    assert classify_role_to_pool_name("Java Developer", skill_text="Python, Django") == "Java"


def test_javascript_does_not_match_java() -> None:
    assert classify_role_to_pool_name("JavaScript Developer") != "Java"


def test_blank_input_returns_none() -> None:
    assert classify_role_to_pool_name(None) is None
    assert classify_role_to_pool_name("") is None
    assert classify_role_to_pool_name("   ") is None
