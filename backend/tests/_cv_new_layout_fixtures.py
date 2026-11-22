"""Fikcyjne CV do testów układu „Nowe CV” (repo jest publiczne: żadnych prawdziwych osób)."""

from __future__ import annotations

import copy
import struct
import zlib
from datetime import date

TODAY = date(2026, 11, 20)

PANGRAM = "Zażółć gęślą jaźń"
PANGRAM_UPPER = "ZAŻÓŁĆ GĘŚLĄ JAŹŃ"

_SKILL_WORDS = (
    "Python",
    "SQL",
    "Kafka",
    "Airflow",
    "dbt",
    "Spark",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Jira",
    "Confluence",
    "BPMN",
    "UML",
    "REST API",
    "GraphQL",
    "PostgreSQL",
    "Oracle",
    "Power BI",
    "Tableau",
    "Git",
    "Jenkins",
    "Azure",
    "AWS",
    "Linux",
)


def _skill_groups(n: int, per_group: int) -> list[dict]:
    groups = []
    for g in range(n):
        items = [
            f"{_SKILL_WORDS[(g * 3 + i) % len(_SKILL_WORDS)]} {g}.{i}"
            for i in range(per_group)
        ]
        groups.append(
            {"label": f"Kategoria {g + 1}:", "content": ", ".join(items) + "."}
        )
    return groups


def long_cv() -> dict:
    roles = [
        (
            "03.2023 – obecnie",
            "Bank Przykładowy S.A.",
            "bankowość",
            "Główny analityk danych",
        ),
        (
            "01.2021 – 02.2023",
            "Ubezpieczenia Beta sp. z o.o.",
            "ubezpieczenia",
            "Analityk danych",
        ),
        ("06.2019 – 12.2020", "Logistyka Gamma", "logistyka", "Analityk systemowy"),
        ("08.2019 – 11.2019", "Projekt Delta", "IT", "Konsultant"),
        ("2016 - 09.2019", "Softwarehouse Alfa", "IT", "Programista Python"),
        ("2014 - 2016", "Handel Epsilon", "handel", "Młodszy analityk"),
        ("2012 - 2014", "Telekom Zeta", "telekomunikacja", "Stażysta BI"),
        ("2010 - 2012", "Energetyka Eta", "energetyka", "Specjalista raportowania"),
        ("2008 - 2010", "Uczelnia Theta", "edukacja", "Asystent"),
    ]
    experience = [
        {
            "dates": d,
            "company": c,
            "industry": ind,
            "position": p,
            "technologies": ["Python", "SQL", "Kafka", "Power BI"],
            "responsibilities": [
                f"Projektowanie potoków danych w Python i SQL dla zespołu {i + 1} — {PANGRAM}",
                "Budowa raportów zarządczych w Power BI oraz utrzymanie hurtowni danych.",
                "Współpraca z biznesem przy zbieraniu wymagań, modelowanie procesów w BPMN i UML.",
                f"Automatyzacja testów danych; {PANGRAM_UPPER} „cytat” – myślnik · kropka.",
            ],
        }
        for i, (d, c, ind, p) in enumerate(roles)
    ]
    return {
        "name": "Łucja Przykładowa",
        "position": "Analityk danych",
        "presentation_position": "Starszy analityk danych",
        "languages": ["Polski - ojczysty", "Angielski - C1/C2", "Niemiecki - B1"],
        "why_points": [
            "**Ponad 15 lat** doświadczenia w **analizie danych** i hurtowniach danych.",
            "Praktyczne doświadczenie z **Python**, **SQL** i **Kafka** w bankowości i ubezpieczeniach.",
            "**Skrócenie raportowania o 40%** dzięki automatyzacji potoków danych.",
            "Czwarty punkt, którego strona 1 nie pokazuje.",
        ],
        "experience": experience,
        "skills": _skill_groups(12, 14),
        "education": [
            {
                "dates": "2005 - 2008",
                "degree": "Informatyka - magister inżynier",
                "institution": "Politechnika Wzorcowa",
                "location": "Warszawa",
            },
            {
                "dates": "2002 - 2005",
                "degree": "Matematyka - licencjat",
                "institution": "Uniwersytet Testowy",
                "location": "Kraków",
            },
            {
                "dates": "1998 - 2002",
                "degree": "",
                "institution": "Liceum Ogólnokształcące nr 1",
                "location": "",
            },
        ],
        "certifications": [
            f"Certyfikat danych {i} - Instytut Przykładowy ({2014 + i})"
            for i in range(9)
        ]
        + ["Azure Data Fundamentals - Microsoft"],
        "highlight_keywords": [
            "Python",
            "SQL",
            "Kafka",
            "Power BI",
            "hurtownie danych",
        ],
        "language": "pl",
        "blind_cv": False,
    }


def huge_cv() -> dict:
    """Jak `long_cv`, ale umiejętności nie zmieszczą się w całości — wymusza „+N”."""
    data = long_cv()
    data["skills"] = _skill_groups(12, 30)
    return data


def short_cv() -> dict:
    return {
        "name": "Jan Testowy",
        "position": "Tester oprogramowania",
        "languages": [],
        "why_points": [f"Doświadczenie w testach manualnych — {PANGRAM}."],
        "experience": [
            {
                "dates": "05.2024 – obecnie",
                "company": "Firma Kappa",
                "industry": "IT",
                "position": "Młodszy tester",
                "technologies": ["Jira"],
                "responsibilities": ["Testy manualne aplikacji webowej."],
            }
        ],
        "skills": [{"label": "Testowanie", "content": "testy manualne, Jira"}],
        "education": [
            {
                "dates": "2020 - 2024",
                "degree": "Informatyka - inżynier",
                "institution": "Politechnika Wzorcowa",
                "location": "",
            }
        ],
        "certifications": [],
        "highlight_keywords": ["Jira"],
        "language": "pl",
        "blind_cv": False,
    }


def english(data: dict) -> dict:
    out = copy.deepcopy(data)
    out["language"] = "en"
    out["languages"] = ["Polish - native", "English - C1"]
    return out


def blind(data: dict) -> dict:
    out = copy.deepcopy(data)
    out["blind_cv"] = True
    return out


def tiny_png(width: int = 40, height: int = 20) -> bytes:
    """Prawidłowy PNG bez zależności (szary prostokąt)."""
    raw = b"".join(b"\x00" + b"\x99\x99\x99" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
