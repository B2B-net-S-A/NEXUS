"""CV na Poligonie: dwa wpisy Nowości z edytora i karty „CV do klienta”.

Strażnik Nowości (22.11.2026) zgłaszał dwa wpisy z rekrutacji bez drogi do
elementu na Poligonie:

- „Lata w punkcie 1 i daty stanowisk” (`cv-editor.tenure-split`): pozycja QC
  `years_breakdown` z poprawką `tenure_split` pojawia się, gdy lata z punktu 1
  dotyczą tylko części ról, a cały staż z dat ról jest dłuższy o ponad rok.
  CV ćwiczebne (`frontend/src/lib/poligon/cv-fiction.ts`) ma od tego dnia
  starszą rolę analityka, a pozycja poniżej to wynik serwera
  (`cv_qc._years_breakdown_check`) na tym CV z 22.11.2026 — test
  `tests/test_poligon_cv_practice.py` liczy ją od nowa;
- „Gotowe CV z nową zgodą RODO” (`cv.ready-cv-new-consent`): pasek „Ta osoba
  ma już gotowe CV” pojawia się, gdy osoba nie ma jeszcze CV do klienta, ma
  gotowe CV etapu z innej rekrutacji, a klient wymaga zrzutu zgody. Na
  Poligonie to Bartosz Brzozowski ze Screeningu (odpowiedzi tylko dla jego
  etapu, store wybiera je przed osobą-szablonem), a klient ćwiczebny ma
  w regule CV „Zrzut zgody RODO” jak PKO BP.

Teksty są wymyślone (repo jest publiczne). Pozycja QC ma klucze spoza słownika
nagrania (`term`, `proposal`, `quote`, `dates`), więc odczyt QC edytora trafia
do `meta.fiction_responses`.
"""

from __future__ import annotations

import copy

TEMPLATE_ENTRY = 990305
TEMPLATE_CANDIDATE = 990105
POLIGON_JOB = 990001
POLIGON_CLIENT = 990501
TRAINER_REC = "Jakub Szkoleniowy"

# Osoba bez CV do klienta, z gotowym CV z innej rekrutacji (indeks 5 z `PEOPLE`).
READY_CV_PERSON = {
    "candidate_id": 990106,
    "entry_id": 990306,
    "name": "Bartosz Brzozowski",
}

# Punkt 1 i role CV ćwiczebnego — te same co w `cv-fiction.ts` (pilnuje
# `poligon-dataset.test.ts`).
POINT_ONE = "9 lat jako Project Manager w bankowości: migracja systemu płatności i bankowość mobilna."
ROLES = [
    ("Senior Project Manager", "03.2021 – obecnie", 69, True),
    ("Project Manager", "01.2017 – 02.2021", 50, True),
    ("Analityk biznesowy", "09.2013 – 12.2016", 40, False),
]
TENURE_PROPOSAL = "Ponad 13 lat w IT, w tym ponad 9 lat jako Project Manager"

QC_EDITOR_KEY = f"GET /api/pipeline/stages/{TEMPLATE_ENTRY}/qc?transient=true"
RULE_KEY = f"GET /api/cv-generator/clients/{POLIGON_CLIENT}/rule-for-generation"
RECRUITMENTS_KEY = f"GET /api/cv-generator/candidates/{TEMPLATE_CANDIDATE}/recruitments"
TEMPLATE_BRANDED_KEY = f"GET /api/candidates/stages/{TEMPLATE_ENTRY}/cv/branded"


def years_breakdown_check() -> dict:
    """Uwaga „Lata w punkcie 1 z dat stanowisk” w kształcie z `cv_qc`."""
    matched = sum(months for _, _, months, hit in ROLES if hit)
    total = sum(months for _, _, months, _ in ROLES)
    return {
        "key": "years_breakdown",
        "label": "Lata w punkcie 1 z dat stanowisk",
        "severity": "warning",
        "status": "fail",
        "summary": "Do decyzji",
        "items": [
            {
                "requirement": None,
                "role": None,
                "detail": (
                    "„9 lat” — role z punktu 1: 9 lat 11 mies., "
                    "cały staż z dat ról: 13 lat 3 mies."
                ),
                "fix": "tenure_split",
                "term": "9 lat",
                "role_index": None,
                "evidence": None,
                "evidence_kind": None,
                "proposal": TENURE_PROPOSAL,
                "tenure": {
                    "quote": "9 lat jako Project Manager w bankowości",
                    "matched_months": matched,
                    "total_months": total,
                    "proposal": TENURE_PROPOSAL,
                    "roles": [
                        {"title": t, "dates": d, "months": m, "matched": hit}
                        for t, d, m, hit in ROLES
                    ],
                },
            }
        ],
        "roles": [],
        "info": [],
        "dismissed_items": [],
        "muted": False,
    }


def with_years_breakdown(qc: dict) -> dict:
    """QC edytora z uwagą o latach w punkcie 1 (zamiast nagranej, jeśli była)."""
    out = copy.deepcopy(qc)
    checks = [c for c in out.get("checks", []) if c.get("key") != "years_breakdown"]
    at = next(
        (i + 1 for i, c in enumerate(checks) if c.get("key") == "years_header"),
        len(checks),
    )
    checks.insert(at, years_breakdown_check())
    out["checks"] = checks
    # Edytor pokazuje listę QC tylko dla CV z etapu, który jest otwarty
    # (`CvEditorIssues`: `qc.cv.stage_id !== stageId`). Odczyty edytora
    # nagrano na etapie innej osoby (`--cv-stage`), więc etap był obcy i lista
    # „Do poprawy” na Poligonie nigdy się nie pokazywała.
    if isinstance(out.get("cv"), dict):
        out["cv"] = {**out["cv"], "stage_id": TEMPLATE_ENTRY}
    out["passed"] = False
    out["warnings_count"] = sum(
        1
        for c in checks
        if c.get("severity") == "warning" and c.get("status") == "fail"
    )
    return out


def _other_recruitment(recruitments: list) -> dict:
    """Inna rekrutacja osoby-szablonu u tego klienta, w której CV już poszło."""
    for row in recruitments:
        if (
            row.get("job_id") != POLIGON_JOB
            and row.get("client_id") == POLIGON_CLIENT
            and row.get("stage") == "cv_sent"
        ):
            return row
    raise SystemExit(
        f"{RECRUITMENTS_KEY}: brak innej rekrutacji z „CV wysłane” — nagraj ją ponownie"
    )


def ready_cv_source(recruitments: list) -> dict:
    """CV etapu z innej rekrutacji: zatwierdzone, zgoda z tamtej nie jedzie."""
    row = _other_recruitment(recruitments)
    return {
        "items": [
            {
                "job_id": row["job_id"],
                "stage_id": row["stage_id"],
                "job_title": row.get("job_title"),
                "reference_number": "ĆW-02",
                "client_name": row.get("client_name"),
                "status": "finalized",
                "version": 2,
                "language": "pl",
                "blind": False,
                "updated_at": "@rel:-21.2",
                "updated_by_name": TRAINER_REC,
                "consent_carried": False,
            }
        ]
    }


def without_cv(branded: dict) -> dict:
    """CV do klienta etapu, którego jeszcze nie ma (`status: none`)."""
    return {
        **branded,
        "candidate_stage_id": READY_CV_PERSON["entry_id"],
        "status": "none",
        "content_html": None,
        "from_generator": False,
        "source": None,
        "generated_document_id": None,
        "edit_revision": 0,
        "version": 0,
        "updated_at": None,
        "updated_by": None,
        "updated_by_name": None,
        "consent_required": True,
    }


def cv_practice(dataset: dict) -> tuple[dict, list[str]]:
    """Odczyty do nałożenia na zestaw i klucze, które są w całości wymyślone."""
    entry = READY_CV_PERSON["entry_id"]
    candidate = READY_CV_PERSON["candidate_id"]
    rule = {**dataset[RULE_KEY], "requires_rodo_consent_block": True}
    out = {
        QC_EDITOR_KEY: with_years_breakdown(dataset[QC_EDITOR_KEY]),
        RULE_KEY: rule,
        f"GET /api/candidates/stages/{entry}/cv/branded": without_cv(
            dataset[TEMPLATE_BRANDED_KEY]
        ),
        f"GET /api/candidates/stages/{entry}/cv/branded/sources": ready_cv_source(
            dataset[RECRUITMENTS_KEY]
        ),
        f"GET /api/cv-generator/generated?candidate_id={candidate}"
        f"&job_id={POLIGON_JOB}&limit=10": [],
    }
    return out, [QC_EDITOR_KEY]
