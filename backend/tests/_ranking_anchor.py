"""Wspólna kotwica rankingu dla testów analityki marży.

`margin-by-contractor` i `margin-by-client` kończą się tak::

    rows.sort(key=lambda x: x.total_monthly_margin, reverse=True)
    return rows[:limit]

czyli zwracają WYŁĄCZNIE okno top-N. Test, który zasiewa wiersz o niskiej marży
i szuka go potem w odpowiedzi, przechodzi na świeżej bazie i pada na bazie,
którą zapełniły inne pliki testowe. Baza testowa jest współdzielona i NIE jest
czyszczona, a podział na shardy w CI jest round-robinem po posortowanych
ścieżkach plików — więc dopisanie DOWOLNEGO nowego pliku testowego przestawia
partycję i decyduje, kiedy to wybuchnie. Wygląda jak losowa flaka, jest
deterministyczne; ten sam tryb awarii opisuje
``test_shared_test_helpers_are_not_copied.py``.

Reguła mieszka tutaj, a nie w plikach testowych, bo używają jej DWA pliki
(`test_contract_analytics_fx.py`, `test_contract_analytics.py`) i obowiązuje
tu ten sam zakaz kopiowania, co dla `pick_parties` i `calls_in`: rozjechane
kopie tej reguły dałyby czerwień WĘDRUJĄCĄ między shardami, czyli dokładnie
to, co ta reguła ma likwidować.

Dwie decyzje, które łatwo cofnąć „przy okazji":

* **Celujemy w PRÓG ODCIĘCIA, nie w maksimum.** To warunek wykonalności, nie
  optymalizacja: `test_raw_analytics` zasiewa 99 999 999 dziennie w EUR, co po
  normalizacji na miesiąc i przewalutowaniu daje ~9,4 mld — kotwica nad
  MAKSIMUM nie mieści się już w ``NUMERIC(16, 6)`` kolumny stawki
  (sprawdzone: przepełnienie przy zapisie ``rate_client``). Próg odcięcia jest
  o rzędy wielkości niższy (na realnej zapełnionej bazie: 50) i nie rośnie
  z pojedynczymi wartościami odstającymi.
* **`limit` jest WYMAGANY.** Endpointy bez ``?limit=`` zwracają 20 wierszy,
  a z ``?limit=100`` — sto. Kotwica policzona na innym oknie niż to, o które
  test potem pyta, jest cicho za mała: domyślna wartość zamieniłaby ten błąd
  w kolejną wędrującą flakę zamiast w błąd wywołania.
"""

from decimal import ROUND_CEILING, Decimal

__all__ = ["RATE_CEILING", "anchor_contract", "ranking_anchor"]

#: Sufit ``NUMERIC(16, 6)`` na ``contracts.rate_client`` — 10 cyfr przed przecinkiem.
RATE_CEILING = Decimal("9999999999")

#: Zapas nad progiem odcięcia. Sama nierówność ostra wystarcza (wiersz o marży
#: ponad progiem ma rangę co najwyżej N), ale odpowiedź wraca przez JSON-a jako
#: float — zapas zdejmuje z tej granicy zależność od zaokrąglenia.
_HEADROOM = Decimal("1000")


def _ranked_endpoints(limit: int) -> tuple[str, ...]:
    return (
        f"/api/contract-analytics/margin-by-contractor?limit={limit}",
        f"/api/contract-analytics/margin-by-client?limit={limit}",
    )


async def ranking_anchor(app_client, headers: dict, *, limit: int) -> Decimal:
    """Najmniejsza marża w PLN, która utrzyma zasiany wiersz w oknie top-N.

    ``limit`` MUSI być tym samym oknem, o które test pyta potem endpoint
    (bez ``?limit=`` jest to 20) — patrz docstring modułu.

    Niepełne okno (mniej wierszy niż ``limit``) znaczy, że nic nie wypada —
    wtedy wystarczy dowolna dodatnia marża, a kotwica i tak jest zasiewana,
    żeby kształt danych nie zależał od stanu bazy.
    """

    cutoff = Decimal("0")
    for path in _ranked_endpoints(limit):
        response = await app_client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        rows = response.json()
        if len(rows) < limit:
            continue
        cutoff = max(
            cutoff,
            min(Decimal(str(row["total_monthly_margin"])) for row in rows),
        )
    # Całkowita: kwoty analityki są w pełnych złotych (`to_whole_pln`), więc
    # kotwica nie może wnosić groszy, których wynik i tak by nie pokazał.
    anchor = (cutoff + _HEADROOM).to_integral_value(rounding=ROUND_CEILING)
    assert anchor < RATE_CEILING, (
        f"próg odcięcia rankingu urósł do {cutoff} — kotwica {anchor} nie "
        f"zmieści się w NUMERIC(16, 6). Ktoś zasiał setki wierszy o marżach "
        f"bliskich sufitowi kolumny; to trzeba naprawić u źródła, a nie "
        f"podbijaniem kotwicy."
    )
    return anchor


def anchor_contract(*, candidate_id: int, client_id: int, margin: Decimal):
    """Kontrakt w PLN, którego JEDYNYM zadaniem jest ranking.

    Czysto złotówkowy, więc nie może zamaskować błędu przewalutowania. Bez nogi
    kosztowej, żeby wnosił DOKŁADNIE ``margin`` przychodu i ``margin`` marży —
    wołający dodaje tę jedną liczbę do oczekiwań, a właściwością dowodzoną
    w teście zostaje to, ile (nic albo znana kwota) dokłada obok niego noga
    walutowa.

    Bez ``job_id``: rola w ``role-client-mix`` liczy się wtedy z
    ``candidate.competence_category``, więc kotwica nie zakłada nowego kubełka
    roli obok tego, o który pyta test.
    """

    from datetime import date

    from app.models.contract import Contract, ContractStatus

    return Contract(
        candidate_id=candidate_id,
        client_id=client_id,
        status=ContractStatus.active,
        start_date=date(2025, 1, 1),
        end_date=None,
        rate_client=margin,
        rate_candidate=Decimal("0"),
        currency="PLN",
    )
