"""Zestaw danych Poligonu NEXUSA z nagranych odpowiedzi API.

Poligon (onboarding rekruterów, decyzja Artura z 14.11.2026) pokazuje prawdziwe
ekrany NEXUSA na rekrutacji ćwiczebnej. Front podaje im odpowiedzi z pliku
`frontend/src/lib/poligon/dataset.json`; ten skrypt go buduje.

Wejście to katalog nagrania (`log.json` + ciała odpowiedzi `0000.json`…),
zrobionego na stagingu z laptopa jednym kontem rekrutera: lista rekrutacji,
Tablica jednej rekrutacji i panel jednej osoby. Nagranie zawiera prawdziwe dane,
więc zostaje lokalnie i NIGDY nie trafia do repo.

Zasada bezpieczeństwa (repo jest publiczne): każdy tekst, którego nie ma
w `frontend/src/lib/poligon/vocab.json` ani w słowniku osób ćwiczebnych poniżej,
znika. Wyjątki: krótkie kody (`screening`, `hybrid`) i daty, które zamieniamy
na względne (`@rel:-3.2` = 3,2 dnia temu). Identyfikatory przechodzą na zakres
poligonu (990000+). Test `poligon-dataset.test.ts` sprawdza to samo po stronie
frontu, więc nowy tekst w zestawie bez wpisu w słowniku zatrzyma CI.

Użycie (z `backend/`):
    python3 scripts/build_poligon_dataset.py <katalog-nagrania> --job <id> \
        --client <id> --candidate <id> [--report]

`--report` wypisuje teksty, które zniknęły, pogrupowane po kluczu — z tej listy
dopisuje się do `vocab.json` etykiety interfejsu (nigdy osoby, firmy, notatki).
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

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

FICTIONAL_NAMES = (
    {n for pair in PEOPLE for n in pair}
    | {f"{a} {b}" for a, b in PEOPLE}
    | {t[1] for t in TRAINERS.values()}
    | {JOB_TITLE, CLIENT_NAME, JOB_REFERENCE}
)

# Ile kart zostaje w kolumnie Tablicy (po kodzie etapu); reszta kolumn pusta.
CARDS_PER_STAGE = {"new": 4, "screening": 3, "verified": 2}

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

ENUM = re.compile(r"^[a-z0-9_\-:.]{1,60}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:\d{2})?)?$")
DIGITS = re.compile(r"^\d{4,}$")

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
        if ENUM.match(value) and not self.mentions_real(value):
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
                return None if key not in {"name", "title", "label"} else ""
            return value
        if PERSON_NAME_KEYS.search(key) and re.match(
            r"^[A-ZŁŚŻŹĆÓ][a-ząćęłńóśźż]+(\s+[A-ZŁŚŻŹĆÓ][a-ząćęłńóśźż-]+)+$",
            value.strip(),
        ):
            return self.fake_person(value.strip())
        self.dropped[key][value[:80]] += 1
        return None if key not in {"name", "title", "label"} else ""

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


def shape_kanban(b: Builder, data: dict) -> dict:
    """Mała Tablica: kilka kart w pierwszych kolumnach, osoby ćwiczebne."""
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
}


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
    for c in board["columns"]:
        per_stage[c.get("stage")] += len(c.get("items", []))
    total = sum(per_stage.values())
    ours = {FIRST_CANDIDATE + i for i in range(len(PEOPLE))}
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
                    col["count"] = per_stage.get(col.get("stage"), 0)
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", type=Path)
    ap.add_argument("--job", type=int, required=True)
    ap.add_argument("--client", type=int, required=True)
    ap.add_argument("--candidate", type=int, required=True)
    ap.add_argument("--captured-at", default=datetime.now(timezone.utc).isoformat())
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    b = Builder(
        args.job, args.client, args.candidate, datetime.fromisoformat(args.captured_at)
    )
    log = json.loads((args.recording / "log.json").read_text())

    entries: list[tuple[dict, object]] = []
    for i, e in enumerate(log):
        body_file = args.recording / f"{i:04d}.json"
        if (
            e["status"] != 200
            or not body_file.exists()
            or e["path"].startswith("/api/novelties/")
        ):
            continue
        try:
            body = json.loads(body_file.read_text())
        except json.JSONDecodeError:
            continue
        entries.append((e, body))

    for _, body in entries:
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

    owned_markers = {
        str(args.job),
        str(args.candidate),
        f"client_id={args.client}",
        f"/clients/{args.client}/",
    }
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
            }
        )
        if not owned:
            continue
        key = f"{e['method']} {b.clean_url(e['path'], e['query'])}"
        if re.match(rf"/api/candidates/{args.candidate}(/quick-view)?$", e["path"]):
            first, last = PEOPLE[b.ids[args.candidate] - FIRST_CANDIDATE]
            body = fictionalize_candidate(body, first, last)
        dataset[key] = calm(keep_ours(b.clean(e.get("_shaped", body))))

    # Adresy, których nagranie nie złapało, a ekran woła je przy ćwiczeniach.
    tpl = b.ids[args.candidate]
    dataset.setdefault(
        f"GET /api/interview-cycle/pairs/{POLIGON_JOB}/{tpl}/meetings", []
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
        "trainers": {k: {"id": v[0], "name": v[1]} for k, v in TRAINERS.items()},
        "people": [
            {
                "candidate_id": FIRST_CANDIDATE + i,
                "entry_id": FIRST_ENTRY + i,
                "name": first,
                "lastname": last,
            }
            for i, (first, last) in enumerate(PEOPLE)
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"meta": meta, "responses": dataset}, ensure_ascii=False, indent=1)
        + "\n"
    )
    META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    print(
        f"{len(dataset)} odpowiedzi → {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)"
    )
    if args.report:
        for key, counter in sorted(
            b.dropped.items(), key=lambda kv: -sum(kv[1].values())
        ):
            print(f"\n[{key}] {sum(counter.values())}")
            for v, n in counter.most_common(8):
                print(f"   {n:>3}× {v}")


if __name__ == "__main__":
    main()
