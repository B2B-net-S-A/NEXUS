"""Dzienniki kolejki kosztów jak w eBI24 (22.11.2026).

eBI24 trzymało faktury w folderach-dziennikach: „Przychody”, „Kontraktorzy”,
„Zakupy pozostałe”, „BENEFITY” i „BIURO”. Artur wybrał cztery dzienniki
(przychody, kontraktorzy, zakupy pozostałe, biuro); przychody są w Księgowość →
„Źródła”, więc kolejka „Koszty” ma trzy. Dziennik nie jest zapisany — wynika
z kategorii wpisu (``CATEGORY_JOURNAL``), więc zmiana kategorii przenosi
fakturę do innego dziennika, a reguła dekretu (wybierana po kategorii) zostaje
spójna z dziennikiem.

Kategoria nowej faktury: faktura osoby zespołu i kontraktora klienta mają ją ze
źródła (Zespół, Kontraktorzy). Dokument wydatku dostawał „Biuro” z góry, a na
kopii produkcji z 19.11.2026 3 229 z 4 849 takich dokumentów eBI24 trzymało
w „Kontraktorach”, a tylko 216 w „BIURZE”; folder w eBI24 zależał wyłącznie od
sprzedawcy (710 sprzedawców, żaden w dwóch folderach). Dlatego
``suggest_categories`` podpowiada kategorię dokumentu wydatku z historii
sprzedawcy: najpierw ręcznie zmieniona kategoria jego wcześniejszej faktury
w NEXUSIE, potem folder jego ostatniej faktury w archiwum eBI24. Podpowiedź
dotyczy tylko wpisów nietkniętych (poczekalnia albo „Do opisu”, bez dekretu,
bez wcześniejszej zmiany kategorii) i zostaje w historii wpisu jako zmiana
kategorii bez osoby, ze źródłem.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

JOURNALS: tuple[str, ...] = ("contractors", "purchases", "office")
JOURNAL_LABELS: dict[str, str] = {
    "contractors": "Kontraktorzy",
    "purchases": "Zakupy pozostałe",
    "office": "Biuro",
}
#: Kategoria wpisu → dziennik. Faktury osób zespołu (B2B) są w „Kontraktorach”
#: jak w eBI24 (folder osób na B2B); „Benefity” nie mają już osobnego dziennika
#: (Artur wybrał cztery), idą do „Zakupów pozostałych”.
CATEGORY_JOURNAL: dict[str, str] = {
    "contractor": "contractors",
    "team": "contractors",
    "office": "office",
    "benefit": "purchases",
    "proforma": "purchases",
    "other": "purchases",
}
#: Folder eBI24 → kategoria podpowiadana dokumentowi wydatku.
EBI24_FOLDER_CATEGORY: dict[str, str] = {
    "Kontraktorzy": "contractor",
    "Zakupy pozostałe": "other",
    "BIURO": "office",
    "BENEFITY": "benefit",
}
SUGGESTION_SOURCES: dict[str, str] = {
    "history": "NEXUS — jak wcześniejsza faktura sprzedawcy",
    "ebi24": "NEXUS — dziennik sprzedawcy w eBI24",
}


def journal_of(category: str) -> str:
    return CATEGORY_JOURNAL.get(category, "purchases")


def categories_of(journal: str) -> tuple[str, ...]:
    return tuple(
        category for category, target in CATEGORY_JOURNAL.items() if target == journal
    )


def label_of(journal: Optional[str]) -> Optional[str]:
    return JOURNAL_LABELS.get(journal or "")


def _folder_case() -> str:
    whens = " ".join(
        f"WHEN '{folder}' THEN '{category}'"
        for folder, category in EBI24_FOLDER_CATEGORY.items()
    )
    return f"CASE a.folder {whens} END"


#: Wpisy, którym wolno podpowiedzieć kategorię: dokument wydatku, nietknięty.
_UNTOUCHED = (
    "e.source_type = 'approval_document' AND e.stage IN ('received', 'new') "
    "AND e.decree IS NULL AND e.batch_id IS NULL AND e.seller_nip IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM finance_cost_entry_events v "
    "WHERE v.entry_id = e.id AND v.action = 'category')"
)

#: Ostatnia ręczna zmiana kategorii u tego samego sprzedawcy (inny wpis).
_FROM_HISTORY = f"""
WITH picked AS (
    SELECT DISTINCT ON (e.id) e.id, e.category AS before, v.detail->>'to' AS after
    FROM finance_cost_entries e
    JOIN finance_cost_entries o
      ON o.seller_nip = e.seller_nip AND o.id <> e.id
    JOIN finance_cost_entry_events v
      ON v.entry_id = o.id AND v.action = 'category' AND v.actor_id IS NOT NULL
    WHERE {_UNTOUCHED}
    ORDER BY e.id, v.created_at DESC, v.id DESC
), changed AS (
    UPDATE finance_cost_entries e SET category = p.after
    FROM picked p
    WHERE e.id = p.id AND p.after IN ({", ".join(f"'{c}'" for c in CATEGORY_JOURNAL)})
      AND p.after <> p.before
    RETURNING e.id, p.before, p.after
)
INSERT INTO finance_cost_entry_events (entry_id, action, detail, actor_id, created_at)
SELECT id, 'category',
       jsonb_build_object('from', before, 'to', after, 'source', 'history'),
       NULL, now()
FROM changed
"""

#: Folder ostatniej faktury sprzedawcy w archiwum eBI24 (NIP z kartoteki eBI24).
_FROM_EBI24 = f"""
WITH archive AS (
    SELECT DISTINCT ON (nip) nip, folder
    FROM (
        SELECT regexp_replace(
                   upper(coalesce(meta->'_partner'->>'officialId', '')),
                   '^PL|[^0-9]', '', 'g') AS nip,
               folder, coalesce(issue_date, document_date) AS day, id
        FROM finance_archive_documents
        WHERE kind = 'cost' AND folder IN (
            {", ".join(f"'{folder}'" for folder in EBI24_FOLDER_CATEGORY)})
    ) t
    WHERE length(nip) = 10
    ORDER BY nip, day DESC NULLS LAST, id DESC
), picked AS (
    SELECT e.id, e.category AS before, {_folder_case()} AS after, a.folder
    FROM finance_cost_entries e
    JOIN archive a ON a.nip = e.seller_nip
    WHERE {_UNTOUCHED}
      -- Ręczna decyzja Finansów u tego sprzedawcy wygrywa z eBI24, także gdy
      -- zostawiła kategorię domyślną.
      AND NOT EXISTS (
          SELECT 1 FROM finance_cost_entries o
          JOIN finance_cost_entry_events s
            ON s.entry_id = o.id AND s.action = 'category' AND s.actor_id IS NOT NULL
          WHERE o.seller_nip = e.seller_nip AND o.id <> e.id)
), changed AS (
    UPDATE finance_cost_entries e SET category = p.after
    FROM picked p
    WHERE e.id = p.id AND p.after <> p.before
    RETURNING e.id, p.before, p.after, p.folder
)
INSERT INTO finance_cost_entry_events (entry_id, action, detail, actor_id, created_at)
SELECT id, 'category',
       jsonb_build_object('from', before, 'to', after, 'source', 'ebi24',
                          'folder', folder),
       NULL, now()
FROM changed
"""


async def suggest_categories(db: AsyncSession) -> None:
    """Kategoria nietkniętych dokumentów wydatków z historii sprzedawcy.

    Najpierw NEXUS (ręczna decyzja Finansów wygrywa), potem archiwum eBI24.
    Woła go ``costs.catch_up`` na końcu każdego przebiegu KSeF.
    Wpis z podpowiedzią ma zdarzenie ``category``, więc kolejny przebieg go
    nie rusza — także gdy archiwum się zmieni.
    """

    await db.execute(text(_FROM_HISTORY))
    await db.execute(text(_FROM_EBI24))
