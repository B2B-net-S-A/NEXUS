#!/usr/bin/env python3
"""Jednorazowa konwersja scripts/champion_template_clients.json → app/data/client_playbooks/seed.json.

Reguły przydziału linii z „standardy" (pierwsze trafienie wygrywa):
  SENSITIVE — wykluczenia po pochodzeniu: ZOSTAJĄ w process_rules_md (decyzja 03.09.2026);
              `--drop-sensitive` wycina je i drukuje na stderr;
  PRIORITY  — reguły priorytetu → priority_rules;
  RATE      — stawki/budżet → process_rules_md (sprawdzane PRZED onboardingiem, bo „stawek umownych" ma „umow");
  ONBOARD   — sprzęt, adresy, dokumenty, rozliczenia, umowy, PESEL → onboarding_md;
  reszta    → process_rules_md (w tym linie o nazwie pliku i języku CV — dublują regułę CV,
              ale NIC z wzorów nie może zginąć; DL usunie je, gdy reguła CV jest zatwierdzona).
Liczby (SLA, limity) NIE są parsowane z tekstu — pochodzą z tabeli META (plan §4.1).
Na końcu skrypt sprawdza KOMPLETNOŚĆ: każda niepusta linia źródłowa musi być w karcie
(linia z URL-em: jej URL w `documents`); inaczej kończy się błędem — to dowód, że nic nie uciekło.

Uruchomienie z katalogu backend/:
    python3 scripts/build_client_playbook_seed.py [--drop-sensitive]

UWAGA: plik źródłowy `scripts/champion_template_clients.json` został usunięty po
tej jednorazowej konwersji, więc skrypt nie ma dziś czego czytać — zostaje jako
zapis reguł podziału treści. Wygenerowany `seed.json` ma JEDNĄ ręczną korektę
niesioną przez źródło: wzór PFRON mówił, że sprzęt zapewnia „bank Nordea"
(kopiuj-wklej ze wzoru Nordei) — na karcie PFRON zdanie mówi „przez klienta".
Odtwarzając seed ze starego źródła, powtórz tę poprawkę; pilnuje jej
`test_seed_never_names_another_client_in_card_text`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

SRC = pathlib.Path("scripts/champion_template_clients.json")
DST = pathlib.Path("app/data/client_playbooks/seed.json")

RATE_ALIOR = (
    "Stawki oczekiwane zawsze w zapytaniu; brak jednoznacznego FA, "
    "bazujemy na dotychczasowych zatrudnieniach."
)
RATE_NORDEA = (
    "Kandydaci poza budżetem klienta rozpatrywani case by case; "
    "przed przerobieniem CV kontakt z Marcinem lub Igorem."
)

META = {
    "ALIOR": dict(
        seed_key="profil-championa-wzor-alior-docx",
        name_pattern="%alior%",
        cv_limit_per_process=2,
        rate_policy=RATE_ALIOR,
    ),
    "BIK": dict(
        seed_key="profil-championa-wzor-bik-docx",
        name_pattern="%informacji kredytowej%",
        rate_policy=RATE_ALIOR,
    ),
    "BNP PARIBAS": dict(
        seed_key="profil-championa-wzor-bnp-paribas-docx",
        name_pattern="%bnp%",
        sla_business_days=10,
        sla_min_candidates=2,
        cv_limit_per_process=6,
        multi_project_cooldown_days=14,
        rate_policy=(
            "Nie przekraczamy stawek umownych; wyjątek: Architekci i profile "
            "skomplikowane, nierynkowe."
        ),
    ),
    "Bank_Pocztowy": dict(
        seed_key="profil-championa-wzor-bank-pocztowy-docx",
        name_pattern="%pocztow%",
        cv_limit_per_process=2,
        hold_hours=24,
    ),
    "Credit_Agricole": dict(
        seed_key="profil-championa-wzor-credit-agricole-docx",
        name_pattern="%credit agricole%",
    ),
    "ENERGA": dict(
        seed_key="profil-championa-wzor-energa-docx",
        name_pattern="%energa%",
        cv_limit_per_process=5,
    ),
    "KIR": dict(
        seed_key="profil-championa-wzor-kir-docx",
        name_pattern="%krajowa izba rozliczeniowa%",
    ),
    "Nordea": dict(
        seed_key="profil-championa-wzor-nordea-docx",
        name_pattern="%nordea%",
        sla_business_days=5,
        sla_min_candidates=1,
        hold_hours=24,
        rate_policy=RATE_NORDEA,
    ),
    "ORLEN": dict(
        seed_key="profil-championa-wzor-orlen-docx",
        name_pattern="%orlen%",
        cv_limit_per_process=5,
    ),
    "PANSA": dict(
        seed_key="profil-championa-wzor-pansa-docx",
        name_pattern="%pansa%",
        sla_business_days=5,
        cv_limit_per_process=3,
        hold_hours=24,
        rate_policy=(
            "Limit stawki, nie rekomendujemy powyżej; ewentualnie 5 zł powyżej "
            "po konsultacji z DL (Michał Walasek)."
        ),
    ),
    "PFRON": dict(
        seed_key="profil-championa-wzor-pfron-docx",
        name_pattern="%pfron%",
        sla_business_days=10,
        sla_min_candidates=1,
        hold_hours=24,
        rate_policy=RATE_NORDEA,
    ),
    "PKO_BP": dict(
        seed_key="profil-championa-wzor-pko-bp-docx",
        name_pattern="%pko%",
        hold_hours=24,
    ),
    "SANTANDER": dict(
        seed_key="profil-championa-wzor-santander-docx",
        name_pattern="%santander%",
    ),
    "Tauron": dict(
        seed_key="profil-championa-wzor-tauron-docx",
        name_pattern="%tauron%",
        sla_business_days=5,
        sla_min_candidates=1,
        hold_hours=24,
        rate_policy="Brak limitu stawki; wysyłamy w rozsądnych, rynkowych stawkach.",
    ),
}

INT_FIELDS = (
    "sla_business_days",
    "sla_min_candidates",
    "cv_limit_per_process",
    "hold_hours",
    "multi_project_cooldown_days",
)

SENSITIVE_RE = re.compile(
    r"(ze wschodu|wschód\s*[–-]|krajów objętych|pochodzących z innych krajów"
    r"|preferowani polacy|nie są mile widziani)",
    re.I,
)
PRIORITY_RE = re.compile(
    r"(w pierwszej kolejności|priorytetowo|preferowani kandydaci"
    r"|must-have to doświadczenie|kredytem zaufania)",
    re.I,
)
RATE_RE = re.compile(r"(stawk|budżet)", re.I)
ONBOARDING_RE = re.compile(
    r"(sprzęt|adresy biur|^biura\b|delegacj|rozliczenia|^ts\b|ts musi|ts jest|keś"
    r"|umow[aęy]|dokument|pesel|\bnip\b|compliance|onboarding|oświadczeni|oswiadczeni"
    r"|\bkrk\b|\bnda\b|praca spoza|godzinach biurowych|wyłączność|współpraca na lata"
    r"|vpn|faktur|odbiór z biura|akceptacja kandydata|po akceptacji"
    r"|^(gdańsk|warszawa|kraków|katowice|wrocław|poznań|lublin)\b)",
    re.I,
)
URL_RE = re.compile(r"https?://\S+")


def _lines(items: list) -> list:
    out = []
    for item in items:
        out.extend(str(item).split("\n"))
    return out


def bullets(lines: list) -> str:
    out = []
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            continue
        if re.match(r"^\s*[-•]\s+", s):
            out.append("  - " + re.sub(r"^\s*[-•]\s+", "", s).strip())
        else:
            out.append("- " + s.strip())
    return "\n".join(out)


def parse_documents(lines: list):
    docs, rest = [], []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = URL_RE.search(s)
        if not m:
            rest.append(s)
            continue
        url = m.group(0).rstrip(".,;)")
        name = URL_RE.sub("", s)
        name = re.sub(r"^\d+[.)]\s*", "", name)
        name = re.sub(r"\s*(->|→|–|-|:)\s*$", "", name).strip(" -–:>")
        docs.append({"name": (name or "Dokument")[:255], "url": url[:2000]})
    return docs, rest


def _assert_complete(
    key: str, entry: dict, text_lines: list, doc_lines: list, dropped: set
) -> None:
    """Każda niepusta linia źródłowa musi być w karcie — inaczej seed gubi treść wzoru (D11).

    Linie ze „standardy" i „o kliencie" trafiają do pól tekstowych 1:1 (podciąg po
    `strip()`). Linie z „dokumenty" z URL-em stają się wpisami `documents`, więc
    sprawdzamy sam URL; bez URL-a lądują w onboarding_md jako tekst.
    """
    haystack = "\n".join(
        str(entry.get(field) or "")
        for field in (
            "about_for_candidate",
            "priority_rules",
            "process_rules_md",
            "onboarding_md",
        )
    )
    doc_urls = {doc["url"] for doc in entry["documents"]}
    missing = []
    for ln in text_lines:
        s = ln.strip()
        if s and s not in dropped and s not in haystack:
            missing.append(s)
    for ln in doc_lines:
        s = ln.strip()
        if not s:
            continue
        m = URL_RE.search(s)
        if m:
            if m.group(0).rstrip(".,;)")[:2000] not in doc_urls:
                missing.append(s)
        elif s not in haystack:
            missing.append(s)
    if missing:
        raise SystemExit(f"[{key}] linie źródłowe nie trafiły do karty: {missing}")


def convert(drop_sensitive: bool) -> list:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    out, dropped = [], []
    for key, data in src.items():
        meta = META[key]
        process, onboarding, priority = [], [], []
        std_lines = _lines(data.get("standardy", []))
        for ln in std_lines:
            s = ln.strip()
            if not s:
                continue
            if drop_sensitive and SENSITIVE_RE.search(s):
                dropped.append((key, s))
                continue
            if PRIORITY_RE.search(s):
                priority.append(s)
            elif RATE_RE.search(s):
                process.append(s)
            elif ONBOARDING_RE.search(s):
                onboarding.append(s)
            else:
                process.append(s)
        doc_lines = _lines(data.get("dokumenty", []))
        docs, doc_rest = parse_documents(doc_lines)
        onboarding_md = bullets(onboarding)
        if doc_rest:
            onboarding_md = (onboarding_md + "\n\n" if onboarding_md else "") + (
                "**Dokumenty wymagane od konsultanta**\n" + bullets(doc_rest)
            )
        entry = {"seed_key": meta["seed_key"], "name_pattern": meta["name_pattern"]}
        for field in INT_FIELDS:
            entry[field] = meta.get(field)
        entry.update(
            {
                "rate_policy": meta.get("rate_policy"),
                "about_for_candidate": "\n".join(data.get("o_kliencie", [])).strip()
                or None,
                "priority_rules": "\n".join(priority) or None,
                "process_rules_md": bullets(process) or None,
                "onboarding_md": onboarding_md or None,
                "documents": docs,
            }
        )
        _assert_complete(
            key,
            entry,
            std_lines + _lines(data.get("o_kliencie", [])),
            doc_lines,
            {s for k, s in dropped if k == key},
        )
        out.append(entry)
    for key, s in dropped:
        print(f"POMINIĘTO [{key}]: {s}", file=sys.stderr)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drop-sensitive", action="store_true")
    args = parser.parse_args()
    entries = convert(args.drop_sensitive)
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"zapisano {len(entries)} kart → {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
