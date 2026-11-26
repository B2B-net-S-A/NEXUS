"""Zestaw danych Poligonu NEXUSA z nagranych odpowiedzi API.

Poligon (onboarding rekruterów, decyzja Artura z 14.11.2026) pokazuje prawdziwe
ekrany NEXUSA na rekrutacji ćwiczebnej. Front podaje im odpowiedzi z pliku
`frontend/src/lib/poligon/dataset.json`; ten skrypt go buduje.

Wejście to katalog nagrania (`log.json` + ciała odpowiedzi `0000.json`…),
zrobionego na stagingu z laptopa kontem rekrutera: lista rekrutacji,
Tablica jednej rekrutacji i panel jednej osoby. Od 15.11.2026 (ścieżka Delivery
Leada) nagranie ma też fazy `dl-review*` z konta Delivery Leada: przegląd
jednej osoby z kolumny „QC CV” innej rekrutacji (`--dl-*`). Jej odpowiedzi
trafiają pod osobę-szablon rekrutacji ćwiczebnej, a kwoty, wymagania i ocena
w kontekście przeglądu są wymyślone (`DL_CONTEXT`). Nagranie zawiera prawdziwe
dane, więc zostaje lokalnie i NIGDY nie trafia do repo.

Zasada bezpieczeństwa (repo jest publiczne): każdy tekst, którego nie ma
w `frontend/src/lib/poligon/vocab.json` ani w słowniku osób ćwiczebnych poniżej,
znika. Wyjątki: krótkie kody (`screening`, `hybrid`) i daty, które zamieniamy
na względne (`@rel:-3.2` = 3,2 dnia temu). Identyfikatory przechodzą na zakres
poligonu (990000+). Test `poligon-dataset.test.ts` sprawdza to samo po stronie
frontu, więc nowy tekst w zestawie bez wpisu w słowniku zatrzyma CI.

Użycie (z `backend/`):
    python3 scripts/build_poligon_dataset.py <katalog-nagrania> --job <id> \
        --client <id> --candidate <id> \
        [--dl-job <id> --dl-client <id> --dl-candidate <id> --dl-stage <id>] [--report]

Nagranie robi skrypt Playwrighta ze scratchpadu sesji (logowanie
`python -m scripts.staging_login_as --user-id …`, zapis każdej odpowiedzi API
z portu 8100 z polem `phase`); opis kroków w `docs/claude/ui/poligon-nexusa-onboarding.md`.

Klient ćwiczebny (karta klienta, kontrakty, zamówienia z maila, Finanse; 22.11.2026)
jest wymyślony w `scripts/poligon_client_practice.py`, a odczyty CV z dwóch
wpisów Nowości (lata w punkcie 1, gotowe CV z nową zgodą) w
`scripts/poligon_cv_practice.py`, a stop do podpisu przedwstępnej (lekcje
Nowości z 23.11.2026) w `scripts/poligon_pre_contract_practice.py`. Języki
i wcześniejsze odpowiedzi osoby-szablonu (ekran wstawia je w zdanie, a filtr
zostawiał `null`) są w `scripts/poligon_person_texts.py`. Bez nagrania:
    python3 scripts/build_poligon_dataset.py --practice-only
nakłada wymyślone odczyty (nowości z porcji i klienta ćwiczebnego) na zestaw,
który już jest w repo.

`--report` wypisuje teksty, które zniknęły, pogrupowane po kluczu — z tej listy
dopisuje się do `vocab.json` etykiety interfejsu (nigdy osoby, firmy, notatki).
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

try:
    from scripts.poligon_client_practice import CLIENT_PEOPLE, client_practice
    from scripts.poligon_cv_practice import READY_CV_PERSON, cv_practice
    from scripts.poligon_person_texts import person_texts
    from scripts.poligon_pre_contract_practice import pre_contract_practice
    from scripts.poligon_terms_practice import PERSON as TERMS_CARD, terms_practice
    from scripts.poligon_board_tasks_practice import board_tasks_practice
    from scripts.poligon_payments_practice import payments_practice
    from scripts.poligon_review_batch_practice import review_batch_practice
except (
    ModuleNotFoundError
):  # wywołanie z `backend/`: python3 scripts/build_poligon_dataset.py
    from poligon_client_practice import CLIENT_PEOPLE, client_practice
    from poligon_cv_practice import READY_CV_PERSON, cv_practice
    from poligon_person_texts import person_texts
    from poligon_pre_contract_practice import pre_contract_practice
    from poligon_terms_practice import PERSON as TERMS_CARD, terms_practice
    from poligon_board_tasks_practice import board_tasks_practice
    from poligon_payments_practice import payments_practice
    from poligon_review_batch_practice import review_batch_practice

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend/src/lib/poligon/dataset.json"
# Mały wyciąg dla powłoki aplikacji (osoby ćwiczebne), żeby nie ładować całego zestawu.
META_OUT = ROOT / "frontend/src/lib/poligon/meta.json"
SAFE_KEYS_FILE = ROOT / "frontend/src/lib/poligon/safe-keys.json"

POLIGON_JOB = 990001
POLIGON_CLIENT = 990501
FIRST_CANDIDATE = 990101
FIRST_ENTRY = 990301
FIRST_OTHER = 991001
TRAINERS = {"dl": (990901, "Anna Poligonowa"), "rec": (990902, "Jakub Szkoleniowy")}

JOB_TITLE = "Senior Project Manager (bankowość)"
CLIENT_NAME = "Bank Północny"
JOB_REFERENCE = "ĆW-01"

# Osoby ćwiczebne: imię i nazwisko w zgodnym rodzaju, wymyślone.
PEOPLE = [
    ("Zofia", "Jodłowska"),
    ("Tomasz", "Leszczyński"),
    ("Natalia", "Topolska"),
    ("Igor", "Sosnowski"),
    ("Helena", "Wrzosek"),
    ("Bartosz", "Brzozowski"),
    ("Aleksandra", "Kalinowska"),
    ("Jakub", "Jaworek"),
    ("Weronika", "Cisowska"),
    ("Szymon", "Grabowiec"),
    ("Laura", "Olszyńska"),
    ("Filip", "Bukowiec"),
    ("Maja", "Wierzbicka"),
    ("Oskar", "Modrzewski"),
]

# Osoby ćwiczeń z 16.11.2026 spoza bazy i Tablicy z nagrania: na karcie
# „Rozmowa u klienta” czeka na wybór terminu (`SLOT_PERSON`), a osobę
# z pliku CV NEXUS „odczytuje” dopiero w ćwiczeniu (`CV_PERSON`).
SLOT_PERSON = ("Kamil", "Dębowski")
CV_PERSON = ("Ewa", "Jesionowska")
# Osoba w „CV wysłane” do lekcji „Terminy przy ruchu” (`poligon_terms_practice.py`).
TERMS_PERSON = ("Marta", "Jarzębska")
EXTRA_PEOPLE = [SLOT_PERSON, CV_PERSON, TERMS_PERSON]
ALL_PEOPLE = PEOPLE + EXTRA_PEOPLE

FICTIONAL_NAMES = (
    {n for pair in ALL_PEOPLE for n in pair}
    | {f"{a} {b}" for a, b in ALL_PEOPLE}
    | {t[1] for t in TRAINERS.values()}
    | {JOB_TITLE, CLIENT_NAME, JOB_REFERENCE}
)

# Ile kart zostaje w kolumnie Tablicy (po kodzie etapu); reszta kolumn pusta.
# „QC CV” (`interview`) dostaje karty z „CV wysłane” nagranej rekrutacji
# (QC zdane) — na nich Delivery Lead ćwiczy przegląd i wysyłkę.
CARDS_PER_STAGE = {"new": 4, "screening": 3, "verified": 2, "interview": 2}
QC_STAGE = "interview"
QC_SOURCE_STAGE = "cv_sent"
# Karta czeka na przegląd DL-a, więc nie ma jeszcze stawki do klienta.
QC_CARD_RESET = {
    "client_rate_value": None,
    "client_rate_unit": None,
    "client_rate_currency": None,
    "next_action_owner": "recruiter",
    "followup": None,
}

# Fazy nagrania z konta Delivery Leada, które dokładamy do zestawu (przegląd
# osoby z „QC CV”). Odpowiedź pod adresem, który ma już nagranie rekrutera,
# zostaje z nagrania rekrutera — Tablica i panel osoby są wspólne.
DL_PHASES = {"dl-review", "dl-review-return", "dl-review-reject"}
# Z Tablicy DL-a bierzemy tylko odczyty nagłówka, które widzi Delivery Lead
# (gotowość do przekazania, „Klient milczy”, rekrutacja bez ruchu).
DL_BOARD_PATHS = re.compile(r"^/api/(jobs/\d+/(readiness|idle)|client-wait/jobs/\d+)$")
# Dogranie z 16.11.2026 (`rec4`: terminy u klienta, edytor CV, czat, zapisane
# wyszukiwania, listy, CV z pliku): tylko dokłada adresy, których nie ma —
# Tablica i panel osoby zostają z pierwszego nagrania.
ADD_ONLY_PHASES = {
    "login4",
    "slot-board",
    "slot-pick",
    "cv-board",
    "cv-dock",
    "cv-editor",
    "cv-editor-assistant",
    "cv-editor-api",
    "chat",
    "saved-searches",
    "profile-lists",
    "add-from-cv",
}

# Kwoty w zestawie są wymyślone: repo jest publiczne, a stawki osób i marże
# klientów to tajemnica firmy. Liczby pasują do treści ćwiczeń: kandydat
# 105 zł/h, budżet rekrutacji do 115 zł/h (`lib/poligon/exercises.ts`).
POLIGON_CANDIDATE_HOURLY = 105.0
POLIGON_BUDGET_MAX_HOURLY = 115.0
MONEY_KEY = re.compile(
    r"(^|_)(rate|rates|budget|margin|cost|revenue|salary|fee|amount|price|hourly)(_|$)"
)
NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")
NOT_MONEY_KEY = re.compile(r"(count|version|_usd)$")


def money_value(key: str) -> float:
    k = key.lower()
    if "budget" in k:
        return 95.0 if "min" in k else POLIGON_BUDGET_MAX_HOURLY
    if "margin" in k:
        return 18.0
    if "fee" in k:
        return 20.0
    if "client" in k or "revenue" in k:
        return 122.0
    if "from" in k:
        return 100.0
    return POLIGON_CANDIDATE_HOURLY


# Treść CV i notatek osoby z nagrania zastępujemy CV ćwiczebnym, bo nawet bez
# nazwiska opis kariery i lista firm wskazują konkretnego człowieka.
CV_FICTION = {
    "role": "Senior Project Manager",
    "current_role": "Senior Project Manager w Firmie Przykładowej",
    "current_position": "Senior Project Manager w Firmie Przykładowej",
    "description": "Prowadzenie programu migracji systemów płatności w banku: harmonogram, ryzyka, budżet i koordynacja czterech zespołów.",
    "desc": "Prowadzenie programu migracji systemów płatności w banku: harmonogram, ryzyka, budżet i koordynacja czterech zespołów.",
    "companies": "Firma Przykładowa S.A.",
    "company_norm": "firma przykładowa",
    "achievements": "Wdrożenie nowej platformy płatności w terminie i w budżecie.",
    "evidence": "Opisała prowadzenie programu migracji płatności z czterema zespołami i dostawcą zewnętrznym.",
    "issuer": "PMI",
    "certifications": "PMP (aktywny)",
    "degree": "Magister zarządzania",
    "school": "Uczelnia Przykładowa",
    "field": "Zarządzanie projektami",
    "profile": "Project Manager z 9 latami doświadczenia w bankowości: migracje systemów płatności, praca z dostawcami i komitetem sterującym.",
    "professional_profile": "Project Manager z 9 latami doświadczenia w bankowości: migracje systemów płatności, praca z dostawcami i komitetem sterującym.",
    "ai_summary": "Project Manager z 9 latami doświadczenia w bankowości: migracje systemów płatności, praca z dostawcami i komitetem sterującym.",
    "career_summary": "Osoba ćwiczebna: 9 lat w zarządzaniu projektami IT w bankowości.",
    "matching_facts": "Prowadziła program w regulowanej branży i samodzielnie przygotowywała raporty dla komitetu sterującego.",
    "bullets": "Sektory: bankowość, płatności",
    "notes": "Rozmowa telefoniczna: zainteresowana projektem, dostępna od przyszłego miesiąca.",
    "content": "Rozmowa telefoniczna: zainteresowana projektem, dostępna od przyszłego miesiąca.",
    "content_rendered": "Rozmowa telefoniczna: zainteresowana projektem, dostępna od przyszłego miesiąca.",
    "notice_period": "1 miesiąc",
    "available_from": "Od pierwszego dnia przyszłego miesiąca",
    "rate_flexibility": "Do rozmowy przy dłuższym projekcie.",
    "added_via": "Import z ogłoszenia",
}

# „Moi ludzie” poligonu: osoby ćwiczebne spoza Tablicy (ostatnie z `PEOPLE`),
# żeby ćwiczenie nie pokazywało prawdziwych ludzi z konta, które nagrywało.
MY_PEOPLE_PATHS = {
    "/api/my-people",
    "/api/my-people/summary",
    "/api/talent-pools",
    "/api/me/career-link/people",
}
MY_PEOPLE_COUNT = 4

# Hasło listy bez nazwy (np. słowniczek technologii) wypada z listy.
NAMED_ITEM_KEYS = ("display_name", "term")

# Teksty, które API zawsze oddaje jako napis (`schemas/champion.py`: `about: str = ""`),
# a ekran woła na nich `.trim()`. Wycięte zostają puste, nie `null`: 25.11.2026
# „Edytuj” Profilu Championa na Poligonie kończyło się „Coś poszło nie tak”
# i lekcja „Najważniejsze zadanie w tej roli” była nie do zrobienia.
EMPTY_TEXT_KEYS = frozenset(
    {"name", "title", "label", "about", "responsibilities", "deal_breaker"}
)


def blank_empty_texts(value):
    """`null` pod kluczem z `EMPTY_TEXT_KEYS` → `""` w całym odczycie (kopia)."""
    if isinstance(value, dict):
        return {
            k: "" if v is None and k in EMPTY_TEXT_KEYS else blank_empty_texts(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [blank_empty_texts(v) for v in value]
    return value


# Teksty, których ekran wymaga (nie znosi `null`), a filtr prawdziwych nazw
# je wyciął — np. pytanie screeningowe z nazwą klienta.
REQUIRED_TEXT = {
    "question": "Jak wyglądał największy program, który prowadziłeś/aś w bankowości — zakres, zespół i budżet?",
    "ideal_answer": "Konkretny program z liczbami: wielkość zespołu, budżet, czas trwania i własna rola.",
    # Dosłowny cytat z notatki (fakt z rozmowy) — ekran pokazuje go pod wartością.
    "raw": "z rozmowy telefonicznej",
}

# Kody etapów („new”, „screening”) to słownik systemu, nie tekst o osobie —
# filtr prawdziwych nazw (np. firma „New…” z bazy) nie może ich zdejmować.
STAGE_CODE_KEYS = {
    "stage",
    "column",
    "board_column",
    "from_column",
    "to_column",
    "from_stage",
    "to_stage",
}
ENUM = re.compile(r"^[a-z0-9_\-:.]{1,60}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:\d{2})?)?$")
DIGITS = re.compile(r"^\d{4,}$")
# Odciski, tokeny i podpisy z nagrania (np. `state_token` formularza screeningu):
# stała wartość, bo prawdziwy odcisk jest śladem stanu prawdziwej osoby,
# a Gitleaks słusznie bierze go za sekret.
SECRET_LIKE_KEYS = re.compile(
    r"(token|hash|fingerprint|sha\d*|signature|secret|password)", re.I
)
POLIGON_TOKEN = "poligon"

# Słowa z nazw firm i stanowisk, które nie wskazują nikogo.
COMMON_WORDS = {
    "bank",
    "poland",
    "polska",
    "group",
    "senior",
    "project",
    "manager",
    "program",
    "system",
    "import",
    "sales",
    "expert",
    "the",
    "and",
    "for",
    "services",
    "technology",
    "technologies",
    "digital",
    "nowy",
    "nowi",
    "screening",
    "inne",
    "brak",
    "rekrutacja",
    "rekrutacje",
    "junior",
    "business",
    "claude",
    "jjit",
    "nexus",
    "area",
    "data",
    "cloud",
    "solutions",
    "consulting",
    "software",
}

LEARN_KEYS = {
    "full_name",
    "recruiter_name",
    "taken_by_name",
    "verified_by_name",
    "added_to_job_by_name",
    "moved_by_name",
    "owner_name",
    "author_name",
    "delivery_lead_name",
    "hiring_manager_name",
    "caller_name",
    "p0_set_by_name",
    "last_author_name",
    "substitute_name",
    "actor_name",
    "assigned_by_name",
    "candidate_name",
    "uploaded_by_name",
    "closed_by_name",
    "claim_user_name",
    "person",
    "first_name",
    "last_name",
    "lastname",
    "client_name",
    "company",
    "companies",
    "client",
    "recruiters",
    "school",
}

PERSON_NAME_KEYS = re.compile(
    r"(^|_)(name|author_name|recruiter_name|taken_by_name|verified_by_name|added_to_job_by_name|"
    r"moved_by_name|owner_name|claim_user_name|candidate_added_by_name|closed_by_name|"
    r"delivery_lead_name|actor_name|caller_name|uploaded_by_name|added_by_name|"
    r"assigned_by_name|p0_set_by_name|last_author_name|substitute_name|full_name|person|who)$"
)
JOB_TITLE_KEYS = {
    "title",
    "working_title",
    "job_title",
    "role_name",
    "job_working_title",
    "cv_position",
}
CLIENT_KEYS = {"client_name", "company", "client"}
DROP_KEYS = {
    "email",
    "candidate_email",
    "phone",
    "candidate_phone",
    "url",
    "online_meeting_url",
    "link",
    "download_url",
    "filename",
    "cv_filename",
    "original_cv_filename",
}


class Builder:
    def __init__(self, job: int, client: int, candidate: int, captured_at: datetime):
        self.captured_at = captured_at
        self.ids: dict[int, int] = {job: POLIGON_JOB, client: POLIGON_CLIENT}
        self.template_candidate = candidate
        self.next_other = FIRST_OTHER
        self.safe_keys = set(json.loads(SAFE_KEYS_FILE.read_text()))
        # Nazwy programów i projektów klienta z nagrania, których nie ma w polach osób ani firm.
        self.real_tokens: set[str] = {"amla"}
        self.dropped: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        self.person_names: dict[str, str] = {}
        self.client_ids = {client}

    # --- identyfikatory --------------------------------------------------
    def remap_id(self, value: int) -> int:
        if value in self.ids:
            return self.ids[value]
        self.ids[value] = self.next_other
        self.next_other += 1
        return self.ids[value]

    def is_id_key(self, key: str) -> bool:
        return (
            key == "id"
            or key.endswith("_id")
            or key.endswith("_ids")
            or key
            in {"moved_by", "created_by", "approved_by", "rejected_by", "ended_by"}
        )

    # --- teksty ----------------------------------------------------------
    def rel(self, value: str) -> str:
        if len(value) == 10:
            d = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            return f"@reld:{round((d - self.captured_at).total_seconds() / 86400)}"
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return f"@rel:{round((d - self.captured_at).total_seconds() / 86400, 3)}"

    def fake_person(self, real: str) -> str:
        if real not in self.person_names:
            self.person_names[real] = TRAINERS[
                "rec" if len(self.person_names) % 2 else "dl"
            ][1]
        return self.person_names[real]

    def text(self, key: str, value: str) -> str | None:
        if not value:
            return value
        if SECRET_LIKE_KEYS.search(key):
            return POLIGON_TOKEN
        if DATE.match(value):
            return self.rel(value)
        if DIGITS.match(value) and int(value) in self.ids:
            return str(self.ids[int(value)])
        if key in DROP_KEYS or "@" in value or value.startswith("http"):
            return None
        if key in JOB_TITLE_KEYS:
            return JOB_TITLE
        if key in CLIENT_KEYS:
            return CLIENT_NAME
        if key in {"reference_number", "client_reference"}:
            return JOB_REFERENCE
        if ENUM.match(value) and (
            key in STAGE_CODE_KEYS or not self.mentions_real(value)
        ):
            return value
        if key in CV_FICTION:
            return CV_FICTION[key]
        if value in FICTIONAL_NAMES:
            return value
        if key in {"technologies", "skill"}:
            # Umiejętności z CV osoby z nagrania: stały, wymyślony zestaw.
            return FICTION_SKILLS[sum(map(ord, value)) % len(FICTION_SKILLS)]
        if (
            PERSON_NAME_KEYS.search(key)
            and self.mentions_real(value)
            and re.match(
                r"^[A-ZŁŚŻŹĆÓ][a-ząćęłńóśźż]+(\s+[A-ZŁŚŻŹĆÓ][a-ząćęłńóśźż-]+)+$",
                value.strip(),
            )
        ):
            return self.fake_person(value.strip())
        if key in self.safe_keys or ENUM.match(value):
            if self.mentions_real(value):
                self.dropped["(prawdziwa nazwa) " + key][value[:80]] += 1
                if key in REQUIRED_TEXT:
                    return REQUIRED_TEXT[key]
                return "" if key in EMPTY_TEXT_KEYS else None
            return value
        if PERSON_NAME_KEYS.search(key) and re.match(
            r"^[A-ZŁŚŻŹĆÓ][a-ząćęłńóśźż]+(\s+[A-ZŁŚŻŹĆÓ][a-ząćęłńóśźż-]+)+$",
            value.strip(),
        ):
            return self.fake_person(value.strip())
        self.dropped[key][value[:80]] += 1
        if key in REQUIRED_TEXT:
            return REQUIRED_TEXT[key]
        return "" if key in EMPTY_TEXT_KEYS else None

    def mentions_real(self, value: str) -> bool:
        words = set(re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}", value.lower()))
        return bool(words & self.real_tokens)

    def learn_real_names(self, value, key: str = "") -> None:
        """Zbiera imiona, nazwiska i nazwy firm z nagrania — filtr dla tekstów ze `safe-keys`."""
        if isinstance(value, dict):
            # Osoba: para imię + nazwisko albo konto z adresem e-mail.
            if isinstance(value.get("name"), str) and (
                "lastname" in value or "email" in value
            ):
                self.learn_tokens(f"{value['name']} {value.get('lastname') or ''}")
            for k, v in value.items():
                self.learn_real_names(v, k)
        elif isinstance(value, list):
            for v in value:
                self.learn_real_names(v, key)
        elif isinstance(value, str) and key in LEARN_KEYS:
            self.learn_tokens(value)

    def learn_tokens(self, value: str) -> None:
        for w in re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}", value):
            if w[0].isupper() and w.lower() not in COMMON_WORDS:
                self.real_tokens.add(w.lower())

    # --- przejście po drzewie --------------------------------------------
    def clean(self, value, key: str = ""):
        if isinstance(value, dict):
            # Słowniki kluczowane identyfikatorem (np. wyniki dopasowania per osoba).
            return {
                (
                    str(self.remap_id(int(k))) if k.isdigit() and int(k) >= 1000 else k
                ): self.clean(v, k)
                for k, v in value.items()
            }
        if isinstance(value, list):
            if key.endswith("_ids") and all(isinstance(x, int) for x in value):
                return [
                    self.remap_id(x) if x >= 1000 or key == "client_ids" else x
                    for x in value
                ]
            return [self.clean(v, key) for v in value]
        if isinstance(value, bool) or value is None:
            return value
        if (
            isinstance(value, (int, float, str))
            and MONEY_KEY.search(key)
            and not NOT_MONEY_KEY.search(key)
            and not self.is_id_key(key)
            and NUMERIC.match(str(value))
        ):
            fake = money_value(key)
            return f"{fake:.2f}" if isinstance(value, str) else fake
        if isinstance(value, int):
            if self.is_id_key(key) and (
                value >= 1000 or (key == "client_id" and value in self.client_ids)
            ):
                return self.remap_id(value)
            return value
        if isinstance(value, float):
            return value
        if isinstance(value, str):
            return self.text(key, value)
        return None

    def clean_url(self, path: str, query: str) -> str:
        def sub_path(m: re.Match) -> str:
            n = int(m.group(1))
            return "/" + str(
                self.remap_id(n) if n >= 1000 or n in self.client_ids else n
            )

        p = re.sub(r"/(\d+)", sub_path, path)
        q = []
        for k, v in parse_qsl(query.lstrip("?"), keep_blank_values=True):
            if re.fullmatch(r"\d+", v) and (
                int(v) >= 1000 or (k == "client_id" and int(v) in self.client_ids)
            ):
                v = str(self.remap_id(int(v)))
            elif DATE.match(v):
                continue  # daty w zapytaniu (np. `overdue_to`) liczy front na bieżąco
            elif k == "user_ids":
                continue
            q.append((k, v))
        q.sort()
        return p + ("?" + urlencode(q) if q else "")


def with_qc_cards(data: dict) -> dict:
    """Kolumna „QC CV” z kartami gotowymi do przeglądu DL-a (QC zdane)."""
    columns = data["columns"]
    qc = next((c for c in columns if c.get("stage") == QC_STAGE), None)
    sent = next((c for c in columns if c.get("stage") == QC_SOURCE_STAGE), None)
    if qc is None or sent is None:
        return data
    ready = [
        {
            **item,
            **QC_CARD_RESET,
            "stage": qc["stage"],
            "stage_def_id": qc["stage_def_id"],
        }
        for item in sent.get("items", [])
        if (item.get("qc") or {}).get("status") == "passed"
    ]
    out = [
        {**c, "items": ready + list(c.get("items", []))} if c is qc else c
        for c in columns
    ]
    return {**data, "columns": out}


# „Rozmowa u klienta” (ćwiczenie „Wybierz termin z kandydatem”, 16.11.2026).
# Kształt odznaki i podpowiedzi prepów pochodzi z nagrania (`slot-*`), treść
# jest wymyślona: prawdziwe odpowiedzi mają nazwiska organizatorów prepów,
# a godziny przesunięte o chwilę nagrania wyglądałyby jak „13:27”. Daty
# `@relt:<dni>T<HH:MM>` = za tyle dni roboczych o pełnej godzinie (UTC).
CLIENT_INTERVIEW_STAGE = "client_interview"
SLOT_REQUEST_ID = 990701


def slot_badge() -> dict:
    slots = [("2T09:00", "2T10:00"), ("3T13:00", "3T14:00"), ("5T08:00", "5T09:00")]
    respond_by = "@relt:1T15:00"
    steps = ["slots", "choice", "prep", "prep2", "interview", "call", "debrief"]
    return {
        "kind": "choose_slot",
        "label": "Wybierz termin · 3 propozycje",
        "tone": "wait",
        "at": respond_by,
        "steps": [
            {
                "key": k,
                "state": "done"
                if k == "slots"
                else "current"
                if k == "choice"
                else "todo",
                "at": respond_by if k == "choice" else None,
                "event_id": None,
            }
            for k in steps
        ],
        "interview_event_id": None,
        "tentative_interview_at": f"@relt:{slots[0][0]}",
        "late_prep_event_id": None,
        "slot_request": {
            "id": SLOT_REQUEST_ID,
            "status": "awaiting_recruiter",
            "expired": False,
            "slots": [{"start": f"@relt:{a}", "end": f"@relt:{z}"} for a, z in slots],
            "chosen_index": None,
            "respond_by": respond_by,
            "recruiter_id": TRAINERS["rec"][0],
            "created_by": TRAINERS["dl"][0],
            "duration_minutes": 60,
            "note": None,
            "event_id": None,
        },
        "preps": [],
        "debrief": None,
        "prep2_skip_status": "not_needed",
        "prep2_skip": None,
        "prep1_remaining": [],
        "phase": "awaiting_recruiter_pick",
        "interview_date": None,
    }


def prep_suggestions() -> dict:
    """Podpowiedzi godzin prepów do okna wyboru terminu (prepy w Teams wyłączone)."""

    def prep(no: int, organizer: str, times: list[str]) -> dict:
        uid, name = TRAINERS[organizer]
        return {
            "prep_no": no,
            "organizer": {"id": uid, "name": name},
            "calendar": "off",
            "scheduled_start": None,
            "minutes": 45,
            "options": [
                {"start": f"@relt:{t}", "end": f"@relt:{t[:-2]}45"} for t in times
            ],
            "busy": [],
        }

    return {
        "enabled": False,
        "preps": [
            prep(1, "dl", ["1T07:00", "1T08:00", "1T09:00"]),
            prep(2, "rec", ["2T07:00", "1T15:00", "1T16:00"]),
        ],
    }


def with_slot_card(data: dict) -> dict:
    """Kolumna „Rozmowa u klienta”: jedna osoba czeka na wybór terminu z kandydatem."""
    columns = data["columns"]
    target = next(
        (c for c in columns if c.get("stage") == CLIENT_INTERVIEW_STAGE), None
    )
    template = next(
        (i for c in columns if c.get("stage") == QC_STAGE for i in c.get("items", [])),
        None,
    )
    if target is None or template is None:
        return data
    i = len(PEOPLE) + EXTRA_PEOPLE.index(SLOT_PERSON)
    first, last = SLOT_PERSON
    card = {
        **copy.deepcopy(template),
        "id": FIRST_ENTRY + i,
        "candidate_id": FIRST_CANDIDATE + i,
        "name": first,
        "lastname": last,
        "stage": target["stage"],
        "stage_def_id": target["stage_def_id"],
        "interview_badge": slot_badge(),
        "next_action_owner": "recruiter",
        "followup": None,
    }
    out = [{**c, "items": [card], "count": 1} if c is target else c for c in columns]
    return {**data, "columns": out}


# Edytor CV (ćwiczenie „Popraw CV poleceniem AI”): CV firmowe osoby-szablonu
# jest szkicem. Treść CV ćwiczebnego dokłada front (`lib/poligon/cv-fiction.ts`),
# bo zestaw nie przyjmuje tekstu spoza słownika.
BRANDED_DRAFT = {
    "status": "draft",
    "content_html": None,
    "edit_revision": 3,
    "version": 1,
    "template": "standard",
    "language": "pl",
    "from_generator": True,
    "source": "generator",
}


def shape_kanban(b: Builder, data: dict) -> dict:
    """Mała Tablica: kilka kart w pierwszych kolumnach, osoby ćwiczebne."""
    data = with_qc_cards(data)
    people = iter(enumerate(PEOPLE))
    columns = []
    for col in data["columns"]:
        keep = CARDS_PER_STAGE.get(col.get("stage"), 0)
        items = []
        for item in col.get("items", [])[:keep]:
            i, (first, last) = next(people)
            b.ids[item["candidate_id"]] = FIRST_CANDIDATE + i
            b.ids[item["id"]] = FIRST_ENTRY + i
            item = dict(item)
            item["name"], item["lastname"] = first, last
            items.append(item)
        columns.append({**col, "items": items, "count": len(items)})
    return {**data, "columns": columns}


def add_slot_card(dataset: dict) -> None:
    """Karta na „Rozmowie u klienta” po oczyszczeniu Tablicy (identyfikatory już poligonu)."""
    key = f"GET /api/pipeline/kanban/{POLIGON_JOB}"
    if isinstance(dataset.get(key), dict):
        dataset[key] = with_slot_card(dataset[key])


def drop_stripped_words(value):
    """Słowa wymagań, które filtr nazw wyciął (`None`), znikają razem z wierszem.

    Wiersz `[None]` w `search.requirements` wywracał zakładkę Profil Championa
    na poligonie (`sanitizeKeyword` na `null`, 18.11.2026).
    """
    if isinstance(value, list):
        # Notatka albo podpowiedź bez treści (`text: None`) obok innych z treścią:
        # ekran woła `.trim()` na każdej (Brief Profilu Championa).
        if any(isinstance(v, dict) and isinstance(v.get("text"), str) for v in value):
            value = [
                v
                for v in value
                if not (isinstance(v, dict) and "text" in v and v["text"] is None)
            ]
        return [drop_stripped_words(v) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if (
            k == "requirements"
            and isinstance(v, list)
            and all(isinstance(r, list) for r in v)
        ):
            v = [[w for w in r if w is not None] for r in v]
            v = [r for r in v if r]
        elif k == "rows" and isinstance(v, list):
            v = [
                {**r, "words": [w for w in r["words"] if w is not None]}
                if isinstance(r, dict) and isinstance(r.get("words"), list)
                else r
                for r in v
            ]
            v = [r for r in v if not (isinstance(r, dict) and r.get("words") == [])]
        elif k == "all_of" and isinstance(v, list):
            v = [
                {**r, "any_of": [w for w in r["any_of"] if w is not None]}
                if isinstance(r, dict) and isinstance(r.get("any_of"), list)
                else r
                for r in v
            ]
            v = [r for r in v if not (isinstance(r, dict) and r.get("any_of") == [])]
        elif k in ("must", "nice") and isinstance(v, list):
            v = [
                r
                for r in v
                if not (isinstance(r, dict) and "name" in r and not r["name"])
            ]
        out[k] = drop_stripped_words(v)
    return out


# Nowości z porannej porcji przeklikiwane na poligonie (18.11.2026). Treść
# wymyślona: zmiana Profilu Championa, zespół z gotowymi składami i umowa
# do podpisu z NDA. Żaden z tych odczytów nie ma odpowiednika w nagraniu.
PRACTICE_TEAM_ID = 990601
PRACTICE_AGREEMENT_ID = 990801
PRACTICE_NDA_ID = 990811
# Osoby zespołu: dwie z „QC CV” i osoba z „Rozmowy u klienta” (indeksy `ALL_PEOPLE`).
TEAM_PEOPLE = [(8, "cv_sent"), (9, "cv_sent"), (14, CLIENT_INTERVIEW_STAGE)]


def champion_changes() -> dict:
    """„Co się zmieniło od przekazania”: jedna nieprzeczytana zmiana DL-a."""
    return {
        "job_id": POLIGON_JOB,
        "last_seen_revision_id": None,
        "revisions": [
            {
                "id": 990651,
                "created_at": "@rel:-0.2",
                "author_id": TRAINERS["dl"][0],
                "author_name": TRAINERS["dl"][1],
                "note": None,
                # Zgodne z Briefem rekrutacji ćwiczebnej (15 osób, te słowa w „Musi mieć”).
                "changes": [
                    {
                        "kind": "set",
                        "text": "Liczba osób",
                        "detail": "15 (wcześniej 10)",
                    },
                    {
                        "kind": "moved",
                        "text": "data sourcing",
                        "detail": "„Mile widziane” → „Musi mieć”",
                    },
                    {
                        "kind": "added",
                        "text": "escalations",
                        "detail": "nowe w „Musi mieć”",
                    },
                ],
                "mine": False,
            }
        ],
    }


def _team_candidate(index: int, stage: str, rate: float, sent_days_ago: float) -> dict:
    first, last = ALL_PEOPLE[index]
    money = {"value": rate, "unit": "hourly", "currency": "PLN"}
    return {
        "candidate_id": FIRST_CANDIDATE + index,
        "name": f"{first} {last}",
        "stage": stage,
        "sent_at": f"@rel:-{sent_days_ago}",
        "available_from": None,
        "client_rate": money,
        "expected_rate": {**money, "value": rate - 20},
    }


def practice_team() -> dict:
    """Zespół klienta z rekrutacją ćwiczebną: dwa miejsca, trzy wysłane osoby."""
    candidates = [
        _team_candidate(i, stage, rate, 2 + n)
        for n, ((i, stage), rate) in enumerate(zip(TEAM_PEOPLE, (125.0, 130.0, 120.0)))
    ]
    return {
        "id": PRACTICE_TEAM_ID,
        "name": "Zespół projektowy (ćwiczenie)",
        "client_id": POLIGON_CLIENT,
        "client_name": CLIENT_NAME,
        "hours_per_month": 168,
        "positions": [
            {
                "job_id": POLIGON_JOB,
                "title": JOB_TITLE,
                "headcount": 2,
                "closed": False,
                "budget_min": None,
                "budget_max": POLIGON_BUDGET_MAX_HOURLY,
                "delivery_lead": {"id": TRAINERS["dl"][0], "name": TRAINERS["dl"][1]},
                "candidates": candidates,
                "rate_hint": None,
            }
        ],
        "panel": {
            "enabled": False,
            "show_rate": False,
            "expires_at": None,
            "url": None,
            "short_url": None,
        },
        "selections": [],
        "variants": [],
        "variants_approved_at": None,
    }


def team_variants_proposal() -> dict:
    """„Zaproponuj składy”: trzy składy po dwie osoby (odczyt, nic nie zapisuje)."""
    ids = [FIRST_CANDIDATE + i for i, _ in TEAM_PEOPLE]
    variants = [
        ("fastest", "Najszybszy start", [ids[0], ids[1]], 255.0),
        ("cheapest", "Najniższa cena", [ids[0], ids[2]], 245.0),
        ("best_fit", "Najwięcej wymagań w CV", [ids[1], ids[2]], 250.0),
    ]
    return {
        "variants": [
            {
                "key": key,
                "name": name,
                "why": "",
                "picks": [{"job_id": POLIGON_JOB, "candidate_ids": picks}],
                "hourly_total": total,
                "start": None,
                "unknown_start": 2,
            }
            for key, name, picks, total in variants
        ]
    }


def practice_agreement_row() -> dict:
    """Umowa B2B osoby na „Rozmowie u klienta”, gotowa do wysyłki do podpisu."""
    i = len(PEOPLE) + EXTRA_PEOPLE.index(SLOT_PERSON)
    full = " ".join(SLOT_PERSON)
    return {
        "id": PRACTICE_AGREEMENT_ID,
        "contract_number": "cw-b2b-001",
        "partner_name": full,
        "partner_display_name": full,
        "partner_secondary_line": None,
        "partner_nip": None,
        "start_date": "@reld:14",
        "client_name": CLIENT_NAME,
        "language": "pl",
        "signing_date": None,
        "created_at": "@rel:-0.3",
        "created_by_name": TRAINERS["rec"][1],
        "created_by_role": "recruiter",
        "pair_column": CLIENT_INTERVIEW_STAGE,
        # Bez `signature_status` („unsigned”): strażnik zestawu nie przyjmuje
        # tekstu pod kluczem z „signature”, a brak = niepodpisana.
        "signature_source": None,
        "contract_status": "in_progress",
        "closure_reason": None,
        "closure_reason_other": None,
        "closure_date": None,
        "can_change_status": False,
        "candidate_id": FIRST_CANDIDATE + i,
        "job_id": POLIGON_JOB,
        "client_id": POLIGON_CLIENT,
        "contract_id": None,
        "candidate_name": full,
        "job_title": JOB_TITLE,
        "canonical_client_name": None,
        "signed_at": None,
        "signed_by_name": None,
        "can_confirm_signed": False,
        "blocked_reason": None,
        "esign": None,
        "can_send_esign": True,
        "can_delete": False,
        "can_edit": False,
        "can_download": False,
    }


def esign_defaults() -> dict:
    """Okno „Wyślij do podpisu”: podpisujący za firmę to trener, w paczce NDA klienta."""
    return {
        "contractor_name": " ".join(SLOT_PERSON),
        "contractor_email": None,
        "company_signers": [{"id": TRAINERS["dl"][0], "name": TRAINERS["dl"][1]}],
        # Na ćwiczeniach skrzynka jest „połączona”: 25.11.2026 osoby z połączoną
        # skrzynką czytały na Poligonie „Twoja skrzynka nie jest połączona”.
        "mailbox_connected": True,
        "cc_candidates": [],
        "documents": [{"id": PRACTICE_NDA_ID, "name": f"NDA {CLIENT_NAME}"}],
    }


def add_novelty_practice(dataset: dict) -> None:
    """Odczyty nowości z porannej porcji: zastępują puste odpowiedzi nagrania."""
    job = POLIGON_JOB
    dataset[f"GET /api/jobs/{job}/champion-profile/changes"] = champion_changes()
    dataset[f"GET /api/job-teams/{PRACTICE_TEAM_ID}"] = practice_team()
    dataset[f"GET /api/job-teams/{PRACTICE_TEAM_ID}/variants/proposal"] = (
        team_variants_proposal()
    )
    dataset[f"GET /api/b2b-generator/generated?job_id={job}&limit=50"] = [
        practice_agreement_row()
    ]
    dataset[
        f"GET /api/b2b-generator/generated/{PRACTICE_AGREEMENT_ID}/esign/defaults"
    ] = esign_defaults()


FICTION_SKILLS = [
    "Agile",
    "Scrum",
    "Jira",
    "Confluence",
    "MS Project",
    "Zarządzanie ryzykiem",
    "Budżetowanie",
    "Komitet sterujący",
    "SAFe",
    "Raportowanie zarządcze",
]


def with_names(items: list, names: list[str]) -> list:
    """Lista w kształcie oryginału (pierwszy element jako wzór), z wymyślonymi nazwami."""
    if not items or not isinstance(items[0], dict):
        return list(names)
    return [{**items[0], "name": n} for n in names]


def fictionalize_candidate(body: dict, first: str, last: str) -> dict:
    """Panel osoby: CV z nagrania zastępujemy CV ćwiczebnym (projekty, umiejętności, certyfikaty)."""
    body = dict(body)
    for k, v in (
        ("name", first),
        ("first_name", first),
        ("lastname", last),
        ("last_name", last),
        ("full_name", f"{first} {last}"),
    ):
        if k in body:
            body[k] = v
    if isinstance(body.get("skills"), list):
        body["skills"] = with_names(body["skills"], FICTION_SKILLS)
    if isinstance(body.get("talent_pools"), list):
        body["talent_pools"] = []
    cv = body.get("cv_extracted_data")
    if isinstance(cv, dict):
        cv = dict(cv)
        cv["projects"] = with_names(
            cv.get("projects") or [],
            ["Migracja systemu płatności", "Nowa bankowość mobilna"],
        )
        cv["skills"] = with_names(cv.get("skills") or [], FICTION_SKILLS)
        cv["certifications"] = with_names(cv.get("certifications") or [], ["PMP"])
        cv["languages"] = with_names(cv.get("languages") or [], ["Polish", "English"])
        cv.pop("_notes_insights", None)
        body["cv_extracted_data"] = cv
    if isinstance(body.get("candidate"), dict):
        body["candidate"] = fictionalize_candidate(body["candidate"], first, last)
    return body


# Stany z dnia nagrania, które na rekrutacji ćwiczebnej tylko by przeszkadzały.
CALM_JOB = {
    "p0_until": None,
    "p0_reason": None,
    "p0_set_at": None,
    "p0_set_by_name": None,
    "priority": "normal",
    # Kolejka Cpro (Nordea) zmienia przegląd DL-a w akceptację do Cpro —
    # rekrutacja ćwiczebna wysyła CV prosto do klienta.
    "cpro_enabled": False,
}


def shape_my_people(dataset: dict) -> None:
    """„Moi ludzie”: wiersze z nagrania (już oczyszczone) jako wzór kształtu,
    osoby — ćwiczebne. Pule i linki kariery puste, jak u nowej osoby."""
    mine = list(enumerate(PEOPLE))[-MY_PEOPLE_COUNT:]

    def rows(recorded: list) -> list:
        if not recorded:
            return []
        out = []
        for i, (first, last) in mine:
            row = copy.deepcopy(recorded[0])
            row.update(
                candidate_id=FIRST_CANDIDATE + i,
                full_name=f"{first} {last}",
                in_job=False,
            )
            out.append(row)
        return out

    for key, body in list(dataset.items()):
        path = key.split(" ", 1)[1].split("?", 1)[0]
        if path.startswith("/api/my-people/for-job/") or path == "/api/my-people":
            if isinstance(body, dict) and isinstance(body.get("rows"), list):
                dataset[key] = {**body, "rows": rows(body["rows"])}
                for count_key in ("total", "count"):
                    if isinstance(body.get(count_key), int):
                        dataset[key][count_key] = MY_PEOPLE_COUNT
        elif path == "/api/my-people/summary" and isinstance(body, dict):
            dataset[key] = {
                **zero_counts(body),
                "total": MY_PEOPLE_COUNT,
                "latest_matches": [],
                "idle_top": [],
            }
        elif path == "/api/talent-pools":
            dataset[key] = []
        elif path == "/api/me/career-link/people" and isinstance(body, dict):
            dataset[key] = {**body, "total": 0, "people": []}


def prune_dropped(value):
    """Pozycje list, z których filtr wyciął tekst: `null` między napisami
    i słowniki bez nazwy wypadają — ekran nie umie pokazać hasła bez nazwy."""
    if isinstance(value, dict):
        return {k: prune_dropped(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [prune_dropped(v) for v in value]
        if any(isinstance(v, str) for v in items):
            items = [v for v in items if v is not None]
        return [
            v
            for v in items
            if not (
                isinstance(v, dict)
                and any(k in v and v[k] is None for k in NAMED_ITEM_KEYS)
            )
        ]
    return value


def mentionable_users() -> list[dict]:
    """Lista do „@” na poligonie: trenerzy ćwiczebni, nie prawdziwy zespół."""
    roles = {"dl": "delivery_lead", "rec": "recruiter"}
    return [
        {
            "id": uid,
            # Bez domeny: „@anna.poligonowa” w notatce, żaden prawdziwy adres.
            "email": ".".join(name.lower().split()),
            "name": name,
            "role": roles[key],
            "roles": [roles[key]],
            "is_active": True,
        }
        for key, (uid, name) in TRAINERS.items()
    ]


def calm(value):
    if isinstance(value, dict):
        out = {k: calm(v) for k, v in value.items()}
        if out.get("id") == POLIGON_JOB:
            out.update({k: v for k, v in CALM_JOB.items() if k in out})
        return out
    if isinstance(value, list):
        return [calm(v) for v in value]
    return value


def zero_counts(value):
    if isinstance(value, dict):
        return {k: zero_counts(v) for k, v in value.items()}
    if isinstance(value, int) and not isinstance(value, bool):
        return 0
    return value


def fix_counts(dataset: dict) -> None:
    """Liczniki listy rekrutacji liczą tylko rekrutację ćwiczebną, nie dzień nagrania."""
    board = dataset.get(f"GET /api/pipeline/kanban/{POLIGON_JOB}")
    if not board:
        return
    per_stage: dict[str, int] = collections.Counter()
    # Kilka kolumn szablonu ma ten sam kod etapu (`new`: „Wysłać do Cpro”,
    # „Umowa wysłana”…), więc kolumna listy liczy się po `stage_def_id`.
    per_def: dict[int, int] = collections.Counter()
    for c in board["columns"]:
        per_stage[c.get("stage")] += len(c.get("items", []))
        per_def[c.get("stage_def_id")] += len(c.get("items", []))
    total = sum(per_stage.values())
    ours = {FIRST_CANDIDATE + i for i in range(len(ALL_PEOPLE))}
    for key, value in dataset.items():
        if key == f"GET /api/jobs/{POLIGON_JOB}":
            for k in ("collaborators", "recruiters"):
                if isinstance(value.get(k), list):
                    value[k] = value[k][:1]
        if key == f"GET /api/jobs/{POLIGON_JOB}/pipeline-scores":
            if isinstance(value.get("pipeline_candidate_ids"), list):
                value["pipeline_candidate_ids"] = [
                    c for c in value["pipeline_candidate_ids"] if c in ours
                ]
            for k, v in list(value.items()):
                if isinstance(v, dict) and v and all(x.isdigit() for x in v):
                    value[k] = {x: y for x, y in v.items() if int(x) in ours}
        if key == "GET /api/jobs/quick-counts":
            counts = zero_counts(value)
            for k in ("all", "mine", "open", "my_category", "active_in_search"):
                if k in counts:
                    counts[k] = 1
            for k in (
                "request_status",
                "request_status_mine",
                "request_stage",
                "request_stage_mine",
            ):
                if isinstance(counts.get(k), dict) and "searching" in counts[k]:
                    counts[k]["searching"] = 1
            dataset[key] = counts
        if key.startswith("GET /api/jobs?"):
            for item in value.get("items", []):
                item["stage_breakdown"] = {k: v for k, v in per_stage.items() if v}
                for col in item.get("stage_columns", []):
                    col["count"] = per_def.get(col.get("stage_def_id"), 0)
                item["candidate_count"] = total
                for k in (
                    "needs_action_count",
                    "review_count",
                    "open_proposals_count",
                    "priority_carry_over_count",
                ):
                    if k in item:
                        item[k] = 0
                item["review_count"] = per_stage.get("new", 0)
                if isinstance(item.get("collaborators"), list):
                    item["collaborators"] = item["collaborators"][:1]
                if isinstance(item.get("recruiters"), list):
                    item["recruiters"] = item["recruiters"][:1]


def keep_ours(value):
    """Wyrzuca z list wpisy o osobach i rekrutacjach spoza poligonu."""
    if isinstance(value, dict):
        out = {k: keep_ours(v) for k, v in value.items()}
        if isinstance(out.get("items"), list) and "total" in out:
            out["total"] = len(out["items"])
        return out
    if isinstance(value, list):
        kept = []
        for v in value:
            if isinstance(v, dict):
                cid = v.get("candidate_id")
                if isinstance(cid, int) and cid >= FIRST_OTHER:
                    continue
                if (
                    "client_name" in v
                    and isinstance(v.get("id"), int)
                    and v["id"] >= FIRST_OTHER
                    and "title" in v
                ):
                    continue  # inna rekrutacja na liście
            kept.append(keep_ours(v))
        return kept
    return value


def dl_context(recorded: dict) -> dict:
    """Kontekst przeglądu DL-a: kształt z nagrania, treść wymyślona.

    Wymagania, ocena rekrutera i pola do poprawy pochodzą z innej (prawdziwej)
    rekrutacji, a kwoty klienta i wcześniejsze wysyłki to tajemnica firmy —
    wszystko to zastępujemy treścią pasującą do rekrutacji ćwiczebnej."""
    question = REQUIRED_TEXT["question"]
    rate_at = (recorded.get("candidate_rate") or {}).get("at")
    return {
        **recorded,
        "category_name": "Zarządzanie projektami",
        "candidate_rate": {
            "amount": POLIGON_CANDIDATE_HOURLY,
            "unit": "hourly",
            "currency": "PLN",
            "hourly_pln": POLIGON_CANDIDATE_HOURLY,
            "at": rate_at,
        },
        "rate_from_hourly": 100.0,
        "budget": {"min_hourly": None, "max_hourly": POLIGON_BUDGET_MAX_HOURLY},
        "client_rate_hint": None,
        "client_rates": {
            "consultants": 4,
            "client_margin_median_hourly": 18.0,
            "category_name": "Zarządzanie projektami",
            "category_count": 3,
            "category_cost_min": 98.0,
            "category_cost_max": 110.0,
            "category_revenue_min": 115.0,
            "category_revenue_max": 128.0,
            "category_margin_median_hourly": 17.0,
        },
        "requirements": [
            {
                "key": "must:0",
                "label": "Zarządzanie projektami IT",
                "level": "must",
                "status": "met",
                "sources": ["profil", "CV", "rozmowa"],
                "candidate_value": "9 lat jako Project Manager w bankowości",
            },
            {
                "key": "must:1",
                "label": "Agile / Scrum",
                "level": "must",
                "status": "met",
                "sources": ["CV", "rozmowa"],
                "candidate_value": "Scrum, SAFe",
            },
            {
                "key": "must:2",
                "label": "Angielski B2+",
                "level": "must",
                "status": "missing",
                "sources": [],
                "candidate_value": None,
            },
            {
                "key": "nice:0",
                "label": "Bankowość",
                "level": "nice",
                "status": "unknown",
                "sources": ["CV"],
                "candidate_value": "Programy płatności w bankach",
            },
            {
                "key": "nice:1",
                "label": "PMP lub PRINCE2",
                "level": "nice",
                "status": "met",
                "sources": ["CV"],
                "candidate_value": "PMP (aktywny)",
            },
        ],
        "requirements_met": 3,
        "requirements_total": 5,
        "assessment": {
            "overall_fit": "fit",
            "overall_fit_label": "Pasuje",
            "fields": {
                "recommendation": CV_FICTION["matching_facts"],
                "motivation": "Chce prowadzić większy program niż obecnie.",
                "red_flags": None,
                "availability": "Od 1. dnia przyszłego miesiąca",
                "work_mode": "Hybrydowo",
                "location": "Warszawa",
                "english": None,
                "worked_at_client": "Nie",
            },
            "answers": [
                {
                    "question": question,
                    "question_id": "q1",
                    "answer": "Program migracji płatności: cztery zespoły, 35 osób, 18 miesięcy; prowadziła harmonogram, ryzyka i komitet sterujący.",
                    "deal_breaker_hit": False,
                }
            ],
        },
        "risks": [],
        "start": "1 miesiąc",
        "previous_sends": [],
        "job_sends": [],
        "last_contract": None,
        "hiring_manager_name": None,
        "earlier_interviews": [],
        "recruiter_handoff_remark": None,
        "fix_options": [
            {"key": "question:q1", "label": question, "group": "answers"},
            {"key": "field:availability", "label": "Dostępność", "group": "terms"},
            {"key": "field:work_mode", "label": "Tryb pracy", "group": "terms"},
            {"key": "field:location", "label": "Lokalizacja", "group": "terms"},
            {"key": "field:english", "label": "Angielski", "group": "terms"},
            {
                "key": "field:overall_fit",
                "label": "Ocena rekrutera",
                "group": "assessment",
            },
            {
                "key": "field:recommendation",
                "label": "Dlaczego ten kandydat",
                "group": "assessment",
            },
            {"key": "candidate_rate", "label": "Stawka kandydata", "group": "rate"},
            {"key": "cv", "label": "CV firmowe", "group": "cv"},
        ],
    }


def with_practice(meta: dict, dataset: dict) -> tuple[dict, dict]:
    """Wymyślone odczyty: nowości z porcji i klient ćwiczebny (bez nagrania)."""
    dataset = {k: blank_empty_texts(v) for k, v in dataset.items()}
    add_novelty_practice(dataset)
    practice = client_practice(meta["template_candidate_id"])
    dataset.update(practice)
    # Edytor i karta „CV do klienta”: lata w punkcie 1, gotowe CV z nową zgodą.
    cv, cv_fiction = cv_practice(dataset)
    dataset.update(cv)
    # Stop do podpisu przedwstępnej: ustawienie rekrutacji, Szymon czeka na podpis.
    pre_contract, pre_contract_fiction = pre_contract_practice(dataset)
    dataset.update(pre_contract)
    # Języki i wcześniejsze odpowiedzi osoby-szablonu: ekran wstawia je w zdanie,
    # a filtr nagrania zostawiał `null` (24.11.2026: „null · poziom nieznany”).
    texts, texts_fiction = person_texts(dataset)
    dataset.update(texts)
    # Osoba w „CV wysłane” do lekcji „Terminy przy ruchu” (25.11.2026): kolumna
    # była pusta, a zadanie każe przesunąć kartę właśnie stamtąd.
    terms, people = terms_practice(dataset, meta["people"])
    dataset.update(terms)
    fix_counts(dataset)
    # „Czeka na Ciebie” z osobami ćwiczebnymi (lekcja „Pracuj po kolei”, 25.11.2026).
    board, board_fiction = board_tasks_practice(dataset)
    dataset.update(board)
    # Plan przelewów z fakturą kontraktora ćwiczebnego (lekcja „Zajęcia i spory”).
    payments, payments_fiction = payments_practice()
    dataset.update(payments)
    # Porcja dnia z osobami ćwiczebnymi (lekcje „Porcja…”, 26.11.2026).
    batch, batch_fiction = review_batch_practice(dataset)
    dataset.update(batch)
    meta = {
        **meta,
        "people": people,
        # Osoba w „CV wysłane” (lekcja „Terminy przy ruchu”).
        "terms_candidate_id": TERMS_CARD["candidate_id"],
        # Osoby po stronie klienta ćwiczebnego (nie kandydaci).
        "client_people": CLIENT_PEOPLE,
        # Osoba bez CV do klienta z gotowym CV z innej rekrutacji.
        "ready_cv_candidate_id": READY_CV_PERSON["candidate_id"],
        # Odpowiedzi w całości wymyślone w skrypcie: strażnik zestawu nie
        # wymaga dla nich kluczy ze słownika (`poligon-dataset.test.ts`).
        "fiction_responses": sorted(
            {
                *practice,
                *cv_fiction,
                *pre_contract_fiction,
                *texts_fiction,
                *board_fiction,
                *payments_fiction,
                *batch_fiction,
            }
        ),
    }
    return meta, dataset


def read_dataset() -> tuple[dict, dict]:
    data = json.loads(OUT.read_text())
    return data["meta"], data["responses"]


def write_dataset(meta: dict, dataset: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"meta": meta, "responses": dataset}, ensure_ascii=False, indent=1)
        + "\n"
    )
    META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    print(
        f"{len(dataset)} odpowiedzi → {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", type=Path, nargs="?")
    ap.add_argument("--job", type=int)
    ap.add_argument("--client", type=int)
    ap.add_argument("--candidate", type=int)
    # Bez nagrania: tylko wymyślone odczyty na zestawie, który już jest w repo.
    ap.add_argument("--practice-only", action="store_true")
    # Przegląd Delivery Leada (fazy `dl-review*`): inna rekrutacja, osoba i jej
    # wiersz etapu „QC CV” — trafiają pod rekrutację i osobę-szablon poligonu.
    ap.add_argument("--dl-job", type=int)
    ap.add_argument("--dl-client", type=int)
    ap.add_argument("--dl-candidate", type=int)
    ap.add_argument("--dl-stage", type=int)
    # Edytor CV (faza `cv-editor-api`): etap osoby z CV firmowym — trafia pod osobę-szablon.
    ap.add_argument("--cv-stage", type=int)
    ap.add_argument("--cv-candidate", type=int)
    ap.add_argument("--captured-at", default=datetime.now(timezone.utc).isoformat())
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.practice_only:
        write_dataset(*with_practice(*read_dataset()))
        return
    if not (args.recording and args.job and args.client and args.candidate):
        ap.error("nagranie wymaga katalogu oraz --job, --client i --candidate")

    b = Builder(
        args.job, args.client, args.candidate, datetime.fromisoformat(args.captured_at)
    )
    log = json.loads((args.recording / "log.json").read_text())

    entries: list[tuple[dict, object]] = []
    for i, e in enumerate(log):
        body_file = args.recording / f"{i:04d}.json"
        dl_phase = e.get("phase", "").startswith("dl-")
        if (
            e["status"] != 200
            or not body_file.exists()
            or e["path"].startswith("/api/novelties/")
            # Odznaka terminów i podpowiedzi prepów są wymyślone (`slot_badge`).
            or e.get("phase", "").startswith("slot-")
            or (
                dl_phase
                and (
                    not args.dl_job
                    or not (
                        e["phase"] in DL_PHASES
                        or (
                            e["phase"] == "dl-board" and DL_BOARD_PATHS.match(e["path"])
                        )
                    )
                )
            )
        ):
            continue
        try:
            body = json.loads(body_file.read_text())
        except json.JSONDecodeError:
            continue
        entries.append((e, body))

    # Dogranie (`ADD_ONLY_PHASES`) uczy filtr nazw tylko z odpowiedzi, które
    # wchodzą do zestawu (niżej) — inaczej obce firmy i szkoły z całego
    # dogrania zdejmowałyby słowa takie jak „Polish” z odpowiedzi nagrania.
    for e, body in entries:
        if e.get("phase") not in ADD_ONLY_PHASES:
            b.learn_real_names(body)
    for e, body in entries:
        if e["path"] == f"/api/pipeline/kanban/{args.job}":
            for col in body["columns"]:
                for it in col.get("items", []):
                    b.learn_real_names(
                        {"name": f"{it.get('name', '')} {it.get('lastname', '')}"}
                    )
        if e["path"] == "/api/users":
            b.learn_real_names(body)

    # Najpierw Tablica, żeby osoby ćwiczebne dostały stałe identyfikatory.
    for e, body in entries:
        if e["path"] == f"/api/pipeline/kanban/{args.job}":
            body = shape_kanban(b, body)
            e["_shaped"] = body
    # Szablon panelu osoby to osoba z nagrania → pierwsza osoba ćwiczebna z kolumny Screening.
    template_entry = next(
        (e for e in log if e["path"].startswith("/api/candidates/stages/")), None
    )
    b.ids.setdefault(args.candidate, FIRST_CANDIDATE)
    template_stage = (
        int(re.search(r"/stages/(\d+)/", template_entry["path"]).group(1))
        if template_entry
        else 0
    )
    if template_entry:
        b.ids.setdefault(template_stage, FIRST_ENTRY)
    if args.dl_job:
        # Przegląd DL-a nagrany na innej rekrutacji = ta sama osoba-szablon:
        # jej identyfikatory, wiersz etapu i CV etapu, imię i nazwisko.
        template_entry_id = b.ids.get(template_stage, FIRST_ENTRY)
        b.ids[args.dl_job] = POLIGON_JOB
        b.ids[args.dl_candidate] = b.ids[args.candidate]
        b.ids[args.dl_stage] = template_entry_id
        if args.dl_client:
            b.ids[args.dl_client] = POLIGON_CLIENT
            b.client_ids.add(args.dl_client)
        first, last = PEOPLE[b.ids[args.candidate] - FIRST_CANDIDATE]
        for e, body in entries:
            if e["path"] == "/api/board-tasks/dl-review-row":
                row = body.get("row") or {}
                if isinstance(row.get("cv_stage_id"), int):
                    b.ids[row["cv_stage_id"]] = template_entry_id
                if isinstance(row.get("candidate_name"), str):
                    b.person_names[row["candidate_name"].strip()] = f"{first} {last}"

    if args.cv_stage:
        b.ids[args.cv_stage] = b.ids.get(template_stage, FIRST_ENTRY)
        b.ids[args.cv_candidate] = b.ids[args.candidate]
    owned_markers = {
        str(args.job),
        str(args.candidate),
        f"client_id={args.client}",
        f"/clients/{args.client}/",
    }
    if args.dl_job:
        owned_markers |= {str(args.dl_job), str(args.dl_candidate), str(args.dl_stage)}
    if args.cv_stage:
        owned_markers |= {str(args.cv_stage), str(args.cv_candidate)}
    dataset: dict[str, object] = {}
    for e, body in entries:
        raw = e["path"] + e["query"] + (e.get("reqBody") or "")
        owned = (
            any(m in raw for m in owned_markers)
            or "/stages/" in e["path"]
            or e["path"]
            in {
                "/api/jobs",
                "/api/jobs/quick-counts",
                "/api/pipeline-templates/1",
                "/api/saved-searches",
                *MY_PEOPLE_PATHS,
            }
        )
        if not owned:
            continue
        key = f"{e['method']} {b.clean_url(e['path'], e['query'])}"
        if (
            e.get("phase", "").startswith("dl-") or e.get("phase") in ADD_ONLY_PHASES
        ) and key in dataset:
            continue
        if e.get("phase") in ADD_ONLY_PHASES:
            b.learn_real_names(body)
        if re.match(rf"/api/candidates/{args.candidate}(/quick-view)?$", e["path"]):
            first, last = PEOPLE[b.ids[args.candidate] - FIRST_CANDIDATE]
            body = fictionalize_candidate(body, first, last)
        dataset[key] = prune_dropped(calm(keep_ours(b.clean(e.get("_shaped", body)))))

    # Adresy, których nagranie nie złapało, a ekran woła je przy ćwiczeniach.
    tpl = b.ids[args.candidate]
    # Baza kandydatów poligonu = osoby ćwiczebne. Z nagranej listy bierzemy
    # tylko nazwy pól wiersza; wartości pochodzą z profilu ćwiczebnego.
    recorded_list = next(
        (
            body
            for e, body in entries
            if e["path"] == "/api/candidates"
            and isinstance(body, dict)
            and len(body.get("items") or []) > 1
        ),
        None,
    )
    shape_my_people(dataset)
    for key in [k for k in dataset if k.startswith("GET /api/users/mentionable")]:
        dataset[key] = mentionable_users()
    # Członkowie czatu rekrutacji = trenerzy poligonu (jak lista do „@”).
    for key in [k for k in dataset if re.match(r"GET /api/jobs/\d+/chat/members", k)]:
        dataset[key] = [
            {"id": u["id"], "name": u["name"], "email": None, "role": u["role"]}
            for u in mentionable_users()
        ]
    dataset["GET /api/users/mentionable"] = mentionable_users()
    profile = dataset.get(f"GET /api/candidates/{tpl}")
    if recorded_list and isinstance(profile, dict):
        keys = list(recorded_list["items"][0].keys())
        envelope = b.clean(
            {k: v for k, v in recorded_list.items() if k not in ("items", "total")}
        )
        items = []
        for i, (first, last) in enumerate(PEOPLE):
            row = {k: copy.deepcopy(profile.get(k)) for k in keys}
            # Wiersz listy, nie profil: krótkie listy, żeby zestaw był lekki.
            for long_key, keep in (("experience", 1), ("education", 1), ("skills", 6)):
                if isinstance(row.get(long_key), list):
                    row[long_key] = row[long_key][:keep]
            row.update(
                id=FIRST_CANDIDATE + i,
                name=first,
                lastname=last,
                cv_extracted_data=None,
                identity_sync=None,
            )
            items.append(row)
        dataset["GET /api/candidates"] = {
            **envelope,
            "items": items,
            "total": len(items),
            "page": 1,
            "page_size": 50,
        }
    dataset.setdefault(
        f"GET /api/interview-cycle/pairs/{POLIGON_JOB}/{tpl}/meetings", []
    )
    # Źródła kandydatów, których nagranie nie ma: puste listy, nie błąd ekranu.
    job = POLIGON_JOB
    dataset.setdefault(
        f"GET /api/jobs/{job}/proposal-inbox?limit=50&offset=0&status=proposed",
        {
            "job_id": job,
            "status": "proposed",
            "items": [],
            "dismissed_candidate_ids": [],
            "total": 0,
            "hidden_on_page": 0,
        },
    )
    dataset.setdefault(
        f"GET /api/jobs/{job}/screened-out", {"job_id": job, "total": 0, "items": []}
    )
    dataset.setdefault(
        f"GET /api/jobs/{job}/candidates-from-similar",
        {
            "job_id": job,
            "tier_used": "primary",
            "similar_jobs": [],
            "candidates": [],
            "meta": {
                "tier_a_count": 0,
                "tier_b_count": 0,
                "total_sources": 0,
                "reason_if_empty": None,
            },
        },
    )
    for key in [k for k in dataset if k.startswith("GET /api/dl-review/context?")]:
        dataset[key] = dl_context(dataset[key])
    # Rekrutacja ćwiczebna jest gotowa do przekazania (nagrana miała braki).
    key = f"GET /api/jobs/{POLIGON_JOB}/readiness"
    if isinstance(dataset.get(key), dict):
        dataset[key] = {
            **dataset[key],
            "ready": True,
            "blockers": [],
            "blocker_items": [],
        }
    # Inne procesy osoby w mailu odrzucenia to prawdziwe rekrutacje.
    for key in [
        k for k in dataset if k.startswith("POST /api/rejection-emails/preview")
    ]:
        for person in dataset[key].get("people") or []:
            person["other_processes"] = []
    # „Pasuje też do” wskazywałoby prawdziwe rekrutacje — na poligonie nic.
    for key in [k for k in dataset if k.startswith("GET /api/dl-match/candidates/")]:
        dataset[key] = {**dataset[key], "jobs": []}
    # Odczyty Tablicy, których jedno nagranie nie łapie (zależą od stanu
    # rekrutacji): ostatni przegląd bazy i migawka rekomendacji. Na rekrutacji
    # ćwiczebnej ich nie ma — serwer odpowiada wtedy `run: null` i 404, a 404
    # zapisujemy jawnie (`@status`), żeby adapter nie brał go za brak w zestawie.
    dataset.setdefault(
        f"GET /api/candidate-search/jobs/{job}/latest-run", {"job_id": job, "run": None}
    )
    dataset.setdefault(f"GET /api/jobs/{job}/proposals/latest", {"@status": 404})
    # „Historia i czat” (ćwiczenie czatu): zakładki „Praca w tle” i „Historia
    # requestów”. Nagrana historia to prawdziwe rekrutacje innych klientów —
    # na rekrutacji ćwiczebnej obie są puste (kształt z odpowiedzi stagingu).
    dataset.setdefault(
        f"GET /api/jobs/{job}/background-events?limit=30",
        {"job_id": job, "items": [], "limit": 30},
    )
    dataset.setdefault(
        f"GET /api/jobs/{job}/request-history?cross_client=false&include_open=true&top_k=15",
        {
            "closed": [],
            "in_progress": [],
            "skill_frequency": {
                "n": 0,
                "must": [],
                "nice": [],
                "consistent_must": [],
                "consistent_nice": [],
                "threshold": 0.6,
            },
            "meta": {
                "sql_count": 0,
                "voyage_count": 0,
                "total": 0,
                "skill_freq_sample": 0,
            },
        },
    )
    # Proces u klienta (18.11.2026) — fakt w nagłówku rekrutacji. Na
    # rekrutacji ćwiczebnej nikt go nie wpisał, a historia klienta ma mniej
    # niż 5 decyzji: serwer odpowiada wtedy obiema wartościami `null`.
    dataset.setdefault(
        f"GET /api/jobs/client-process?client_id={POLIGON_CLIENT}&job_id={job}",
        {"client_id": POLIGON_CLIENT, "suggested": None, "measured": None},
    )
    # Ćwiczenia z 16.11.2026: osoba czeka na wybór terminu u klienta, a CV
    # firmowe osoby-szablonu jest szkicem do poprawy asystentem.
    add_slot_card(dataset)
    add_novelty_practice(dataset)
    dataset = drop_stripped_words(dataset)
    dataset[
        f"GET /api/interview-cycle/preps/suggestions?candidate_id={tpl}&job_id={job}"
        "&prep1_minutes=45&prep2_minutes=45"
    ] = prep_suggestions()
    tpl_entry = b.ids.get(template_stage, FIRST_ENTRY)
    branded = f"GET /api/candidates/stages/{tpl_entry}/cv/branded"
    if isinstance(dataset.get(branded), dict):
        dataset[branded] = {**dataset[branded], **BRANDED_DRAFT}
    dataset.setdefault(
        f"GET /api/candidates/stages/{tpl_entry}/cv/branded/versions", {"versions": []}
    )
    fix_counts(dataset)
    meta = {
        "job_id": POLIGON_JOB,
        "job_title": JOB_TITLE,
        "job_reference": JOB_REFERENCE,
        "client_id": POLIGON_CLIENT,
        "client_name": CLIENT_NAME,
        "template_candidate_id": b.ids[args.candidate],
        "template_entry_id": b.ids.get(template_stage, FIRST_ENTRY),
        # Osoby ćwiczeń z 16.11.2026: czeka na termin u klienta / „odczytana” z pliku CV.
        "slot_candidate_id": FIRST_CANDIDATE
        + len(PEOPLE)
        + EXTRA_PEOPLE.index(SLOT_PERSON),
        "cv_candidate_id": FIRST_CANDIDATE
        + len(PEOPLE)
        + EXTRA_PEOPLE.index(CV_PERSON),
        "trainers": {k: {"id": v[0], "name": v[1]} for k, v in TRAINERS.items()},
        "people": [
            {
                "candidate_id": FIRST_CANDIDATE + i,
                "entry_id": FIRST_ENTRY + i,
                "name": first,
                "lastname": last,
            }
            for i, (first, last) in enumerate(ALL_PEOPLE)
        ],
    }
    write_dataset(*with_practice(meta, dataset))
    if args.report:
        for key, counter in sorted(
            b.dropped.items(), key=lambda kv: -sum(kv[1].values())
        ):
            print(f"\n[{key}] {sum(counter.values())}")
            for v, n in counter.most_common(8):
                print(f"   {n:>3}× {v}")


if __name__ == "__main__":
    main()
