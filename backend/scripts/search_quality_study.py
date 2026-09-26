"""Szerokie badanie wyszukiwania ręcznego (tylko odczyt) — 26.09.2026.

Uzupełnia ``compare_keyword_fold_fts`` (stara vs nowa ścieżka) o pytania,
które decydują, czy rekruter znajdzie właściwą osobę, a nie tylko „ile osób
zwraca słowo”:

1. **Stan danych** — ilu kandydatów w ogóle da się znaleźć słowem: bez tekstu
   CV (a z plikiem CV), ze sklejonym tekstem, bez niczego poza notatkami.
2. **Stara vs nowa ścieżka** — jak ``compare_keyword_fold_fts``.
3. **Skąd trafienie** (nowa ścieżka) — CV / stanowisko / umiejętności /
   notatki; ile osób jest do znalezienia WYŁĄCZNIE dzięki notatkom albo bez
   tekstu CV, i czy zawężenie zakresu (``q_scope``) zgadza się z „wszędzie”.
4. **Warianty pisowni** — pary (k8s/kubernetes, postgres/postgresql…): ile osób
   gubi rekruter, który wpisze tylko jedną formę, i czy przycisk „z wariantami”
   podsuwa drugą.
5. **Odmiana** — „bankowość” vs „bankow*” vs angielski odpowiednik.
6. **Historia rekrutacji** — czy wiersze wymagań z must-have znajdują osoby,
   które zespół potem zweryfikował/wysłał; ile tylko dzięki notatkom
   (notatki sprzed otwarcia rekrutacji, bez przecieku z samego procesu);
   dlaczego nie znajdują pozostałych.
8. **Szum** krótkich i wieloznacznych słów (sap, go, r, swift…) — konteksty
   trafień w CV do przejrzenia, udział adresów i linków.
9. **Zgodność liczb** — „N osób” w podpowiedzi vs wynik listy.
10. **Filtry a wybrani** — ile osób zweryfikowanych/wysłanych klientowi
    wycięłyby filtry stawki, miasta, statusu i kategorii, w tym te, które
    „Szukaj ręcznie” dokłada sam.
7. **API** (``--api``, w kontenerze backendu) — czasy ``GET /api/candidates``
   w typowych scenariuszach, „Szukaj ręcznie” z ``sort=match`` i zgodność
   kolejności z kolumną „Dop.” (``/api/search/candidates/scores``).

Baza w ``SET TRANSACTION READ ONLY``; API tylko GET i POST-y do odczytu
(``/scores``) z krótkim tokenem zmintowanym w procesie::

    cd /app && python -m scripts.search_quality_study            # części 1–6, 8–10
    cd /app && python -m scripts.search_quality_study --api      # + część 7
    cd /app && python -m scripts.search_quality_study --only 3,4 --jobs 40

Wynik: Markdown na stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import time
from datetime import timedelta

from sqlalchemy import select, text

from scripts.compare_keyword_fold_fts import DEFAULT_WORDS

SOURCE_WORDS: tuple[str, ...] = (
    "java",
    "python",
    "sql",
    "react",
    "c#",
    "kubernetes",
    "sap",
    "scrum",
    "tester",
    "analityk",
    "bankowość",
    "ubezpieczenia",
    "b2b",
    "zdalnie",
    "angielski",
    "łódź",
    "kraków",
)

# (to, co wpisze rekruter, forma, którą mogą mieć inni kandydaci)
VARIANT_PAIRS: tuple[tuple[str, str], ...] = (
    ("kubernetes", "k8s"),
    ("postgresql", "postgres"),
    ("javascript", "js"),
    ("typescript", "ts"),
    ("react", "reactjs"),
    ("node.js", "nodejs"),
    ("vue", "vuejs"),
    ("angular", "angularjs"),
    ("spring boot", "springboot"),
    ("power bi", "powerbi"),
    ("sql server", "mssql"),
    ("pl/sql", "plsql"),
    (".net", "dotnet"),
    ("c#", "csharp"),
    ("golang", "go"),
    ("excel", "ms excel"),
    ("qa", "quality assurance"),
    ("ux", "user experience"),
    ("ci/cd", "cicd"),
    ("devops", "dev ops"),
    ("machine learning", "ml"),
    ("tester", "qa"),
    ("programista", "developer"),
    ("analityk", "analyst"),
    ("bankowość", "banking"),
    ("ubezpieczenia", "insurance"),
    ("kierownik projektu", "project manager"),
)

INFLECTION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("bankowość", "bankowości", "bankow*", "banking"),
    ("ubezpieczenia", "ubezpieczeń", "ubezpiecz*", "insurance"),
    ("analityk", "analityka", "analityk*", "analyst"),
    ("programista", "programisty", "programist*", "developer"),
    ("testowanie", "testów", "testow*", "testing"),
    ("zarządzanie", "zarządzania", "zarzadz*", "management"),
    ("telekomunikacja", "telekomunikacji", "telekomunik*", "telecommunications"),
    ("energetyka", "energetyki", "energetyk*", "energy"),
)

SCOPES = ("cv", "title", "skills", "notes")
SAMPLE = 5


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "—"


def _term(word: str):
    from app.services.keyword_terms import parse_keyword

    return parse_keyword(word)


async def _ids(db, clause) -> tuple[set[int], float]:
    from app.models.candidate import Candidate

    started = time.perf_counter()
    rows = (await db.execute(select(Candidate.id).where(clause))).scalars().all()
    return set(rows), (time.perf_counter() - started) * 1000


async def _new(db, word: str, scope: str = "all") -> set[int]:
    from app.services import keyword_corpus
    from app.services.advanced_candidate_search import _whole_word_match

    term = _term(word)
    if term is None:
        return set()
    with keyword_corpus.force_folded_search(True):
        ids, _ = await _ids(db, _whole_word_match(term, scope))
    return ids


# --- 1. Stan danych -----------------------------------------------------------


async def part_data(db) -> None:
    from app.services import keyword_corpus
    from app.services.cv_text_extractor import GLUED_AVG_WORD_LEN

    print("\n## 1. Stan danych — kogo w ogóle da się znaleźć słowem\n")
    row = (
        await db.execute(
            text(
                """
        with c as (
          select c.id,
                 coalesce(length(btrim(c.raw_cv_text)), 0) as cv_len,
                 c.raw_cv_text,
                 coalesce(jsonb_array_length(case when jsonb_typeof(c.skills)='array'
                          then c.skills end), 0) as n_skills,
                 exists (select 1 from notes n where n.candidate_id = c.id) as has_notes,
                 exists (select 1 from candidate_documents d where d.candidate_id = c.id
                         and d.document_kind = 'cv') as has_cv_doc,
                 c.keyword_fold_fts is null as fold_null
          from candidates c
        )
        select count(*) as total,
               count(*) filter (where cv_len = 0) as no_cv_text,
               count(*) filter (where cv_len = 0 and has_cv_doc) as cv_doc_without_text,
               count(*) filter (where cv_len between 1 and 299) as cv_short,
               count(*) filter (where cv_len >= 300 and cv_len::float /
                   nullif(cv_len - length(replace(raw_cv_text, ' ', '')) + 1, 0)
                   > :glued) as cv_glued,
               count(*) filter (where n_skills = 0) as no_skills,
               count(*) filter (where cv_len = 0 and n_skills = 0 and has_notes)
                   as only_notes,
               count(*) filter (where cv_len = 0 and n_skills = 0 and not has_notes)
                   as nothing,
               count(*) filter (where has_notes) as with_notes,
               count(*) filter (where fold_null) as fold_null
        from c
        """
            ),
            {"glued": GLUED_AVG_WORD_LEN},
        )
    ).one()
    total = row.total
    wrapped = (await db.execute(text(keyword_corpus.NOTES_WRAPPED_COUNT_SQL))).scalar()
    version = (
        await db.execute(
            text("select value from app_settings where key = :k"),
            {"k": keyword_corpus.FOLD_VERSION_KEY},
        )
    ).scalar()
    lines = [
        ("Kandydaci razem", total),
        ("Bez tekstu CV", row.no_cv_text),
        ("…w tym z plikiem CV (tekst nie odczytany)", row.cv_doc_without_text),
        ("Tekst CV krótszy niż 300 znaków", row.cv_short),
        ("Tekst CV sklejony (słowa bez spacji)", row.cv_glued),
        ("Bez listy umiejętności", row.no_skills),
        ("Bez CV i umiejętności, ale z notatkami (tylko notatki)", row.only_notes),
        ("Bez CV, umiejętności i notatek", row.nothing),
        ("Z co najmniej jedną notatką", row.with_notes),
        ("Bez korpusu złożonego (keyword_fold_fts NULL)", row.fold_null),
        ("Notatki nadal zapisane jako JSON Traffita", wrapped),
    ]
    print("| co | osób | udział |")
    print("|---|---:|---:|")
    for label, value in lines:
        share = "" if label.startswith("Notatki nadal") else _pct(value, total)
        print(f"| {label} | {value} | {share} |")
    print(
        f"\nWersja składania w bazie: `{version}` "
        f"(kod: {keyword_corpus.FOLD_VERSION}).",
        flush=True,
    )


# --- 2. Stara vs nowa ścieżka -------------------------------------------------


async def part_compare(db, words: list[str]) -> None:
    from app.services import keyword_corpus
    from app.services.advanced_candidate_search import _whole_word_match

    print("\n## 2. Stara vs nowa ścieżka\n")
    print(
        "| słowo | stara | nowa | ubywa | przybywa | stara ms | nowa ms | przykłady ubywa |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    lost_total = gained_total = 0
    for word in words:
        term = _term(word)
        if term is None:
            continue
        with keyword_corpus.force_folded_search(False):
            old, old_ms = await _ids(db, _whole_word_match(term, "all"))
        with keyword_corpus.force_folded_search(True):
            new, new_ms = await _ids(db, _whole_word_match(term, "all"))
        lost, gained = sorted(old - new), sorted(new - old)
        lost_total += len(lost)
        gained_total += len(gained)
        print(
            f"| {word} | {len(old)} | {len(new)} | {len(lost)} | {len(gained)} "
            f"| {old_ms:.0f} | {new_ms:.0f} | {lost[:SAMPLE]} |",
            flush=True,
        )
    print(f"\nRazem ubywa: {lost_total}, przybywa: {gained_total}.")


# --- 3. Skąd trafienie --------------------------------------------------------


async def part_sources(db) -> None:
    print("\n## 3. Skąd trafienie (nowa ścieżka)\n")
    no_cv = set(
        (
            await db.execute(
                text(
                    "select id from candidates "
                    "where coalesce(length(btrim(raw_cv_text)), 0) = 0"
                )
            )
        ).scalars()
    )
    print(
        "„Tylko notatki” = słowo w notatce, a nie w CV, stanowisku ani umiejętnościach "
        "(może jeszcze stać w innym polu profilu). „Profil poza CV” = trafienie bez "
        "CV i bez notatek (pola Traffita, „o sobie”, stanowiska, umiejętności).\n"
    )
    print(
        "| słowo | wszędzie | CV | stanowisko | umiejętności | notatki "
        "| tylko notatki | bez tekstu CV | CV ⊄ wszędzie |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for word in SOURCE_WORDS:
        everywhere = await _new(db, word)
        per = {scope: await _new(db, word, scope) for scope in SCOPES}
        only_notes = per["notes"] - per["cv"] - per["title"] - per["skills"]
        outside = sum(len(per[s] - everywhere) for s in ("cv", "title", "skills"))
        print(
            f"| {word} | {len(everywhere)} | {len(per['cv'])} | {len(per['title'])} "
            f"| {len(per['skills'])} | {len(per['notes'])} "
            f"| {len(only_notes)} ({_pct(len(only_notes), len(everywhere))}) "
            f"| {len(everywhere & no_cv)} | {outside} |",
            flush=True,
        )
    print(
        "\n„CV ⊄ wszędzie” > 0 znaczy, że zawężenie zakresu znajduje kogoś, kogo "
        "„wszędzie” nie znajduje — błąd."
    )
    print("\nZakres a polskie znaki (ta sama osoba, dwie pisownie):\n")
    print("| pisownia A | pisownia B | CV A | CV B | wszędzie A | wszędzie B |")
    print("|---|---|---:|---:|---:|---:|")
    for a, b in (
        ("łódź", "lodz"),
        ("kraków", "krakow"),
        ("zarządzanie", "zarzadzanie"),
    ):
        cv_a, cv_b = await _new(db, a, "cv"), await _new(db, b, "cv")
        all_a, all_b = await _new(db, a), await _new(db, b)
        print(
            f"| {a} | {b} | {len(cv_a)} | {len(cv_b)} | {len(all_a)} | {len(all_b)} |",
            flush=True,
        )


# --- 4. Warianty pisowni ------------------------------------------------------


def _offered_variants(word: str) -> tuple[str, ...]:
    from app.services import keyword_suggest as ks

    key = ks.fold(word)
    for entry in ks.catalog():
        if entry.key == key or key in entry.alias_keys:
            return ks.skill_variants(entry)
    return ()


async def part_variants(db) -> None:
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    print("\n## 4. Warianty pisowni\n")
    print(
        "„Gubi” = osoby znalezione drugą formą, których pierwsza forma nie znajduje "
        "(rekruter wpisał tylko pierwszą). Uwaga: krótkie formy (js, ts, go, qa, ml) "
        "łapią też szum — sprawdź próbki przed dopisaniem wariantu.\n"
    )
    print(
        "| wpisuje | druga forma | wpisuje: osób | druga: osób | gubi | „z wariantami” podsuwa | próbka gubionych |"
    )
    print("|---|---|---:|---:|---:|---|---|")
    for typed, other in VARIANT_PAIRS:
        a, b = await _new(db, typed), await _new(db, other)
        missing = sorted(b - a)
        offered = _offered_variants(typed)
        covered = any(v.lower() == other.lower() for v in offered)
        print(
            f"| {typed} | {other} | {len(a)} | {len(b)} | {len(missing)} "
            f"| {'tak' if covered else 'nie'} ({', '.join(offered) or '—'}) "
            f"| {missing[:SAMPLE]} |",
            flush=True,
        )


# --- 5. Odmiana ---------------------------------------------------------------


async def part_inflection(db) -> None:
    print("\n## 5. Odmiana i angielski odpowiednik\n")
    print(
        "| forma podstawowa | inna forma | rdzeń* | angielski | podstawowa | inna | rdzeń* | angielski | rdzeń* ∪ angielski |"
    )
    print("|---|---|---|---|---:|---:|---:|---:|---:|")
    for base, other, stem, english in INFLECTION_GROUPS:
        s_base, s_other = await _new(db, base), await _new(db, other)
        s_stem, s_en = await _new(db, stem), await _new(db, english)
        print(
            f"| {base} | {other} | {stem} | {english} | {len(s_base)} | {len(s_other)} "
            f"| {len(s_stem)} | {len(s_en)} | {len(s_stem | s_en)} |",
            flush=True,
        )


# --- 6. Historia rekrutacji ---------------------------------------------------

_SKILL_RE = re.compile(r"[a-z0-9ąćęłńóśźż#+./ ]{2,30}")


async def _hits_among(db, word: str, ids: list[int], notes_before) -> tuple[set, set]:
    """(trafienia w profilu/CV, trafienia w notatkach sprzed ``notes_before``)."""
    from app.services.advanced_candidate_search import folded_tsquery
    from app.services import keyword_corpus  # noqa: F401  (FOLD_FUNCTION)
    from app.models.candidate import Candidate
    from app.models.note import Note
    from app.services.advanced_candidate_search import _KEYWORD_FOLD_FTS, _NOTE_FOLD_FTS

    term = _term(word)
    query = folded_tsquery(term) if term is not None else None
    if query is None:
        return set(), set()
    profile = set(
        (
            await db.execute(
                select(Candidate.id).where(
                    Candidate.id.in_(ids), _KEYWORD_FOLD_FTS.op("@@")(query)
                )
            )
        ).scalars()
    )
    notes = set(
        (
            await db.execute(
                select(Note.candidate_id).where(
                    Note.candidate_id.in_(ids),
                    Note.created_at < notes_before,
                    _NOTE_FOLD_FTS.op("@@")(query),
                )
            )
        ).scalars()
    )
    return profile, notes


async def part_history(db, max_jobs: int) -> None:
    from app.services.cv_text_extractor import looks_glued

    print("\n## 6. Historia rekrutacji — czy wiersze wymagań znajdują właściwe osoby\n")
    jobs = (
        await db.execute(
            text(
                """
        select j.id, coalesce(j.opened_at, j.created_at) t0, j.must_skills
        from jobs j
        where (case when jsonb_typeof(j.must_skills)='array'
                    then jsonb_array_length(j.must_skills) else 0 end) >= 2
          and coalesce(j.opened_at, j.created_at) > now() - interval '24 months'
          and (select count(*) from analytics_first_milestones m
               where m.job_id = j.id and m.stage in ('verified','cv_sent')) >= 2
        order by j.id desc limit 600"""
            )
        )
    ).all()
    used = 0
    stats = {
        "positives": 0,
        "and_all": 0,
        "and_without_notes": 0,
        "any_row": 0,
        "notes_only_rows": 0,
    }
    per_row_hits = per_row_total = 0
    reasons = {"brak tekstu CV": 0, "sklejony tekst CV": 0, "słowa nie ma w danych": 0}
    missed_examples: list[str] = []
    for job_id, t0, must in jobs:
        words: list[str] = []
        for item in must:
            name = (
                ((item.get("name") if isinstance(item, dict) else str(item)) or "")
                .strip()
                .lower()
            )
            if not _SKILL_RE.fullmatch(name) or _term(name) is None:
                continue
            words.append(name)
            if len(words) == 3:
                break
        if len(words) < 2:
            continue
        positives = list(
            (
                await db.execute(
                    text(
                        "select distinct candidate_id from analytics_first_milestones "
                        "where job_id = :jid and stage in ('verified','cv_sent')"
                    ),
                    {"jid": job_id},
                )
            ).scalars()
        )
        if len(positives) < 2:
            continue
        hits = {w: await _hits_among(db, w, positives, t0) for w in words}
        cv_rows = {
            r.id: r.raw_cv_text
            for r in (
                await db.execute(
                    text("select id, raw_cv_text from candidates where id = any(:ids)"),
                    {"ids": positives},
                )
            ).all()
        }
        for pid in positives:
            stats["positives"] += 1
            in_profile = [pid in hits[w][0] for w in words]
            in_any = [pid in hits[w][0] or pid in hits[w][1] for w in words]
            per_row_total += len(words)
            per_row_hits += sum(in_any)
            if all(in_any):
                stats["and_all"] += 1
            if all(in_profile):
                stats["and_without_notes"] += 1
            if any(in_any):
                stats["any_row"] += 1
            stats["notes_only_rows"] += sum(
                1 for p, a in zip(in_profile, in_any) if a and not p
            )
            if not all(in_any):
                cv = cv_rows.get(pid) or ""
                if not cv.strip():
                    reasons["brak tekstu CV"] += 1
                elif looks_glued(cv):
                    reasons["sklejony tekst CV"] += 1
                else:
                    reasons["słowa nie ma w danych"] += 1
                    if len(missed_examples) < 12:
                        miss = [w for w, a in zip(words, in_any) if not a]
                        missed_examples.append(
                            f"rekrutacja {job_id}, kandydat {pid}: {miss}"
                        )
        used += 1
        if used >= max_jobs:
            break
    p = stats["positives"]
    print(
        f"Rekrutacje: {used}; osoby zweryfikowane lub wysłane klientowi: {p}. "
        "Wiersze = do 3 pierwszych must-have; notatki liczone tylko sprzed otwarcia "
        "rekrutacji (bez przecieku z samego procesu). Dane profilu są dzisiejsze.\n"
    )
    print("| miara | osób | udział |")
    print("|---|---:|---:|")
    print(
        f"| Spełnia WSZYSTKIE wiersze (tak szuka lista) | {stats['and_all']} | {_pct(stats['and_all'], p)} |"
    )
    print(
        f"| …bez notatek | {stats['and_without_notes']} | {_pct(stats['and_without_notes'], p)} |"
    )
    print(
        f"| Spełnia co najmniej jeden wiersz | {stats['any_row']} | {_pct(stats['any_row'], p)} |"
    )
    print(
        f"| Trafienia wiersz × osoba | {per_row_hits} z {per_row_total} | {_pct(per_row_hits, per_row_total)} |"
    )
    print(
        f"| …z tego tylko dzięki notatkom | {stats['notes_only_rows']} | {_pct(stats['notes_only_rows'], per_row_hits)} |"
    )
    print("\nOsoby, których wszystkie wiersze nie znajdują — dlaczego:\n")
    print("| przyczyna | osób |")
    print("|---|---:|")
    for label, value in reasons.items():
        print(f"| {label} | {value} |")
    if missed_examples:
        print("\nPróbka „słowa nie ma w danych” (do ręcznego sprawdzenia):\n")
        for line in missed_examples:
            print(f"- {line}")


# --- 7. API -------------------------------------------------------------------


async def part_api(db) -> None:
    import httpx

    from app.core.security import create_access_token

    print("\n## 7. API na żywo (bieżąca konfiguracja przełączników)\n")
    admin = (
        await db.execute(
            text(
                "select id, authorization_version from users "
                "where role = 'admin' and is_active order by id limit 1"
            )
        )
    ).one()
    token = create_access_token(
        admin.id,
        "admin",
        expires_delta=timedelta(minutes=15),
        roles=["admin"],
        authorization_version=admin.authorization_version,
    )
    job = (
        await db.execute(
            text(
                """
        select id, must_skills from jobs
        where status = 'published'
          and (case when jsonb_typeof(must_skills)='array'
                    then jsonb_array_length(must_skills) else 0 end) >= 2
        order by id desc limit 1"""
            )
        )
    ).one_or_none()
    headers = {"Authorization": f"Bearer {token}"}
    base = "http://127.0.0.1:8000"
    v2 = [("semantics_version", "2"), ("page_size", "50")]

    def must_rows(limit: int) -> list[tuple[str, str]]:
        if job is None:
            return []
        out = []
        for item in job.must_skills:
            name = (item.get("name") if isinstance(item, dict) else str(item)) or ""
            if name.strip():
                out.append(("q_any_group", name.strip()))
            if len(out) == limit:
                break
        return out

    scenarios: list[tuple[str, list[tuple[str, str]]]] = [
        ("bez filtra", v2),
        ("java", v2 + [("q_any_group", "java")]),
        (
            "java + spring + sql",
            v2
            + [
                ("q_any_group", "java"),
                ("q_any_group", "spring"),
                ("q_any_group", "sql"),
            ],
        ),
        ("c#", v2 + [("q_any_group", "c#")]),
        ("java|kotlin (wiersz z wariantem)", v2 + [("q_any_group", "java|kotlin")]),
        (
            "java + Warszawa",
            v2 + [("q_any_group", "java"), ("location_cities", "Warszawa")],
        ),
        ("java, wyklucz junior", v2 + [("q_any_group", "java"), ("q_none", "junior")]),
        ("scrum w notatkach", v2 + [("q_any_group", "scrum"), ("q_scope", "notes")]),
        ("java sort=match", v2 + [("q_any_group", "java"), ("sort", "match")]),
        (
            "java sort=match str. 2",
            v2 + [("q_any_group", "java"), ("sort", "match"), ("page", "2")],
        ),
    ]
    if job is not None:
        manual = [
            ("recruitment_id", str(job.id)),
            ("recruitment_match", "not_assigned"),
            ("sort", "match"),
        ]
        scenarios += [
            (f"Szukaj ręcznie #{job.id}, bez wymagań", v2 + manual),
            (
                f"Szukaj ręcznie #{job.id}, must-have jako wiersze",
                v2 + manual + must_rows(2),
            ),
        ]
    print("| scenariusz | osób | sort_applied | 1. zapytanie ms | 2. zapytanie ms |")
    print("|---|---:|---|---:|---:|")
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60) as client:
        for label, params in scenarios:
            times, body = [], {}
            for _ in range(2):
                started = time.perf_counter()
                resp = await client.get("/api/candidates", params=params)
                times.append((time.perf_counter() - started) * 1000)
                body = (
                    resp.json()
                    if resp.status_code == 200
                    else {"error": resp.status_code}
                )
            print(
                f"| {label} | {body.get('total', body.get('error'))} "
                f"| {body.get('sort_applied', '—')} | {times[0]:.0f} | {times[1]:.0f} |",
                flush=True,
            )
        print("\nGórne pole — zamiana na wiersze wymagań:\n")
        print("| wpisano | technologie | jako wiersze |")
        print("|---|---|---|")
        for q in (
            "java spring",
            "Kowalski",
            "Kraków",
            "react typescript",
            "java developer",
        ):
            resp = await client.get(
                "/api/candidates/keywords/classify", params={"q": q}
            )
            data = resp.json() if resp.status_code == 200 else {}
            print(f"| {q} | {data.get('skills')} | {data.get('as_requirements')} |")
        if job is not None:
            resp = await client.get(
                "/api/candidates", params=v2[:1] + [("page_size", "20")] + manual
            )
            ids = [item["id"] for item in resp.json().get("items", [])]
            scores_resp = await client.post(
                "/api/search/candidates/scores",
                json={"job_id": job.id, "candidate_ids": ids},
            )
            scores = (
                scores_resp.json().get("scores", {})
                if scores_resp.status_code == 200
                else {}
            )
            seq = [scores.get(str(i)) for i in ids]
            measured = [s for s in seq if s is not None]
            pairs = list(zip(measured, measured[1:]))
            ordered = sum(1 for x, y in pairs if x >= y)
            print(
                f"\nZgodność „Szukaj ręcznie” (sort=match) z kolumną „Dop.” "
                f"(rekrutacja #{job.id}, 20 pierwszych): policzone {len(measured)}/{len(ids)}, "
                f"pary w kolejności malejącej {ordered}/{len(pairs)}. Wyniki: {seq}"
            )


# --- 8. Szum krótkich i wieloznacznych słów ----------------------------------

NOISE_WORDS: tuple[str, ...] = (
    "sap",
    "go",
    "r",
    "c",
    "ai",
    "bi",
    "qa",
    "pm",
    "ba",
    "ml",
    "it",
    "erp",
    "crm",
    "js",
    "rest",
    "spring",
    "swift",
    "rust",
    "ruby",
    "ada",
    "net",
)
NOISE_SAMPLE = 40
_NOISE_CONTEXT = re.compile(r"@|https?:|www\.|\.(?:pl|com|php|html?)\b", re.I)


async def part_noise(db) -> None:
    print("\n## 8. Szum krótkich i wieloznacznych słów (nowa ścieżka)\n")
    print(
        f"Próbka {NOISE_SAMPLE} losowych trafień na słowo. „W CV” = słowo stoi w tekście "
        "CV; „adres/link” = najbliższe sąsiedztwo w CV to e-mail, link albo nazwa pliku; "
        "„gdzie indziej” = tylko notatki albo inne pole profilu. Konteksty do przejrzenia "
        "ręcznego pod tabelą.\n"
    )
    print("| słowo | osób | w CV | adres/link | gdzie indziej | przykładowy kontekst |")
    print("|---|---:|---:|---:|---:|---|")
    examples: list[str] = []
    for word in NOISE_WORDS:
        if _term(word) is None or not re.fullmatch(r"[a-z0-9]+", word):
            print(f"| {word} | — | nie da się szukać jako słowa | | | |")
            continue
        hits = await _new(db, word)
        sample = sorted(hits)[:: max(len(hits) // NOISE_SAMPLE, 1)][:NOISE_SAMPLE]
        rows = (
            await db.execute(
                text(
                    "select id, substring(raw_cv_text from :rx) as ctx "
                    "from candidates where id = any(:ids)"
                ),
                {"rx": rf"(?i).{{0,40}}\m{word}\M.{{0,40}}", "ids": sample},
            )
        ).all()
        in_cv = [r for r in rows if r.ctx]
        noisy = [r for r in in_cv if _NOISE_CONTEXT.search(r.ctx)]
        first = next((r.ctx for r in in_cv if not _NOISE_CONTEXT.search(r.ctx)), "")
        clean = " ".join(first.split()).replace("|", "/")[:90]
        print(
            f"| {word} | {len(hits)} | {len(in_cv)}/{len(rows)} | {len(noisy)} "
            f"| {len(rows) - len(in_cv)} | {clean} |",
            flush=True,
        )
        for r in in_cv[:4]:
            ctx = " ".join(r.ctx.split()).replace("|", "/")[:100]
            examples.append(f"- `{word}` kandydat {r.id}: {ctx}")
    print("\nKonteksty (po 4 na słowo):\n")
    print("\n".join(examples))


# --- 9. Zgodność liczb: podpowiedź vs lista ------------------------------------


async def part_counts(db) -> None:
    from app.services import keyword_corpus, keyword_suggest

    print("\n## 9. Zgodność liczby w podpowiedzi z wynikiem wyszukiwania\n")
    print(
        "Podpowiedź pokazuje „N osób” przy słowie. Lista liczy wszystkich z filtrem "
        "słowa (tu bez innych filtrów). Różnica > 0 znaczy, że podpowiedź obiecuje "
        "coś innego niż lista.\n"
    )
    words = ["java", "python", "c#", "scrum", "kraków", "bankowość", "spring boot"]
    print(
        "| słowo | podpowiedź (stara) | lista (stara) | podpowiedź (nowa) | lista (nowa) |"
    )
    print("|---|---:|---:|---:|---:|")
    from app.services.advanced_candidate_search import _whole_word_match

    for word in words:
        row = []
        for folded in (False, True):
            keyword_suggest.clear_count_cache()
            with keyword_corpus.force_folded_search(folded):
                counts = await keyword_suggest.count_candidates(db, [word])
                ids, _ = await _ids(db, _whole_word_match(_term(word), "all"))
            row += [counts.get(word), len(ids)]
        print(f"| {word} | {row[0]} | {row[1]} | {row[2]} | {row[3]} |", flush=True)


# --- 10. Filtry a osoby, które zespół naprawdę wybrał ---------------------------


async def part_filters(db) -> None:
    from app.services.keyword_suggest import fold

    print("\n## 10. Filtry a osoby zweryfikowane lub wysłane klientowi\n")
    rows = (
        await db.execute(
            text(
                """
        select distinct on (m.candidate_id, m.job_id)
               m.candidate_id, j.rate_budget_hourly as budget, j.location as job_loc,
               cast(j.work_mode as text) as work_mode,
               c.expected_rate_hourly as rate, c.city, c.location,
               c.availability_date, cast(c.availability_status as text) as avail
        from analytics_first_milestones m
        join jobs j on j.id = m.job_id
        join candidates c on c.id = m.candidate_id
        where m.stage in ('verified','cv_sent')
          and m.first_reached_at > now() - interval '12 months'"""
            )
        )
    ).all()
    total = len(rows)
    with_budget = [r for r in rows if r.budget]
    rate_known = [r for r in with_budget if r.rate is not None]
    over = [r for r in rate_known if float(r.rate) > float(r.budget)]
    over10 = [r for r in rate_known if float(r.rate) > float(r.budget) * 1.1]
    onsite = [r for r in rows if r.job_loc and (r.work_mode or "").lower() != "remote"]
    city_known = [r for r in onsite if (r.city or r.location)]
    city_match = [
        r
        for r in city_known
        if fold((r.city or r.location or "").split(",")[0]).strip()
        and fold((r.city or r.location or "").split(",")[0]).strip() in fold(r.job_loc)
    ]
    avail_known = [r for r in rows if r.availability_date is not None]
    print(f"Pary (osoba × rekrutacja) z ostatnich 12 miesięcy: {total}.\n")
    print("| sprawdzenie | osób | udział |")
    print("|---|---:|---:|")
    print(
        f"| Rekrutacja ma budżet PLN/h | {len(with_budget)} | {_pct(len(with_budget), total)} |"
    )
    print(
        f"| …osoba ma stawkę w profilu | {len(rate_known)} | {_pct(len(rate_known), len(with_budget))} |"
    )
    print(
        f"| …stawka powyżej budżetu (filtr „do budżetu” by ją ukrył) | {len(over)} | {_pct(len(over), len(rate_known))} |"
    )
    print(
        f"| …stawka > budżet + 10% | {len(over10)} | {_pct(len(over10), len(rate_known))} |"
    )
    print(
        f"| Rekrutacja z miastem, nie zdalna | {len(onsite)} | {_pct(len(onsite), total)} |"
    )
    print(
        f"| …osoba ma miasto | {len(city_known)} | {_pct(len(city_known), len(onsite))} |"
    )
    print(
        f"| …miasto osoby jest w lokalizacji rekrutacji | {len(city_match)} | {_pct(len(city_match), len(city_known))} |"
    )
    print(
        f"| Osoba ma datę dostępności | {len(avail_known)} | {_pct(len(avail_known), total)} |"
    )
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r.avail or "—"] = statuses.get(r.avail or "—", 0) + 1
    print("\nStatus dostępności w profilu tych osób (dziś):\n")
    print("| status | osób |")
    print("|---|---:|")
    for key, value in sorted(statuses.items(), key=lambda kv: -kv[1]):
        print(f"| {key} | {value} |")
    await _prefill_narrowing(db)


async def _prefill_narrowing(db) -> None:
    """Filtry, które „Szukaj ręcznie” dokłada sam (ManualSearchPanel.jobListFilters):
    status aktywny/pasywny, kategoria kompetencji rekrutacji, miasto rekrutacji
    (poza pracą w pełni zdalną). Ilu wybranych przez zespół by wycięły?"""
    from app.services.keyword_suggest import fold

    rows = (
        await db.execute(
            text(
                """
        select distinct on (m.candidate_id, m.job_id)
               cast(c.status as text) as status,
               j.competence_category_id as job_cc,
               (c.competence_category_id = j.competence_category_id
                or exists (select 1 from candidate_competence_categories x
                           where x.candidate_id = c.id
                             and x.competence_category_id = j.competence_category_id))
                 as cc_ok,
               j.location as job_loc, cast(j.remote_policy as text) as remote,
               c.city, c.location
        from analytics_first_milestones m
        join jobs j on j.id = m.job_id
        join candidates c on c.id = m.candidate_id
        where m.stage in ('verified','cv_sent')
          and m.first_reached_at > now() - interval '12 months'"""
            )
        )
    ).all()
    total = len(rows)
    status_out = [r for r in rows if r.status not in ("active", "passive")]
    with_cc = [r for r in rows if r.job_cc]
    cc_out = [r for r in with_cc if not r.cc_ok]
    city_rows = [r for r in rows if r.job_loc and (r.remote or "") != "remote"]

    def cities(value: str) -> set[str]:
        return {
            fold(part).strip()
            for part in re.split(r"[,/;|+]| i | lub |\(|\)", value or "")
            if fold(part).strip()
        }

    country_words = {"polska", "poland", "pl", "cala polska"}
    city_out, country_out, country_rows = [], [], 0
    for r in city_rows:
        own = fold((r.city or r.location or "").split(",")[0]).strip()
        wanted = cities(r.job_loc)
        is_country = bool(wanted) and wanted <= country_words | {
            w for w in wanted if "lokaliz" in w or "obowiaz" in w
        }
        country_rows += is_country
        if own and own not in wanted:
            city_out.append(r)
            if is_country:
                country_out.append(r)
    any_out = {id(r) for r in status_out + cc_out + city_out}
    print("\nFiltry dokładane po cichu przez „Szukaj ręcznie”:\n")
    print("| filtr | wycina wybranych przez zespół | udział |")
    print("|---|---:|---:|")
    print(
        f"| status aktywny/pasywny | {len(status_out)} z {total} | {_pct(len(status_out), total)} |"
    )
    print(
        f"| kategoria kompetencji rekrutacji | {len(cc_out)} z {len(with_cc)} | {_pct(len(cc_out), len(with_cc))} |"
    )
    print(
        f"| miasto rekrutacji (znane inne miasto) | {len(city_out)} z {len(city_rows)} | {_pct(len(city_out), len(city_rows))} |"
    )
    print(
        f"| …w tym rekrutacje z lokalizacją „Polska” (kraj czytany jak miasto) "
        f"| {len(country_out)} z {country_rows} | {_pct(len(country_out), country_rows)} |"
    )
    print(
        f"| którykolwiek z trzech | {len(any_out)} z {total} | {_pct(len(any_out), total)} |"
    )
    by_status: dict[str, int] = {}
    for r in status_out:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    if by_status:
        print(f"\nStatusy wyciętych: {by_status}")


async def main(args) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus

    keyword_corpus.mark_ready(True)
    only = {int(x) for x in args.only.split(",")} if args.only else set(range(1, 11))
    started = time.time()
    print("# Badanie wyszukiwania ręcznego\n")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL statement_timeout = '180s'"))
        if 1 in only:
            await part_data(db)
        if 2 in only:
            await part_compare(db, list(DEFAULT_WORDS))
        if 3 in only:
            await part_sources(db)
        if 4 in only:
            await part_variants(db)
        if 5 in only:
            await part_inflection(db)
        if 6 in only:
            await part_history(db, args.jobs)
        if 8 in only:
            await part_noise(db)
        if 9 in only:
            await part_counts(db)
        if 10 in only:
            await part_filters(db)
        if 7 in only and args.api:
            await part_api(db)
    print(f"\n_Czas badania: {time.time() - started:.0f} s._")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--only", default="")
    parser.add_argument("--jobs", type=int, default=120)
    asyncio.run(main(parser.parse_args()))
