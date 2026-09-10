# Synchronizacja kontrakt ↔ zamówienia — raport z realizacji (09.2026)

Ticket: kontrakt tworzony jako Aktywny po podpisie obustronnym, pełna
dwukierunkowa synchronizacja z zamówieniami, korekta istniejących szkiców,
jednorazowy raport zgodności w Excelu.

## Co robi system po wdrożeniu

| Punkt ticketu | Realizacja |
|---|---|
| 1. Kontrakt z podpisanej umowy | `confirm-fully-signed` → kontrakt **Aktywny** (`activate_without_revenue_gate`, źródło `b2b_signed_agreement`): start z umowy → bezterminowo, stawka kosztowa godzinowa z umowy. |
| 2a. Jednostka | Kontrakt przyjmuje jednostkę najnowszego uzupełnionego zamówienia; przełączenie przelicza wszystkie kwoty kontraktu (1 MD = 8 h). |
| 2. Okres i przychód | Osobne pola `client_order_start_date`/`client_order_end_date` (okres umowy nietknięty); stawka przychodowa jako krok harmonogramu od daty startu zamówienia. |
| 3. Przelicznik | `convert_rate_between` / `convert_order_rate` — godzina ↔ MD zawsze 8. |
| 4. Kolejne zamówienia | Najnowsze zamówienie nadpisuje okres; stawka zamówienia przyszłego obowiązuje od jego startu. |
| 5. Koszt: kontrakt → zamówienie | Każdy zapis zamówienia nadpisuje jego stawkę kosztową stawką z kontraktu (na dziś, przyciętą do okresu zamówienia); przebieg dobowy wprowadza każdą zaplanowaną podwyżkę w jej dniu. |
| 6. Dopasowanie jednostek | Przychód → w jednostce kontraktu; koszt → w jednostce zamówienia. |
| 7. Okres umowy nietknięty | Tak — sync nigdy nie zapisuje `start_date`/`end_date`. |
| 8. Korekta szkiców | Jednorazowo z `entrypoint.sh`: `draft` → `active` z okresem/przychodem, gdy jest uzupełnione zamówienie (wyjątki niżej). |
| 9. Raport Excel | `GET /api/contracts/order-sync-report` (Admin): „Przed wdrożeniem” (migawka sprzed synchronizacji), „Poprawione szkice”, „Stan bieżący”. |

## Pliki

Backend:
- `app/services/contract_order_sync.py` — nowy: reguły synchronizacji, listener `after_flush`, przebieg dobowy.
- `app/services/contract_order_sync_repair.py` — nowy: migawka raportu, korekta szkiców, budowa XLSX.
- `alembic/versions/0304_contract_order_sync.py` + lustro DDL i blok korekty w `entrypoint.sh`.
- `app/services/contract_lifecycle.py` — `activate_without_revenue_gate`.
- `app/services/order_write_errors.py` — `commit_order_write` synchronizuje przed commitem.
- `app/api/b2b_contract_generator.py` — aktywacja po podpisie + synchronizacja + komunikaty.
- `app/api/contracts.py` — synchronizacja po PATCH i aneksie `rate_change`, ręczna stawka przychodowa przy harmonogramie, endpoint raportu, nowe pole w odpowiedziach.
- `app/services/order_mail_apply.py`, `app/api/admin_import.py` — jawna synchronizacja w writerach spoza routerów.
- `app/tasks/contract_alerts.py` — przebieg dobowy kosztów (osobna sesja).
- `app/services/contract_merge.py` — klasyfikacja nowej kolumny.
- Modele/schematy: `client_order_start_date`, `contract_client_rates.source_order_id`.

Frontend:
- Rejestr kontraktów: okres zamówienia pod okresem umowy, jednostka przy stawkach.
- Szczegóły kontraktu: „Okres umowy” + „Okres zamówienia”.
- Zamówienia: stawka kosztowa tylko do odczytu, gdy kontrakt ją ma („z kontraktu”).
- Generator B2B: opis automatyzacji i komunikat „utworzono aktywny kontrakt”.

## Świadome decyzje i ograniczenia

- **Linie zamówień zbiorczych MD/kosztowych są poza kierunkiem kosztowym** (kontrakt → zamówienie). Ich stawkę prowadzi per linia Delivery Lead; nadpisanie z kontraktów (często szkiców bez stawki albo ze starą wartością) przestawiłoby rozliczenia BIK/Polkomtela/BNP. Kierunek zamówienie → kontrakt je obejmuje. Do potwierdzenia z Arturem, jeśli ma to objąć także MD.
- **Korekta szkiców** aktywuje szkice (także szkice z obsady linii MD bez stawek i szkice czekające na podpis kwalifikowany, ścieżka `/generate`) z trzema wyjątkami, w których aktywacja wprost byłaby szkodą:
  - minęła data końca umowy, a zamówienie trwa → kontrakt bezterminowy i Aktywny (inaczej nocny cron zakończyłby go razem z trwającymi zamówieniami);
  - minęła data końca, zamówienia brak → Zakończony (bez offboardingu);
  - osoba ma już aktywny kontrakt u tego klienta → **zostaje szkicem** (aktywny duplikat podwoiłby MRR) i jest wypisana w raporcie do ręcznej decyzji. To jedyne odstępstwo od kryterium „żaden szkic nie zostaje”.
  Paragon w `app_settings['0304_contract_order_sync_repair']` niesie stan każdego kontraktu sprzed korekty i decyzję.
- **Zapis stawki kosztowej w kontrakcie** nadal wymaga uprawnień finansowych kontraktu (admin) — Delivery Lead nie zmienia już kosztu przez zamówienie, gdy kontrakt ma stawkę.
- Szkic z minioną datą końca umowy nie jest aktywowany przez zamówienie.
- Cała synchronizacja rusza dopiero po markerze jednorazowej korekty — jeśli blok w entrypoincie padnie, system działa jak przed wdrożeniem, a korekta ponowi się przy następnym deployu.
- Błąd synchronizacji nigdy nie cofa zapisu użytkownika (zamówienia, kontraktu, podpisu) — ląduje w logu/Sentry.
- Alert kontraktowy o końcu zamówienia pomija okresy prowadzone synchronizacją (o nich ostrzega skaner zamówień) — bez podwójnych powiadomień.

## Przegląd adwersarialny

Znalezione i naprawione przed commitem: aktywacja szkiców z minioną datą końca (cron zakończyłby je z zamówieniami), obniżenie przychodu przez nieaktualny cache w pełnym formularzu kontraktu, przepisywanie przychodu na walutę zamówienia, zatarcie okresu zamówienia przez przedłużenie/zakończenie, podwójne alerty o końcu zamówienia, synchronizacja przed migawką raportu, brak fail-soft poza trasami zamówień, błędna podpowiedź w modalu linii MD. Testy mają: bramka markera, korekta szkiców (minione/duplikat), cache w formularzu (mutacja łapana), waluta. Poprawki alertów, resync po przedłużeniu/zakończeniu i fail-soft ścieżek kontraktu są pokryte regresją, bez dedykowanego testu.

## Weryfikacja

- `tests/test_contract_order_sync.py` — 35 testów (reguły z ticketu na liczbach z ticketu, API, awaria synchronizacji nie blokuje zapisu, korekta + XLSX, bramka przebiegu dobowego). Mutacja haka w `commit_order_write` łapana.
- Regresja 165 plików testów zamówień/kontraktów/B2B/MD na świeżej bazie: zielona poza testami czytającymi pliki spoza `backend/` (środowisko kontenera). Zaktualizowane testy kodujące poprzednią regułę: aktywacja po podpisie, koszt z zamówienia, okres zamówienia w kontrakcie.
- Frontend: `tsc` czysto, vitest dotkniętych obszarów 269/269, render rejestru w harnessie `/preview/contracts-consolidation` (wiersz z przykładu z ticketu).

## Po wdrożeniu

1. Log startu: `contract-order sync repair: {...}` (liczba szkiców, wierszy raportu).
2. Kontrakt Bartosza Czapelki: Aktywny, okres zamówienia 15.09–31.12.2026, 1340 PLN/MD.
3. Pobranie raportu: `GET /api/contracts/order-sync-report` (konto admina).
