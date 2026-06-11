"""Lock the Job title → Competence Category classifier.

Same convention as ``test_talent_pool_cc.py``: the ruleset ordering is
load-bearing, so we pin the expected slug for a representative slice of the
production job catalogue (titles sampled from prod 2026-06-11) plus edge
cases that exercise the rule precedence (security before data, data before
management, management before infra, infra before software).
"""

import pytest

from app.services.job_cc import classify_job_title_to_cc_slug

INFRA = "infrastructure_operations"
SW = "software_development"
DATA = "data_ai"
SEC = "security_quality"
MGMT = "management_delivery"

# (job_title, expected_slug_or_None) — titles from the prod catalogue.
LIVE_TITLES: list[tuple[str, str | None]] = [
    # — Security & Quality (testers + security, checked first) —
    ("Tester Middle ZOB-2732", SEC),
    ("Tester Senior (ZOB-2741)", SEC),
    ("TESTER AUTOMATYCZNY", SEC),
    ("Tester Automatyzujący Selenium + JAVA", SEC),
    ("Tester automatyzujący C#", SEC),
    ("PKO BP Tester Manualny Junior ZOB-2380", SEC),
    ("Tester UAT (aplikacje mobilne) (ZOB-840)", SEC),
    ("Nordea: Senior Test Automation Engineer D&A Hub (41806)", SEC),
    ("QA Test Engineer Senior (manual) - Consumer Finance - Poland", SEC),
    ("PKP: Specjalista bezpieczeństwa chmury obliczeniowej x1", SEC),
    ("GISP2023/PVM/Senior IT Security Specialist (3) (30530)", SEC),
    ("ATOS:FRONTEX: Security Architect - replacement", SEC),
    ("B2B Red Team: Exploit Developer", SEC),
    ("Technical IT Security resource MFA - Windows Hello for Business", SEC),
    # Precedence: a tester touching ETL stays QA, not data.
    ("Tester Automatyzujący (ETL, bazy danych)", SEC),
    # — Data & AI —
    ("Projekt testowy: ATOS/PGE - Data Architect", DATA),
    ("ETL developer TD11410 (29334)", DATA),
    ("Senior Power BI Analyst (27140)", DATA),
    ("Hadoop 2023_091", DATA),
    ("AI Backend Developer (zespół AI)", DATA),
    ("Analityk danych", DATA),
    # — Management & Delivery —
    ("PKO BP  Analityk Biznesowy ZOB-2336", MGMT),
    ("PKO BP:  ZOB-2463 Analityk Systemowy", MGMT),
    ("Analityk biznesowo-systemowy_23_11_2023", MGMT),
    ("PKO BP Kierownik Projektów (TECHNICZNY LUB BIZNESOWY) ZOB-2326", MGMT),
    ("Nordea: Project Manager (40821)", MGMT),
    ("Nordea: Release Manager - KYC (40963)", MGMT),
    ("PL Scrum Master Nordic Payments BNS Team (36796)", MGMT),
    ("Product Owner D4A (DevOps for Applications)", MGMT),
    ("Lider Techniczny (Java) x1 Zamówienie 19", MGMT),
    ("Specjalista PMO_moduł VI", MGMT),
    ("PL Technical Implementation Project Coordinator (31200)", MGMT),
    ("Nordea: IT Analyst to Mortgage Service Domain (40523)", MGMT),
    ("CS Cloud Compliance Expert (31422)", MGMT),
    # — Infrastructure & Operations —
    ("Senior DevOps Engineer for Kong API Gateway (42117)", INFRA),
    ("ORLEN: Inżynier Dev-ops", INFRA),
    ("DEV OPS ze znajomością SalesForce", INFRA),
    ("Architekt Chmurowy ZOB-2742", INFRA),
    ("CLOUDFERRO: Specjalista ds. infrastruktury (Storage i Cloud)", INFRA),
    ("PL_Senior Infrastructure Operations Specialist (35014)", INFRA),
    ("Specjalista Helpdesk", INFRA),
    ("IT Support Engineer zastępstwo za Paweł Kurantowicz", INFRA),
    ("DBA Consultant: FACP DevOps (32174)", INFRA),
    ("SAP FICO Administrator", INFRA),
    ("Senior IT Application Operations specialist (37526)", INFRA),
    # — Software Development —
    ("PKO BP: Programista Java Middle ZOB-2727", SW),
    ("Starszy Programista Frontend_moduł I", SW),
    ("Programista .NET_moduł I", SW),
    ("HD Programista Java x2 Zapotrzebowanie 11 cz. 4", SW),
    ("2x Developer onsite WAW", SW),
    ("ON HOLD_PL_Senior Front-end Developer (38577)", SW),
    ("3 x Senior Fullstack Developer (PL/SQL, Java)", SW),
    ("PKO BP: Senior iOS Developer / ZOB-1788", SW),
    ("Expert Angular (17-19) / Typescript developer (40311)", SW),
    ("PL - Scala Developer Expert MDP TP#14689 (34429)", SW),
    ("PKP: System Architect", SW),
    ("Architekt Systemu (126 MD) WZ/SYS/SYS/DRA/00116/2023", SW),
    ("HD Architekt_moduł IV", SW),
    ("Architekt PowerApps (126MD) WZ/SYS/SYS/DRA/00191/2023", SW),
    ("PKO BP: Projektant UI/UX  ZOB-1793", SW),
    ("UX Designer - RFP ITVM-3360", SW),
    ("Guidewire Senior Developer  Expert", SW),
    # — Non-role buckets stay NULL —
    ("Opportunity", None),
    ("Stara kadencja", None),
    ("2023_115   usługa SD + onsite B2B", None),
    ("KYC I&P (Poland) (36512)", None),
    ("Główny Księgowy/Księgowa", None),
    ("Tax Consultant (EDL)", None),
    ("PKO BP: Specjalista ds. CRM i Kampanii  Personalizowanych", None),
]


@pytest.mark.unit
@pytest.mark.parametrize("title,expected", LIVE_TITLES)
def test_live_titles(title: str, expected: str | None) -> None:
    assert classify_job_title_to_cc_slug(title) == expected


@pytest.mark.unit
def test_empty_and_none() -> None:
    assert classify_job_title_to_cc_slug(None) is None
    assert classify_job_title_to_cc_slug("") is None
    assert classify_job_title_to_cc_slug("   ") is None


@pytest.mark.unit
def test_precedence_security_over_infra_and_software() -> None:
    # "bezpieczeństwa chmury" → security wins over the infra "chmur" rule.
    assert classify_job_title_to_cc_slug("Specjalista bezpieczeństwa chmury") == SEC
    # Security Architect → security, not the generic software "architect".
    assert classify_job_title_to_cc_slug("Security Architect") == SEC


@pytest.mark.unit
def test_precedence_infra_over_software() -> None:
    # Cloud architect → infra before the generic "architekt" software rule.
    assert classify_job_title_to_cc_slug("Architekt Chmurowy") == INFRA
    # DevOps + Salesforce → infra (devops) before software (salesforce).
    assert classify_job_title_to_cc_slug("DevOps ze znajomością Salesforce") == INFRA
