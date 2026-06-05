"""Definicje 29 ról B2B + dwujęzyczne zakresy usług (seed insert-if-missing).

Zakresy zredagowane są **językiem usługi/rezultatu** — świadomie pozbawione
znamion umowy o pracę (art. 22 §1 KP): brak poleceń przełożonego, sztywnych
godzin, podporządkowania organizacyjnego, urlopu czy „wynagrodzenia za pracę".
Do każdej roli automatycznie dołączane są wspólne bullety o niezależności
(`_INDEP_*`), tak aby każdy zakres potwierdzał charakter B2B. Nadrzędne zdanie
o samodzielności znajduje się dodatkowo w nagłówku Załącznika nr 3 (szablon).

Rekordy trafiają do tabeli `b2b_contract_roles` i są edytowalne w UI; seeder
wstawia brakujące (po `slug`), nigdy nie nadpisuje ręcznych zmian.
"""

from __future__ import annotations

# 5 kategorii (spójne z Competence Categories) → (label_pl, label_en)
CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "infra": ("Infrastruktura i Operacje", "Infrastructure & Operations"),
    "dev": ("Rozwój Oprogramowania", "Software Development"),
    "data_ai": ("Dane i AI", "Data & AI"),
    "security_qa": ("Bezpieczeństwo i Jakość", "Security & Quality"),
    "management": ("Zarządzanie i Dostarczanie", "Management & Delivery"),
}

# Wspólne bullety o niezależności — doklejane do KAŻDEJ roli (charakter B2B).
_INDEP_PL: list[str] = [
    "Samodzielne decydowanie o sposobie, kolejności i metodyce realizacji prac, "
    "przy wykorzystaniu własnego warsztatu narzędziowego i własnej organizacji czasu.",
    "Przekazywanie efektów prac w uzgodnionych terminach na zasadzie "
    "odpowiedzialności za rezultat; dopuszczalna realizacja Usług przy udziale "
    "własnych podwykonawców za uprzednią zgodą B2BNET, z zachowaniem poufności.",
]
_INDEP_EN: list[str] = [
    "Independently determining the manner, order and methodology of the work, "
    "using the Partner's own toolset and own organisation of time.",
    "Delivering work results within agreed deadlines on a results-responsibility "
    "basis; the Services may be performed with the Partner's own subcontractors "
    "subject to B2BNET's prior consent and confidentiality.",
]


# Każdy wpis: (slug, category_key, name_pl, name_en, area, [scope_pl], [scope_en]).
# `area` używamy w obu językach (terminologia branżowa EN funkcjonuje w PL umowach).
_ROLE_DEFS: list[dict] = [
    # ── Infrastruktura i Operacje ────────────────────────────────────────────
    {
        "slug": "cloud-engineering",
        "category": "infra",
        "name_pl": "Cloud Engineering",
        "name_en": "Cloud Engineering",
        "area": "Cloud Engineering",
        "scope_pl": [
            "Projektowanie, wdrażanie i optymalizacja środowisk chmurowych "
            "(AWS / Azure / GCP) zgodnie z wymaganiami architektonicznymi Projektu.",
            "Automatyzacja provisioningu zasobów w modelu Infrastructure as Code "
            "(np. Terraform) oraz konfiguracja sieci, uprawnień i kosztów.",
            "Opracowywanie rozwiązań pod kątem skalowalności, niezawodności i "
            "optymalizacji kosztowej środowiska chmurowego.",
            "Wsparcie zespołu Klienta w zakresie migracji obciążeń do chmury i "
            "dobrych praktyk eksploatacji.",
        ],
        "scope_en": [
            "Designing, deploying and optimising cloud environments "
            "(AWS / Azure / GCP) in line with the Project's architectural requirements.",
            "Automating resource provisioning using Infrastructure as Code "
            "(e.g. Terraform) and configuring networking, permissions and cost controls.",
            "Engineering solutions for scalability, reliability and cost optimisation "
            "of the cloud environment.",
            "Supporting the Client's team with workload migration to the cloud and "
            "operational best practices.",
        ],
    },
    {
        "slug": "devops-engineering",
        "category": "infra",
        "name_pl": "DevOps Engineering",
        "name_en": "DevOps Engineering",
        "area": "DevOps Engineering",
        "scope_pl": [
            "Projektowanie i utrzymanie potoków CI/CD automatyzujących budowanie, "
            "testowanie i wdrażanie oprogramowania.",
            "Automatyzacja konfiguracji środowisk oraz procesów wydawniczych z "
            "wykorzystaniem narzędzi klasy IaC i konteneryzacji.",
            "Konfiguracja monitoringu, logowania i alertowania w celu zapewnienia "
            "obserwowalności dostarczanych rozwiązań.",
            "Opracowywanie usprawnień procesu wytwórczego skracających czas "
            "dostarczania zmian.",
        ],
        "scope_en": [
            "Designing and maintaining CI/CD pipelines that automate build, test and "
            "deployment of software.",
            "Automating environment configuration and release processes using IaC and "
            "containerisation tooling.",
            "Setting up monitoring, logging and alerting to ensure observability of the "
            "delivered solutions.",
            "Engineering delivery-process improvements that reduce change lead time.",
        ],
    },
    {
        "slug": "site-reliability-engineering",
        "category": "infra",
        "name_pl": "Site Reliability Engineering (SRE)",
        "name_en": "Site Reliability Engineering (SRE)",
        "area": "Site Reliability Engineering",
        "scope_pl": [
            "Opracowywanie i wdrażanie rozwiązań zwiększających niezawodność, "
            "dostępność i wydajność systemów produkcyjnych.",
            "Definiowanie i monitorowanie wskaźników SLI/SLO oraz budżetów błędów dla "
            "usług objętych Projektem.",
            "Automatyzacja reakcji na incydenty oraz eliminacja powtarzalnej pracy "
            "operacyjnej (toil).",
            "Udział w analizach poawaryjnych (post-mortem) i rekomendowanie trwałych "
            "usprawnień.",
        ],
        "scope_en": [
            "Engineering and implementing solutions that improve reliability, "
            "availability and performance of production systems.",
            "Defining and monitoring SLI/SLO metrics and error budgets for the services "
            "within the Project.",
            "Automating incident response and eliminating repetitive operational work "
            "(toil).",
            "Contributing to post-mortem analyses and recommending durable improvements.",
        ],
    },
    {
        "slug": "infrastructure-engineering",
        "category": "infra",
        "name_pl": "Infrastructure Engineering",
        "name_en": "Infrastructure Engineering",
        "area": "Infrastructure Engineering",
        "scope_pl": [
            "Projektowanie, wdrażanie i utrzymanie infrastruktury serwerowej, "
            "sieciowej i systemowej zgodnie z wymaganiami Projektu.",
            "Automatyzacja zarządzania konfiguracją oraz utrzymanie spójności "
            "środowisk (dev / test / prod).",
            "Opracowywanie rozwiązań w zakresie kopii zapasowych, odtwarzania po "
            "awarii i ciągłości działania.",
            "Optymalizacja wydajności i kosztów eksploatacji infrastruktury.",
        ],
        "scope_en": [
            "Designing, deploying and maintaining server, network and system "
            "infrastructure in line with the Project's requirements.",
            "Automating configuration management and maintaining consistency across "
            "environments (dev / test / prod).",
            "Engineering backup, disaster-recovery and business-continuity solutions.",
            "Optimising infrastructure performance and operating costs.",
        ],
    },
    {
        "slug": "kubernetes-containerization",
        "category": "infra",
        "name_pl": "Kubernetes / Containerization Engineering",
        "name_en": "Kubernetes / Containerization Engineering",
        "area": "Kubernetes / Containerization Engineering",
        "scope_pl": [
            "Projektowanie i utrzymanie klastrów Kubernetes oraz konteneryzacja "
            "aplikacji (Docker) zgodnie z wymaganiami Projektu.",
            "Opracowywanie manifestów, Helm chartów i polityk wdrożeniowych "
            "zapewniających powtarzalność i skalowalność.",
            "Konfiguracja sieci, zasobów, autoskalowania i bezpieczeństwa obciążeń "
            "kontenerowych.",
            "Wsparcie zespołu Klienta w zakresie dobrych praktyk orkiestracji "
            "kontenerów.",
        ],
        "scope_en": [
            "Designing and maintaining Kubernetes clusters and containerising "
            "applications (Docker) per the Project's requirements.",
            "Engineering manifests, Helm charts and deployment policies ensuring "
            "repeatability and scalability.",
            "Configuring networking, resources, autoscaling and security of "
            "containerised workloads.",
            "Supporting the Client's team with container-orchestration best practices.",
        ],
    },
    # ── Rozwój Oprogramowania ────────────────────────────────────────────────
    {
        "slug": "backend-development",
        "category": "dev",
        "name_pl": "Backend Software Development",
        "name_en": "Backend Software Development",
        "area": "Backend Software Development",
        "scope_pl": [
            "Projektowanie i implementacja logiki serwerowej, interfejsów API oraz "
            "integracji z bazami danych w ramach uzgodnionych rezultatów (kamieni "
            "milowych) Projektu.",
            "Dbałość o jakość, wydajność i bezpieczeństwo dostarczanego kodu zgodnie "
            "z przyjętymi w branży dobrymi praktykami oraz wymaganiami technicznymi "
            "Projektu.",
            "Udział w przeglądach kodu i uzgodnieniach technicznych w zakresie "
            "niezbędnym do koordynacji rezultatów z zespołem Klienta Projektu.",
            "Opracowywanie dokumentacji technicznej dostarczanych komponentów.",
        ],
        "scope_en": [
            "Designing and implementing server-side logic, APIs and database "
            "integrations within the agreed deliverables (milestones) of the Project.",
            "Ensuring quality, performance and security of the delivered code in line "
            "with industry best practices and the Project's technical requirements.",
            "Participating in code reviews and technical alignment to the extent "
            "necessary to coordinate results with the Client's team.",
            "Producing technical documentation of the delivered components.",
        ],
    },
    {
        "slug": "frontend-development",
        "category": "dev",
        "name_pl": "Frontend Development",
        "name_en": "Frontend Development",
        "area": "Frontend Development",
        "scope_pl": [
            "Projektowanie i implementacja warstwy prezentacji aplikacji webowych "
            "zgodnie z wymaganiami funkcjonalnymi i projektami UI.",
            "Integracja interfejsu z usługami i API oraz dbałość o wydajność i "
            "dostępność (accessibility) dostarczanych widoków.",
            "Zapewnienie responsywności i spójności rozwiązań w obsługiwanych "
            "przeglądarkach i urządzeniach.",
            "Udział w przeglądach kodu i uzgodnieniach technicznych z zespołem Klienta "
            "w zakresie niezbędnym do koordynacji rezultatów.",
        ],
        "scope_en": [
            "Designing and implementing the presentation layer of web applications per "
            "functional requirements and UI designs.",
            "Integrating the interface with services and APIs and ensuring performance "
            "and accessibility of the delivered views.",
            "Ensuring responsiveness and consistency across supported browsers and "
            "devices.",
            "Participating in code reviews and technical alignment with the Client's "
            "team to the extent necessary to coordinate results.",
        ],
    },
    {
        "slug": "fullstack-development",
        "category": "dev",
        "name_pl": "Fullstack Development",
        "name_en": "Fullstack Development",
        "area": "Fullstack Development",
        "scope_pl": [
            "Projektowanie i implementacja rozwiązań obejmujących zarówno warstwę "
            "serwerową, jak i prezentacji, w ramach uzgodnionych rezultatów Projektu.",
            "Realizacja integracji end-to-end (API, bazy danych, interfejs) z dbałością "
            "o spójność i jakość całości.",
            "Opracowywanie rozwiązań pod kątem wydajności, bezpieczeństwa i "
            "utrzymywalności kodu.",
            "Udział w uzgodnieniach technicznych i przeglądach kodu z zespołem Klienta "
            "w zakresie koordynacji rezultatów.",
        ],
        "scope_en": [
            "Designing and implementing solutions spanning both server-side and "
            "presentation layers within the Project's agreed deliverables.",
            "Delivering end-to-end integrations (APIs, databases, interface) with care "
            "for overall consistency and quality.",
            "Engineering for performance, security and maintainability of the code.",
            "Participating in technical alignment and code reviews with the Client's "
            "team to coordinate results.",
        ],
    },
    {
        "slug": "mobile-development",
        "category": "dev",
        "name_pl": "Mobile Application Development",
        "name_en": "Mobile Application Development",
        "area": "Mobile Application Development",
        "scope_pl": [
            "Projektowanie i implementacja aplikacji mobilnych (iOS / Android) zgodnie "
            "z wymaganiami funkcjonalnymi Projektu.",
            "Integracja aplikacji z usługami backendowymi oraz dbałość o wydajność, "
            "stabilność i UX na urządzeniach docelowych.",
            "Przygotowywanie buildów i wsparcie procesu publikacji w sklepach "
            "aplikacji.",
            "Udział w przeglądach kodu i uzgodnieniach technicznych z zespołem Klienta "
            "w zakresie koordynacji rezultatów.",
        ],
        "scope_en": [
            "Designing and implementing mobile applications (iOS / Android) per the "
            "Project's functional requirements.",
            "Integrating apps with backend services and ensuring performance, stability "
            "and UX on target devices.",
            "Preparing builds and supporting the app-store release process.",
            "Participating in code reviews and technical alignment with the Client's "
            "team to coordinate results.",
        ],
    },
    {
        "slug": "embedded-development",
        "category": "dev",
        "name_pl": "Embedded Software Development",
        "name_en": "Embedded Software Development",
        "area": "Embedded Software Development",
        "scope_pl": [
            "Projektowanie i implementacja oprogramowania wbudowanego dla urządzeń i "
            "systemów zgodnie z wymaganiami sprzętowymi Projektu.",
            "Realizacja integracji oprogramowania z warstwą sprzętową (firmware, "
            "sterowniki, protokoły komunikacyjne).",
            "Optymalizacja kodu pod kątem ograniczeń zasobowych, niezawodności i "
            "zużycia energii.",
            "Udział w testach integracyjnych i uzgodnieniach technicznych z zespołem "
            "Klienta.",
        ],
        "scope_en": [
            "Designing and implementing embedded software for devices and systems per "
            "the Project's hardware requirements.",
            "Integrating software with the hardware layer (firmware, drivers, "
            "communication protocols).",
            "Optimising code for resource constraints, reliability and energy "
            "consumption.",
            "Participating in integration testing and technical alignment with the "
            "Client's team.",
        ],
    },
    {
        "slug": "ux-ui-design",
        "category": "dev",
        "name_pl": "UX/UI Design",
        "name_en": "UX/UI Design",
        "area": "UX/UI Design",
        "scope_pl": [
            "Opracowywanie projektów interfejsów użytkownika oraz makiet i prototypów "
            "zgodnie z wymaganiami Projektu.",
            "Projektowanie ścieżek użytkownika (user flows) i dbałość o spójność oraz "
            "dostępność rozwiązań.",
            "Przygotowywanie specyfikacji projektowych i zasobów dla zespołu "
            "wytwórczego.",
            "Udział w uzgodnieniach koncepcji z zespołem Klienta w zakresie niezbędnym "
            "do koordynacji rezultatów.",
        ],
        "scope_en": [
            "Producing user-interface designs, wireframes and prototypes per the "
            "Project's requirements.",
            "Designing user flows and ensuring consistency and accessibility of the "
            "solutions.",
            "Preparing design specifications and assets for the development team.",
            "Participating in concept alignment with the Client's team to the extent "
            "necessary to coordinate results.",
        ],
    },
    # ── Dane i AI ────────────────────────────────────────────────────────────
    {
        "slug": "data-engineering",
        "category": "data_ai",
        "name_pl": "Data Engineering",
        "name_en": "Data Engineering",
        "area": "Data Engineering",
        "scope_pl": [
            "Projektowanie, budowa i utrzymanie potoków danych (ETL/ELT) oraz "
            "integracja źródeł danych zgodnie z wymaganiami Projektu.",
            "Modelowanie i optymalizacja struktur danych (hurtownie, jeziora danych) "
            "pod kątem wydajności i jakości.",
            "Zapewnienie jakości, spójności i bezpieczeństwa przetwarzanych danych.",
            "Wsparcie zespołów analitycznych Klienta w zakresie udostępniania danych.",
        ],
        "scope_en": [
            "Designing, building and maintaining data pipelines (ETL/ELT) and "
            "integrating data sources per the Project's requirements.",
            "Modelling and optimising data structures (warehouses, lakes) for "
            "performance and quality.",
            "Ensuring quality, consistency and security of the processed data.",
            "Supporting the Client's analytics teams with data provisioning.",
        ],
    },
    {
        "slug": "data-science",
        "category": "data_ai",
        "name_pl": "Data Science",
        "name_en": "Data Science",
        "area": "Data Science",
        "scope_pl": [
            "Opracowywanie analiz, modeli statystycznych i predykcyjnych "
            "odpowiadających na zdefiniowane potrzeby biznesowe Projektu.",
            "Eksploracja i przygotowanie danych oraz walidacja jakości wyników "
            "analitycznych.",
            "Prezentowanie wniosków i rekomendacji w formie raportów oraz wizualizacji.",
            "Udział w uzgodnieniach zakresu analiz z zespołem Klienta w zakresie "
            "koordynacji rezultatów.",
        ],
        "scope_en": [
            "Developing analyses and statistical/predictive models addressing the "
            "Project's defined business needs.",
            "Exploring and preparing data and validating the quality of analytical "
            "results.",
            "Presenting findings and recommendations as reports and visualisations.",
            "Participating in scoping the analyses with the Client's team to coordinate "
            "results.",
        ],
    },
    {
        "slug": "machine-learning-engineering",
        "category": "data_ai",
        "name_pl": "Machine Learning Engineering",
        "name_en": "Machine Learning Engineering",
        "area": "Machine Learning Engineering",
        "scope_pl": [
            "Projektowanie, trenowanie i wdrażanie modeli uczenia maszynowego zgodnie "
            "z wymaganiami Projektu.",
            "Budowa potoków treningowych i inferencyjnych oraz ich integracja z "
            "systemami produkcyjnymi.",
            "Optymalizacja modeli pod kątem jakości, wydajności i kosztów oraz "
            "monitorowanie ich działania.",
            "Udział w uzgodnieniach technicznych z zespołem Klienta w zakresie "
            "koordynacji rezultatów.",
        ],
        "scope_en": [
            "Designing, training and deploying machine-learning models per the "
            "Project's requirements.",
            "Building training and inference pipelines and integrating them with "
            "production systems.",
            "Optimising models for quality, performance and cost, and monitoring their "
            "operation.",
            "Participating in technical alignment with the Client's team to coordinate "
            "results.",
        ],
    },
    {
        "slug": "business-intelligence",
        "category": "data_ai",
        "name_pl": "Business Intelligence (BI)",
        "name_en": "Business Intelligence (BI)",
        "area": "Business Intelligence",
        "scope_pl": [
            "Projektowanie i budowa raportów, kokpitów i modeli danych wspierających "
            "decyzje biznesowe Klienta.",
            "Integracja i transformacja danych na potrzeby warstwy raportowej.",
            "Zapewnienie poprawności, czytelności i wydajności dostarczanych analiz.",
            "Wsparcie użytkowników Klienta w interpretacji dostarczanych raportów.",
        ],
        "scope_en": [
            "Designing and building reports, dashboards and data models supporting the "
            "Client's business decisions.",
            "Integrating and transforming data for the reporting layer.",
            "Ensuring correctness, clarity and performance of the delivered analyses.",
            "Supporting the Client's users in interpreting the delivered reports.",
        ],
    },
    {
        "slug": "mlops-engineering",
        "category": "data_ai",
        "name_pl": "MLOps Engineering",
        "name_en": "MLOps Engineering",
        "area": "MLOps Engineering",
        "scope_pl": [
            "Projektowanie i utrzymanie potoków automatyzujących cykl życia modeli ML "
            "(trening, wdrożenie, monitoring).",
            "Automatyzacja wersjonowania danych i modeli oraz zapewnienie "
            "powtarzalności eksperymentów.",
            "Konfiguracja monitoringu jakości modeli i wykrywania dryfu w środowisku "
            "produkcyjnym.",
            "Wsparcie zespołów data science Klienta w operacjonalizacji modeli.",
        ],
        "scope_en": [
            "Designing and maintaining pipelines automating the ML model lifecycle "
            "(training, deployment, monitoring).",
            "Automating data and model versioning and ensuring reproducibility of "
            "experiments.",
            "Configuring model-quality monitoring and drift detection in production.",
            "Supporting the Client's data-science teams in operationalising models.",
        ],
    },
    # ── Bezpieczeństwo i Jakość ──────────────────────────────────────────────
    {
        "slug": "cybersecurity",
        "category": "security_qa",
        "name_pl": "Cybersecurity",
        "name_en": "Cybersecurity",
        "area": "Cybersecurity",
        "scope_pl": [
            "Opracowywanie i wdrażanie zabezpieczeń systemów i aplikacji zgodnie z "
            "wymaganiami bezpieczeństwa Projektu.",
            "Identyfikacja podatności i rekomendowanie działań naprawczych oraz "
            "hardeningu środowisk.",
            "Opracowywanie polityk, standardów i dokumentacji bezpieczeństwa.",
            "Wsparcie zespołu Klienta w reagowaniu na zagrożenia i podnoszeniu poziomu "
            "bezpieczeństwa.",
        ],
        "scope_en": [
            "Engineering and implementing security controls for systems and "
            "applications per the Project's security requirements.",
            "Identifying vulnerabilities and recommending remediation and environment "
            "hardening.",
            "Developing security policies, standards and documentation.",
            "Supporting the Client's team in responding to threats and raising the "
            "security posture.",
        ],
    },
    {
        "slug": "security-operations-soc",
        "category": "security_qa",
        "name_pl": "Security Operations (SOC)",
        "name_en": "Security Operations (SOC)",
        "area": "Security Operations (SOC)",
        "scope_pl": [
            "Monitorowanie zdarzeń i alertów bezpieczeństwa oraz analiza potencjalnych "
            "incydentów zgodnie z procedurami Projektu.",
            "Opracowywanie i strojenie reguł detekcji w systemach klasy SIEM/EDR.",
            "Prowadzenie analizy incydentów i rekomendowanie działań ograniczających "
            "ryzyko.",
            "Opracowywanie dokumentacji i raportów z obsługiwanych zdarzeń.",
        ],
        "scope_en": [
            "Monitoring security events and alerts and analysing potential incidents "
            "per the Project's procedures.",
            "Developing and tuning detection rules in SIEM/EDR-class systems.",
            "Conducting incident analysis and recommending risk-mitigating actions.",
            "Producing documentation and reports on the handled events.",
        ],
    },
    {
        "slug": "penetration-testing",
        "category": "security_qa",
        "name_pl": "Penetration Testing",
        "name_en": "Penetration Testing",
        "area": "Penetration Testing",
        "scope_pl": [
            "Przeprowadzanie kontrolowanych testów bezpieczeństwa aplikacji, systemów "
            "i infrastruktury zgodnie z uzgodnionym zakresem.",
            "Identyfikacja i dokumentowanie podatności wraz z oceną ryzyka i "
            "rekomendacjami naprawczymi.",
            "Opracowywanie raportów technicznych i podsumowań dla interesariuszy "
            "Projektu.",
            "Wsparcie zespołu Klienta w weryfikacji skuteczności wdrożonych poprawek.",
        ],
        "scope_en": [
            "Conducting controlled security tests of applications, systems and "
            "infrastructure within the agreed scope.",
            "Identifying and documenting vulnerabilities together with risk assessment "
            "and remediation recommendations.",
            "Producing technical reports and summaries for the Project's stakeholders.",
            "Supporting the Client's team in verifying the effectiveness of applied "
            "fixes.",
        ],
    },
    {
        "slug": "identity-access-management",
        "category": "security_qa",
        "name_pl": "Identity & Access Management (IAM)",
        "name_en": "Identity & Access Management (IAM)",
        "area": "Identity & Access Management",
        "scope_pl": [
            "Projektowanie i wdrażanie rozwiązań zarządzania tożsamością i dostępem "
            "zgodnie z wymaganiami Projektu.",
            "Konfiguracja mechanizmów uwierzytelniania, autoryzacji i federacji "
            "tożsamości.",
            "Opracowywanie polityk dostępu oraz procesów nadawania i odbierania "
            "uprawnień.",
            "Wsparcie zespołu Klienta w audytach i utrzymaniu zgodności dostępów.",
        ],
        "scope_en": [
            "Designing and implementing identity and access management solutions per "
            "the Project's requirements.",
            "Configuring authentication, authorisation and identity-federation "
            "mechanisms.",
            "Developing access policies and provisioning/de-provisioning processes.",
            "Supporting the Client's team in access audits and compliance.",
        ],
    },
    {
        "slug": "devsecops",
        "category": "security_qa",
        "name_pl": "DevSecOps",
        "name_en": "DevSecOps",
        "area": "DevSecOps",
        "scope_pl": [
            "Integracja praktyk i narzędzi bezpieczeństwa w potokach CI/CD "
            "(security-by-design).",
            "Automatyzacja skanowania kodu, zależności i obrazów oraz analiza wyników.",
            "Opracowywanie rekomendacji hardeningu i polityk bezpieczeństwa procesu "
            "wytwórczego.",
            "Wsparcie zespołów wytwórczych Klienta w eliminacji podatności na wczesnym "
            "etapie.",
        ],
        "scope_en": [
            "Integrating security practices and tooling into CI/CD pipelines "
            "(security-by-design).",
            "Automating code, dependency and image scanning and analysing results.",
            "Developing hardening recommendations and security policies for the "
            "delivery process.",
            "Supporting the Client's development teams in eliminating vulnerabilities "
            "early.",
        ],
    },
    {
        "slug": "qa-engineering",
        "category": "security_qa",
        "name_pl": "QA / Test Engineering",
        "name_en": "QA / Test Engineering",
        "area": "Quality Assurance / Test Engineering",
        "scope_pl": [
            "Opracowywanie scenariuszy i przypadków testowych oraz prowadzenie testów "
            "funkcjonalnych i niefunkcjonalnych zgodnie z wymaganiami Projektu.",
            "Identyfikacja, dokumentowanie i raportowanie defektów oraz weryfikacja "
            "poprawek.",
            "Współtworzenie strategii i planów testów oraz dbałość o jakość "
            "dostarczanych rozwiązań.",
            "Udział w uzgodnieniach kryteriów akceptacji z zespołem Klienta w zakresie "
            "koordynacji rezultatów.",
        ],
        "scope_en": [
            "Developing test scenarios and cases and performing functional and "
            "non-functional testing per the Project's requirements.",
            "Identifying, documenting and reporting defects and verifying fixes.",
            "Co-creating test strategies and plans and safeguarding the quality of "
            "delivered solutions.",
            "Participating in acceptance-criteria alignment with the Client's team to "
            "coordinate results.",
        ],
    },
    {
        "slug": "test-automation",
        "category": "security_qa",
        "name_pl": "Test Automation",
        "name_en": "Test Automation",
        "area": "Test Automation",
        "scope_pl": [
            "Projektowanie i implementacja testów automatycznych (jednostkowych, "
            "integracyjnych, E2E) zgodnie z wymaganiami Projektu.",
            "Budowa i utrzymanie frameworków oraz integracja testów z potokami CI/CD.",
            "Analiza wyników testów, raportowanie i rekomendowanie usprawnień jakości.",
            "Udział w uzgodnieniach technicznych z zespołem Klienta w zakresie "
            "koordynacji rezultatów.",
        ],
        "scope_en": [
            "Designing and implementing automated tests (unit, integration, E2E) per "
            "the Project's requirements.",
            "Building and maintaining frameworks and integrating tests into CI/CD "
            "pipelines.",
            "Analysing test results, reporting and recommending quality improvements.",
            "Participating in technical alignment with the Client's team to coordinate "
            "results.",
        ],
    },
    # ── Zarządzanie i Dostarczanie ───────────────────────────────────────────
    {
        "slug": "product-management",
        "category": "management",
        "name_pl": "Product Management",
        "name_en": "Product Management",
        "area": "Product Management",
        "scope_pl": [
            "Opracowywanie i utrzymywanie wizji, mapy drogowej oraz backlogu produktu "
            "zgodnie z celami biznesowymi Projektu.",
            "Definiowanie wymagań i priorytetów oraz analiza wartości dostarczanej "
            "przez kolejne wydania.",
            "Koordynacja merytoryczna prac wytwórczych z interesariuszami Projektu na "
            "zasadzie współpracy.",
            "Analiza danych i informacji zwrotnej w celu rekomendowania kierunków "
            "rozwoju produktu.",
        ],
        "scope_en": [
            "Developing and maintaining the product vision, roadmap and backlog in line "
            "with the Project's business goals.",
            "Defining requirements and priorities and analysing the value delivered by "
            "successive releases.",
            "Substantively coordinating development work with the Project's stakeholders "
            "on a collaborative basis.",
            "Analysing data and feedback to recommend product-development directions.",
        ],
    },
    {
        "slug": "project-management-it",
        "category": "management",
        "name_pl": "Project Management (IT)",
        "name_en": "Project Management (IT)",
        "area": "IT Project Management",
        "scope_pl": [
            "Opracowywanie i utrzymywanie harmonogramu, zakresu i planu realizacji "
            "Projektu zgodnie z uzgodnionymi celami.",
            "Koordynacja merytoryczna zadań i kamieni milowych oraz monitorowanie "
            "postępu i ryzyk.",
            "Raportowanie statusu i rekomendowanie działań korygujących interesariuszom "
            "Projektu.",
            "Wsparcie komunikacji pomiędzy stronami zaangażowanymi w realizację "
            "Projektu.",
        ],
        "scope_en": [
            "Developing and maintaining the Project's schedule, scope and delivery plan "
            "in line with agreed goals.",
            "Substantively coordinating tasks and milestones and monitoring progress "
            "and risks.",
            "Reporting status and recommending corrective actions to the Project's "
            "stakeholders.",
            "Supporting communication between the parties involved in the Project.",
        ],
    },
    {
        "slug": "scrum-master",
        "category": "management",
        "name_pl": "Scrum Master",
        "name_en": "Scrum Master",
        "area": "Scrum Master / Agile Delivery",
        "scope_pl": [
            "Wsparcie zespołu Projektu w stosowaniu praktyk zwinnych oraz facylitacja "
            "zdarzeń (planowanie, przegląd, retrospektywa).",
            "Identyfikacja i pomoc w usuwaniu przeszkód wpływających na tempo "
            "dostarczania.",
            "Opracowywanie i monitorowanie metryk procesu oraz rekomendowanie "
            "usprawnień.",
            "Współpraca z interesariuszami w zakresie przepływu pracy i przejrzystości "
            "postępów.",
        ],
        "scope_en": [
            "Supporting the Project team in applying agile practices and facilitating "
            "events (planning, review, retrospective).",
            "Identifying and helping remove impediments affecting delivery pace.",
            "Developing and monitoring process metrics and recommending improvements.",
            "Collaborating with stakeholders on workflow and progress transparency.",
        ],
    },
    {
        "slug": "business-analysis",
        "category": "management",
        "name_pl": "Business Analysis",
        "name_en": "Business Analysis",
        "area": "Business Analysis",
        "scope_pl": [
            "Identyfikacja, analiza i dokumentowanie wymagań biznesowych i "
            "funkcjonalnych Projektu.",
            "Modelowanie procesów oraz opracowywanie specyfikacji dla zespołu "
            "wytwórczego.",
            "Walidacja rozwiązań względem potrzeb biznesowych i wsparcie testów "
            "akceptacyjnych.",
            "Wsparcie komunikacji pomiędzy stroną biznesową a zespołem realizującym "
            "Projekt.",
        ],
        "scope_en": [
            "Identifying, analysing and documenting the Project's business and "
            "functional requirements.",
            "Modelling processes and producing specifications for the development team.",
            "Validating solutions against business needs and supporting acceptance "
            "testing.",
            "Supporting communication between the business side and the delivery team.",
        ],
    },
    {
        "slug": "it-architecture",
        "category": "management",
        "name_pl": "IT Architecture",
        "name_en": "IT Architecture",
        "area": "IT Architecture",
        "scope_pl": [
            "Opracowywanie koncepcji architektury rozwiązań i systemów zgodnie z "
            "wymaganiami Projektu.",
            "Definiowanie standardów, wzorców i wytycznych technicznych oraz dbałość o "
            "ich spójność.",
            "Ocena rozwiązań pod kątem skalowalności, bezpieczeństwa, kosztów i "
            "utrzymywalności.",
            "Wsparcie zespołów wytwórczych Klienta w realizacji zgodnej z przyjętą "
            "architekturą.",
        ],
        "scope_en": [
            "Developing solution and system architecture concepts per the Project's "
            "requirements.",
            "Defining technical standards, patterns and guidelines and ensuring their "
            "consistency.",
            "Assessing solutions for scalability, security, cost and maintainability.",
            "Supporting the Client's development teams in delivering in line with the "
            "adopted architecture.",
        ],
    },
    {
        "slug": "engineering-management",
        "category": "management",
        "name_pl": "Engineering Management",
        "name_en": "Engineering Management",
        "area": "Engineering Management",
        "scope_pl": [
            "Koordynacja merytoryczna prac inżynierskich w Projekcie oraz dbałość o "
            "jakość i terminowość dostarczanych rezultatów.",
            "Opracowywanie standardów technicznych, dobrych praktyk i usprawnień "
            "procesu wytwórczego.",
            "Wsparcie planowania i priorytetyzacji prac we współpracy z interesariuszami "
            "Projektu.",
            "Analiza wskaźników dostarczania i rekomendowanie działań usprawniających.",
        ],
        "scope_en": [
            "Substantively coordinating engineering work in the Project and "
            "safeguarding the quality and timeliness of deliverables.",
            "Developing technical standards, best practices and delivery-process "
            "improvements.",
            "Supporting planning and prioritisation in collaboration with the Project's "
            "stakeholders.",
            "Analysing delivery metrics and recommending improvements.",
        ],
    },
]


def get_b2b_roles() -> list[dict]:
    """Zwraca pełną listę ról gotową do seedowania.

    Doklejamy wspólne bullety o niezależności (`_INDEP_*`) i rozwijamy etykiety
    kategorii oraz `display_order` (kolejność = kolejność w `_ROLE_DEFS`).
    """
    rows: list[dict] = []
    for idx, r in enumerate(_ROLE_DEFS):
        cat_pl, cat_en = CATEGORY_LABELS[r["category"]]
        rows.append(
            {
                "slug": r["slug"],
                "category_key": r["category"],
                "category_label_pl": cat_pl,
                "category_label_en": cat_en,
                "name_pl": r["name_pl"],
                "name_en": r["name_en"],
                "area_label_pl": r["area"],
                "area_label_en": r["area"],
                "scope_pl": [*r["scope_pl"], *_INDEP_PL],
                "scope_en": [*r["scope_en"], *_INDEP_EN],
                "display_order": idx,
            }
        )
    return rows


B2B_ROLES: list[dict] = get_b2b_roles()
