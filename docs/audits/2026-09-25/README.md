# Audyt NEXUS 25–26.09.2026 — wielorundowy

Seria audytów całej aplikacji. Każda runda: kilku agentów czyta kod tylko do odczytu, koordynator potwierdza znaleziska w kodzie (plik:linia), jeden PR naprawczy z testem na każdą pozycję, przegląd kodu po scaleniu gałęzi agentów, pełne CI, wdrożenie i sprawdzenie `/api/health`.

Te pliki są po to, żeby następny audyt **nie zaczynał od zera**: wiadomo, co już sprawdzono (sekcje „Sprawdzone i czyste”), co świadomie zostawiono i jakie błędy powtarzają się między rundami.

## Rundy

| Runda | Baza | Znaleziska | Naprawa | Raport |
|---|---|---|---|---|
| 1 | `eed680914` | 5 krytycznych, 11 wysokich, ~30 średnich + martwy kod | PR #1833 (`8d9755da2`) | [runda-1.md](runda-1.md) |
| 2 | `8d9755da2` | 1 krytyczne, 5 wysokich, 10 średnich, 3 niskie (15 z 19 to niekompletne poprawki r1) | PR #1836 (`9d85252d8`) | [runda-2.md](runda-2.md) |
| 3 | `9d85252d8` | 10 wysokich, 12 średnich, 9 niskich (1 regresja r2, reszta z nowych obszarów) | PR #1840 (`c72f411a4`) | [runda-3.md](runda-3.md) |
| 4 | `c72f411a4` | 10 wysokich, 16 średnich, 5 niskich (10 to luki poprawek r3) | PR #1844 (`8da65ef74`) | [runda-4.md](runda-4.md) |
| 5 | `8da65ef74` | 1 wysokie, 1 średnio-wysokie, 2 średnie, 4 niskie (1 luka poprawek r4) | PR #1849 | [runda-5.md](runda-5.md)  |
| 6 | `e2585b51c` | 1 krytyczne, 13 wysokich, 2 średnio-wysokie, ~50 średnich, ~35 niskich (19 agentów; 2 luki poprawek r5, reszta z obszarów dotąd nieaudytowanych i kodu po r5) | PR #1860 (`75ffa6ddb`) | [runda-6.md](runda-6.md) |
| 7 | `4e92bbc82` | 3 krytyczne + 1 opublikowane, 14 wysokich, ~45 średnich, ~30 niskich (20 agentów; 4 luki poprawek r6, w tym 2 regresje naprawione przed scaleniem #1860) | PR rundy 7 | [runda-7.md](runda-7.md) |

Reguły, które wynikły z napraw (i których nie wolno cofnąć „przy okazji”), są w `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie” z podsekcjami „Runda 2” … „Runda 7”.

## Co się powtarza (przeczytaj przed kolejnym audytem albo poprawką)

1. **Bliźniacza ścieżka.** Poprawka trafia w jedną ścieżkę, a ta sama reguła żyje w drugiej (bulk-add → `/from-linkedin` → wskazanie osoby przy ruchu karty; podium → numeracja listy → `/my-position`). Przy każdej poprawce grep wzorca w całym `app/`.
2. **Nowy stan bez domknięcia.** Poprawka wprowadza znacznik, migawkę albo status, który ktoś inny czyta albo powinien czyścić (znacznik czekającego rozwiązania umowy, migawka progów, `dismissed_from`). Przy każdym nowym stanie: kto go ustawia, kto czyści, kto czyta.
3. **Nieaktywne konto = brak osoby — wszędzie.** Osoba od Cpro, przypisania requestów, follow-upy, DL rekrutacji. Każda nowa rola „osoby odpowiedzialnej” musi pomijać `is_active = false`.
4. **Logika trójwartościowa SQL.** Klauzula z `->>` użyta z negacją (`~`) bez `coalesce` wyrzuca wiersze po cichu.
5. **Daty: kalendarz firmy.** „Dziś”, „poniedziałek”, rok numeracji — `business_today()` / Europe/Warsaw, nigdy UTC.
6. **Przegląd kodu po scaleniu agentów jest obowiązkowy.** W rundach 3 i 4 złapał odpowiednio 4 i 1 lukę w samych poprawkach, zanim trafiły na produkcję.
7. **Pułapki CI:** fikcyjny UUID w teście łapie gitleaks (`fireflies-api-key`) — buduj go w locie; skan PR obejmuje cały zakres commitów, więc poprawka w nowym commicie nie wystarcza. Testy z bazą padają lokalnie (brak Postgresa) — weryfikacja przez `gh workflow run CI --ref <gałąź>`.
8. **JSONB i `None`.** Kolumna JSONB bez `none_as_null=True` zapisuje JSON `null`; `IS NULL` go nie widzi.
9. **Retencja kasuje pamięć automatu.** Stan „już zrobione” nie może żyć wyłącznie w wierszach, które kasuje retencja.
10. **Zmiana strefy/parsera czasu rozjeżdża złączenia po dokładnym znaczniku** — grep każdego SQL-a łączącego po tym czasie.
11. **Walidacja po kluczu żądania zamiast po zmianie wartości** — formularze odsyłają komplet pól.
12. **Heurystyka „ostatnie/pierwsze z brzegu dopasowanie”** (podpis Outlooka, parsery PDF) — przy niejednoznaczności odmowa albo „do sprawdzenia”.
13. **Publiczne repo = publiczne logi Actions i artefakty**; logi aplikacji w Loki też bez nazwisk, nazw plików CV, sekretnych URL-i.
14. **CPU w `async def`** (tysiące wierszy w Pythonie) blokuje jedyny proces — `asyncio.to_thread` + single-flight.
15. **Skala audytu:** runda 6 szła 19 agentami audytu i 15 naprawczymi (każdy we własnym worktree, obszary rozłączne), potem scalenie i 4 przeglądy. Rozdzielanie obszarów tak, żeby agenci naprawczy nie dotykali tych samych plików, ograniczyło konflikty do stempli i jednego komentarza.
16. **Testy bez bazy puszczaj Z conftest, nie z `--noconftest`.** Conftest odpina ID klientów w bramkach (Polkomtel = −3), wyłącza cache rankingów i otwiera okna czasowe — test „zielony lokalnie” z `--noconftest` padł w CI 8 razy w rundzie 7.
17. **Regex w redakcji logów to powierzchnia ataku.** Lookahead po zachłannym kwantyfikatorze albo prefiks `(?:[a-z0-9]+[_-])*` = czas kwadratowy na tekście z żądania anonimowego; każdy nowy wzorzec z testem liniowości.
18. **Squash poprzedniej rundy vs historia w gałęzi następnej:** zanim scalisz main, potwierdź, że różnica między końcówką poprzedniej gałęzi a mainem to tylko PR-y spoza serii — wtedy konflikty rozstrzyga wersja gałęzi.

## Świadomie zostawione (nie zgłaszaj ponownie bez nowego faktu)

- **CV nie usuwamy nigdy, RODO pomijamy** (decyzja Artura 26.09.2026): pliki CV, wygenerowane CV i zgłoszenia z CV zostają także po usunięciu kandydata. Nie zgłaszaj „danych po usunięciu kandydata” jako błędu do naprawy kasowaniem.

- Martwy kod: routery `analytics_v1`, stary `/api/dashboard`, modele `dr_*` (decyzja Artura 25.09 — nie ruszać).
- CSP egzekwowane bez `script-src` (przejściowo, Report-Only zbiera raporty).
- Retencja `trainee_call_items` — to dziennik telefonów (reguły „niezainteresowany = nigdy”, „zły numer”).
- `SECRET_KEY` w historii gita — rotacja po stronie właściciela.
- Reguła „obecny kontrakt” bez zamówień w kilku miejscach (`api/contracts.py`, `contract_termination_sync.py`, `current_employment.py`, `custom_metrics/engine.py`).
- Przeskok „Zweryfikowany → Rozmowa u klienta / Umowa” bez QC CV i stawki DL — blokuje tylko front (decyzja Artura, runda 3).
- Mail alertów DL (`dl_alerts.py`) bez bramki wyciszeń; ręczne `/competitions/freeze` przed 3. dniem roboczym; numeracja `/monthly-races` po wyniku (tylko Liga ma `award_ranked_rows`); martwy zastępca Cpro = „nikt” nawet przy aktywnej osobie sprzed zastępstwa; przypięcia importu archiwum do pytań już istniejących w banku liczą się w ocenie prepu.

## Obszary sprawdzone i czyste (skrót — szczegóły w raportach rund)

- Runda 7: poprawki rundy 6 (A6, L1–L7, J1–J5, DL-01..05, IC-1/3, X1–X4, W1–W6, PERF, G1/G2), płacące konkursy nietknięte — szczegóły w [runda-7.md](runda-7.md).
- Runda 6: #1843 trasa po trasie, #1846/#1848, fazy Traffita (pliki, CV, tekst, enrich, cv_fields, workflows, sources, talents), dokumenty pochodne B2B i rejestr z Excela, scalanie kandydatów, RODO od końca do końca, rdzeń kontraktów, parsery PDF zamówień, MD i offboarding, M365, cykl rozmów i prepy, automaty rekrutacji, liczby Insights, wydajność pętli zdarzeń, logi/Sentry/workflowy, zakładanie rekrutacji, Finanse — szczegóły w [runda-6.md](runda-6.md).

- Uprawnienia trasa po trasie: ~40 plików API w rundzie 3 + 30 routerów w rundzie 4 (m.in. stawki, konta serwisowe, OAuth, struktura zespołu, MD, Insights DL, priority work, przydziały, portale, akademia, praktykant, follow-upy, QC, pulpit, Jarvis, Finanse, historia zdarzeń, usuwanie klientów). Kontrakt bramek sekcji `test_section_ceiling_contract.py`.
- Lustro DDL w `entrypoint.sh` vs migracje 0350–0384 (runda 5, skrypt porównujący).
- 65 pętli tła: heartbeat/`EXEMPT`, obsługa wyjątków, brak blokad wierszy w trakcie HTTP/modelu (runda 5).
- Powierzchnie publiczne i uwierzytelnianie: 41 tras bez logowania, auth/SSO/OAuth/klucze serwisowe/WebSocket/pliki/SSRF/CORS (runda 5).
- Wyszukiwanie kandydatów (wiersze wymagań, v1/v2, zapisane wyszukiwania, podpowiedzi) i import Traffita poza fazami plików/CV/enrich/workflows/sources/talents (runda 5).
