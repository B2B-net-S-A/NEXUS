"""Rozszerzone rodziny aliasów umiejętności — eksperyment rankingowy (punkt 4a).

Skąd ta lista: pomiar luki pokrycia na prodzie 17.08.2026. Bazowa taksonomia
(196 kanonicznych + 458 aliasów) nie zna narzędzi-podstaw z TYSIĄCAMI
kandydatów: git (14,8k), jira (11,9k), confluence (3,9k), excel, active
directory, maven, servicenow, bpmn, uml… Mechanizm wpływu na ranking:
`_extract_skills_from_champion` rozpoznaje w tekście Championa/JD wyłącznie
terminy z taksonomii (regex z ALIAS_MAP), a to jest źródło implicit-must dla
~88% ofert — termin spoza taksonomii jest w derived-must NIEWIDZIALNY.

Kuracja (świadome wybory):
- WYŁĄCZNIE technologie i narzędzia — zero soft-skills (team leadership,
  communication, stakeholder management…): w must-listach byłyby szumem,
  który ma każdy i nikt.
- Bez gołych 2-literowców jako aliasów ("ad", "ml") — regex ekstrakcji
  z tekstu łapie po granicach słów i krótkie skróty dają fałszywe trafienia.
- Mostki do ISTNIEJĄCYCH kanonicznych (rest apis → rest api) zamiast
  duplikowania rodzin; merge w loaderze i tak daje pierwszeństwo bazie
  (setdefault), więc kolizja z przyszłym seedem jest nieszkodliwa.

Za flagą `SKILL_ALIAS_EXTENDED_ENABLED` (default OFF, w _SCORING_CACHE_INPUTS)
— flip dopiero po pomiarze na zamrożonych 50 ofertach. Rodziny wchodzą TYLKO
do mapy scoringu; taksonomia boldowania CV (set_tech_taxonomy) celowo
NIETKNIĘTA — eksperyment nie może zmieniać wyglądu generowanych CV.
"""

from __future__ import annotations

# kanoniczna (lowercase) -> lista aliasów (lowercase). Kanoniczna sama mapuje
# się na siebie w loaderze; tu tylko warianty.
#
# PUSTA lista aliasów NIE jest no-opem: kanoniczna spoza bazowej taksonomii
# dostaje self-map w ALIAS_MAP, a regex ekstrakcji z tekstu Championa/JD jest
# budowany z KLUCZY tej mapy — samo dopisanie "figma"/"gradle"/"uml" czyni
# termin rozpoznawalnym w derived-must. To jest główny mechanizm eksperymentu;
# aliasy-warianty to nadbudowa.
EXTENDED_FAMILIES: dict[str, list[str]] = {
    # ── narzędzia codzienne (top luki wg liczby kandydatów) ────────────────
    "git": ["gitflow", "git flow"],
    "jira": ["atlassian jira"],
    "confluence": ["atlassian confluence"],
    "microsoft excel": ["excel", "ms excel", "advanced excel"],
    "microsoft office": ["ms office", "office 365", "microsoft 365"],
    "active directory": ["azure ad", "azure active directory", "entra id"],
    "figma": [],
    "maven": ["apache maven"],
    "gradle": [],
    "gitlab": [],
    "azure devops": ["azure devops server", "tfs"],
    "sharepoint": ["microsoft sharepoint"],
    "servicenow": [],
    "sap": ["sap erp"],
    "salesforce": ["salesforce crm"],
    "vmware": ["vsphere", "vmware vsphere", "esxi"],
    "windows server": [],
    "windows": ["microsoft windows"],
    "wordpress": [],
    "zabbix": [],
    "firebase": [],
    "google analytics": ["ga4"],
    # ── analiza / modelowanie / dane ───────────────────────────────────────
    "machine learning": ["uczenie maszynowe"],
    "bpmn": ["bpmn 2.0"],
    "uml": [],
    "etl": ["elt", "etl/elt"],
    "vba": ["excel vba"],
    "dax": [],
    "power query": [],
    "sql server reporting services": ["ssrs"],
    "sql server integration services": ["ssis"],
    # ── testowanie ────────────────────────────────────────────────────────
    "api testing": ["testowanie api"],
    "mockito": [],
    "testng": [],
    "testrail": [],
    "soapui": ["soap ui"],
    "robot framework": [],
    "regression testing": ["testy regresyjne"],
    "functional testing": ["testy funkcjonalne"],
    "test automation": ["automatyzacja testów", "automated testing"],
    # ── backend / integracje ──────────────────────────────────────────────
    "entity framework": ["ef core", "entity framework core"],
    "soap": ["soap api"],
    "xml": [],
    "json": [],
    "itil": ["itil v4"],
    "tomcat": ["apache tomcat"],
    "websphere": ["ibm websphere"],
    "wcf": [],
    "blazor": [],
    "signalr": [],
    # ── mostki wariantów do istniejących kanonicznych ─────────────────────
    # (kanoniczna JUŻ istnieje w bazie; merge setdefault tylko dopisze alias)
    "rest api": ["rest apis", "restful api", "restful apis"],
    "oracle db": ["oracle database"],
    "scrum": ["agile/scrum"],
    "microsoft sql server": ["sql server", "mssql", "ms sql"],
    "power bi": ["powerbi", "power-bi"],
    "node.js": ["nodejs"],
    "next.js": ["nextjs"],
    "react": ["reactjs", "react.js"],
    "vue.js": ["vue", "vuejs"],
    "spring boot": ["springboot"],
    "kubernetes": ["k8s"],
    "postgresql": ["postgres"],
}


def extended_alias_mapping() -> dict[str, str]:
    """Spłaszczona mapa alias->kanoniczna (z kanonicznymi jako no-op)."""
    mapping: dict[str, str] = {}
    for canonical, aliases in EXTENDED_FAMILIES.items():
        mapping[canonical] = canonical
        for alias in aliases:
            mapping[alias] = canonical
    return mapping
