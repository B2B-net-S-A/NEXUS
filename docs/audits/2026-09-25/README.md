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
| 5 | `8da65ef74` | 1 wysokie, 1 średnio-wysokie, 2 średnie, 4 niskie (1 luka poprawek r4) | PR #1849 | [runda-5.md](runda-5.md) (w PR #1849) |

Reguły, które wynikły z napraw (i których nie wolno cofnąć „przy okazji”), są w `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie” z podsekcjami „Runda 2”, „Runda 3”, „Runda 4”.

## Co się powtarza (przeczytaj przed kolejnym audytem albo poprawką)

1. **Bliźniacza ścieżka.** Poprawka trafia w jedną ścieżkę, a ta sama reguła żyje w drugiej (bulk-add → `/from-linkedin` → wskazanie osoby przy ruchu karty; podium → numeracja listy → `/my-position`). Przy każdej poprawce grep wzorca w całym `app/`.
2. **Nowy stan bez domknięcia.** Poprawka wprowadza znacznik, migawkę albo status, który ktoś inny czyta albo powinien czyścić (znacznik czekającego rozwiązania umowy, migawka progów, `dismissed_from`). Przy każdym nowym stanie: kto go ustawia, kto czyści, kto czyta.
3. **Nieaktywne konto = brak osoby — wszędzie.** Osoba od Cpro, przypisania requestów, follow-upy, DL rekrutacji. Każda nowa rola „osoby odpowiedzialnej” musi pomijać `is_active = false`.
4. **Logika trójwartościowa SQL.** Klauzula z `->>` użyta z negacją (`~`) bez `coalesce` wyrzuca wiersze po cichu.
5. **Daty: kalendarz firmy.** „Dziś”, „poniedziałek”, rok numeracji — `business_today()` / Europe/Warsaw, nigdy UTC.
6. **Przegląd kodu po scaleniu agentów jest obowiązkowy.** W rundach 3 i 4 złapał odpowiednio 4 i 1 lukę w samych poprawkach, zanim trafiły na produkcję.
7. **Pułapki CI:** fikcyjny UUID w teście łapie gitleaks (`fireflies-api-key`) — buduj go w locie; skan PR obejmuje cały zakres commitów, więc poprawka w nowym commicie nie wystarcza. Testy z bazą padają lokalnie (brak Postgresa) — weryfikacja przez `gh workflow run CI --ref <gałąź>`.

## Świadomie zostawione (nie zgłaszaj ponownie bez nowego faktu)

- Martwy kod: routery `analytics_v1`, stary `/api/dashboard`, modele `dr_*` (decyzja Artura 25.09 — nie ruszać).
- CSP egzekwowane bez `script-src` (przejściowo, Report-Only zbiera raporty).
- Retencja `trainee_call_items` — to dziennik telefonów (reguły „niezainteresowany = nigdy”, „zły numer”).
- `SECRET_KEY` w historii gita — rotacja po stronie właściciela.
- Reguła „obecny kontrakt” bez zamówień w kilku miejscach (`api/contracts.py`, `contract_termination_sync.py`, `current_employment.py`, `custom_metrics/engine.py`).
- Przeskok „Zweryfikowany → Rozmowa u klienta / Umowa” bez QC CV i stawki DL — blokuje tylko front (decyzja Artura, runda 3).
- Mail alertów DL (`dl_alerts.py`) bez bramki wyciszeń; ręczne `/competitions/freeze` przed 3. dniem roboczym; numeracja `/monthly-races` po wyniku (tylko Liga ma `award_ranked_rows`); martwy zastępca Cpro = „nikt” nawet przy aktywnej osobie sprzed zastępstwa; przypięcia importu archiwum do pytań już istniejących w banku liczą się w ocenie prepu.

## Obszary sprawdzone i czyste (skrót — szczegóły w raportach rund)

- Uprawnienia trasa po trasie: ~40 plików API w rundzie 3 + 30 routerów w rundzie 4 (m.in. stawki, konta serwisowe, OAuth, struktura zespołu, MD, Insights DL, priority work, przydziały, portale, akademia, praktykant, follow-upy, QC, pulpit, Jarvis, Finanse, historia zdarzeń, usuwanie klientów). Kontrakt bramek sekcji `test_section_ceiling_contract.py`.
- Lustro DDL w `entrypoint.sh` vs migracje 0350–0384 (runda 5, skrypt porównujący).
- 65 pętli tła: heartbeat/`EXEMPT`, obsługa wyjątków, brak blokad wierszy w trakcie HTTP/modelu (runda 5).
- Powierzchnie publiczne i uwierzytelnianie: 41 tras bez logowania, auth/SSO/OAuth/klucze serwisowe/WebSocket/pliki/SSRF/CORS (runda 5).
- Wyszukiwanie kandydatów (wiersze wymagań, v1/v2, zapisane wyszukiwania, podpowiedzi) i import Traffita poza fazami plików/CV/enrich/workflows/sources/talents (runda 5).
