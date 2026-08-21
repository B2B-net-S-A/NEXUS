"""Sonda kolacji bazy — porządek sortowania tekstu jako fakt, nie domysł.

Kolacja, według której ten ATS porównuje polskie nazwiska, nazwy klientów
i nazwy etapów pipeline'u, jest wybierana NIEJAWNIE przez jeden tag obrazu
w `docker-compose.yml` (`postgres:16-alpine` = musl, nie glibc). Do tej pory
nic w kodzie jej nie czytało: grep za `lc_collate|datcollate|pg_collation`
po `app`, `alembic` i `tests` nie zwracał nic, `admin_schema_drift` jej nie
sprawdzał, a `/api/health/deep` sondował 42 tabele i ani jednej kolacji.

Dwa fakty, przez które „po prostu sprawdź kolację" nie działa:

1. **Katalog kłamie.** `postgres:16-alpine` i `postgres:16` raportują ten sam
   `datcollate = en_US.utf8`, a mimo to `'Łukasz' < 'Zbigniew'` jest FAŁSZEM
   na pierwszym i PRAWDĄ na drugim. Dlatego odciskiem palca nie jest sama
   nazwa kolacji, tylko `datlocprovider` + ŻYWE porównanie.
2. **Bezpiecznik PostgreSQL tu nie wystrzeli.** Ostrzeżenie „collation version
   mismatch, rebuild indexes" wymaga zapisanej, NIEPUSTEJ wersji kolacji —
   a pod musl `datcollversion` jest pusty. Podmiana obrazu na istniejącym
   wolumenie przestawiłaby więc porządek każdego btree na kolumnie tekstowej
   BEZ JEDNEJ LINIJKI w logu: skany po indeksie zaczęłyby gubić wiersze,
   a UNIQUE na tekście przestałby łapać duplikaty.

Stąd ta sonda: `/api/health/deep` porównuje odcisk palca żywej bazy z
BASELINE zapisanym niżej. Dziś jest zielona (baseline = to, co realnie stoi
na prodzie i w CI), a czerwienieje dokładnie wtedy, gdy ktoś podmieni obraz
albo odtworzy wolumen z inną kolacją — czyli w jedynym momencie, w którym
trzeba przeczytać ten komentarz i uruchomić `REINDEX DATABASE`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

#: Żywy odczyt: nazwa kolacji, provider, wersja kolacji ORAZ porównanie
#: sprawdzające, czy litery spoza ASCII sortują się po polsku. `datcollversion`
#: bywa NULL (musl) — COALESCE do pustego stringu, żeby porównanie odcisku
#: palca nie zależało od różnicy NULL vs ''.
COLLATION_PROBE_SQL = text(
    """
    SELECT
        d.datcollate            AS datcollate,
        d.datctype              AS datctype,
        d.datlocprovider::text  AS datlocprovider,
        COALESCE(d.datcollversion, '') AS datcollversion,
        ('Ł' < 'Z')             AS polish_order_ok
    FROM pg_database AS d
    WHERE d.datname = current_database()
    """
)

#: Odcisk palca zmierzony na `postgres:16-alpine` (prod + serwis CI).
#: `datcollate` CELOWO nie wchodzi do porównania — jest identyczny na obu
#: obrazach, więc jako sygnał dryfu jest bezwartościowy; raportujemy go tylko
#: informacyjnie. Znaczenie ma provider, obecność wersji kolacji i realny
#: wynik porównania.
BASELINE_FINGERPRINT: dict[str, Any] = {
    "datlocprovider": "c",
    "has_collation_version": False,
    "polish_order_ok": False,
}


def fingerprint(row: dict[str, Any]) -> dict[str, Any]:
    """Sprowadź surowy odczyt do trzech cech, które faktycznie decydują
    o porządku indeksów btree."""
    return {
        "datlocprovider": (row.get("datlocprovider") or "").strip(),
        "has_collation_version": bool((row.get("datcollversion") or "").strip()),
        "polish_order_ok": bool(row.get("polish_order_ok")),
    }


def evaluate(row: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """(czy zgodne z baseline, raport diagnostyczny do ciała odpowiedzi).

    Rozjazd NIE oznacza „nowa baza jest gorsza" — oznacza „porządek tekstu
    zmienił się względem tego, w jakim zbudowano istniejące indeksy". Jedno
    i drugie wymaga decyzji człowieka (`REINDEX DATABASE` albo świadoma
    aktualizacja baseline w tym pliku), więc sonda ma być czerwona.
    """
    observed = fingerprint(row)
    report: dict[str, Any] = {
        "datcollate": row.get("datcollate"),
        "datctype": row.get("datctype"),
        "datlocprovider": observed["datlocprovider"],
        "collation_version": (row.get("datcollversion") or "") or None,
        # Nazwane po tym, co realnie mierzy: czy 'Ł' sortuje się PRZED 'Z'
        # (glibc/ICU) czy po nim (musl, porównanie bajtowe).
        "polish_order_ok": observed["polish_order_ok"],
        "matches_baseline": observed == BASELINE_FINGERPRINT,
        "baseline": BASELINE_FINGERPRINT,
    }
    return report["matches_baseline"], report
