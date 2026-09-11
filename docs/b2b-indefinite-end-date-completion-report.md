# Umowy B2B bezterminowe + zakończenia ze zgłoszenia — raport (11.09.2026)

## Zgłoszenie (skrót)

Umowy B2B w statusie „Aktywny"/„Kończący się" miały datę zakończenia przejętą
z końca zamówienia, choć nikt ich nie zakończył. Pożądane: taka umowa jest
bezterminowa (jednorazowa korekta wstecz + zabezpieczenie na przyszłość);
umowy „Zakończone" i umowy zlecenie bez zmian; 16 wskazanych osób kończy
współpracę z datą i wpisem „[Kto] — [Powód]" w polu tekstowym.

## Co zrobiono

| Obszar | Pliki |
|---|---|
| Reguła (jedno źródło) | `backend/app/services/b2b_contract_end_date.py`, `frontend/src/lib/contract-end-date.ts` |
| API — odmowa 422 `b2b_end_date_requires_termination` | `backend/app/api/contracts.py` (POST, PATCH, aneks `extension`, `/bulk-extend`), `backend/app/api/client_orders.py` (`contract-with-order`) |
| Przywrócenie z „Zakończony" w rejestrze → bezterminowa | `backend/app/api/contracts.py` (`update_contract`) |
| Scalanie duplikatów nie daje żywej B2B daty | `backend/app/services/contract_merge.py` |
| Jednorazowa korekta | `backend/app/services/b2b_end_date_repair.py`, blok w `backend/entrypoint.sh` |
| Formularze bez daty końca dla B2B | `NewContractorOrderDialog`, `contracts/new`, `contracts/[id]` (edycja), `AddProjectDialog`, `ContractRegisterDialog` |
| Aneks „Przedłuż" / „Extend" dla bezterminowej | `ContractAmendmentsTab` (przycisk wyłączony z wyjaśnieniem), `ExtendContractMenu` i pasek zbiorczy (komunikat zamiast „przedłużono") |
| Karta zakończenia widoczna od chwili wypowiedzenia | `frontend/src/app/contracts/[id]/page.tsx` („Zaplanowane zakończenie współpracy") |
| Etykieta pola tekstowego | dialogi „Zakończ współpracę" — „Kto zdecydował i dlaczego / wnioski" |
| Testy | `backend/tests/test_b2b_contract_end_date.py` (+ 5 zaktualizowanych), `frontend/src/lib/__tests__/contract-end-date.test.ts`, `NewContractorOrderDialog.test.tsx` |

Brak migracji schematu — wyłącznie korekta danych (marker
`0307_b2b_indefinite_end_date` w `app_settings`, szczegóły pod
`repair_details_0307_b2b_indefinite_end_date`).

## Decyzje, które warto znać

1. **„Ręczne zakończenie"** = `terminated_at`/`termination_reason` (dialog
   „Zakończ współpracę") albo aneks `early_termination`. Umowa B2B z takim
   śladem zachowuje datę, nawet w statusie „Aktywny"/„Kończący się".
2. **Pole „powód zakończenia" jest listą wyboru, nie tekstem.** Wpis
   „[Kto] — [Powód]" trafia do jedynego pola tekstowego zakończenia
   (`termination_lessons`), a lista dostaje najbliższą wartość: Klient — No
   budget → „Cięcie budżetu klienta", Klient — Wydajność → „Problem
   jakościowy", Kandydat — Wyższa stawka → „Dostał lepszą ofertę", Kandydat —
   Przyczyny osobiste → „Powody osobiste", Kandydat / Kandydat — No budget →
   „Konsultant zrezygnował", Internalizacja → „Przejście do klienta".
3. **Data przyszła nie daje dziś statusu „Zakończony"** (reguła P0.7
   `/terminate`): umowa pracuje do daty zakończenia („Aktywny", w oknie
   30 dni „Kończący się"), nocny cron przestawia ją na „Zakończony" dzień po
   dacie. Inaczej osoby odchodzące np. 31.12 znikałyby z MRR już teraz.
   Wypowiedzenie widać od razu na karcie kontraktu.
4. **Data ze zgłoszenia wygrywa** także wtedy, gdy jest późniejsza niż
   dotychczasowa (dotychczasowa pochodziła z końca zamówienia). Zamówienia
   są tylko skracane do daty zakończenia, nigdy wydłużane.
5. **Szkice poza korektą** — wyczyszczona data wpuściłaby martwy szkic do MRR
   przy najbliższej automatycznej aktywacji.
6. **Repo publiczne**: lista 16 osób w kodzie to trójki ID (kontrakt,
   kandydat, klient) sprawdzone na produkcji; niezgodna trójka = pominięcie
   z kodem powodu w paragonie.

## Weryfikacja

- Backend: `test_b2b_contract_end_date.py` (22 testy, w tym wykonanie korekty
  na bazie) + szeroka lista testów kontraktów/zamówień na lokalnym Postgresie
  16; ruff check + format czyste.
- Frontend: `tsc --noEmit` czysty, vitest (kontrakty, okno nowego kontraktora,
  helper), eslint; podgląd `/preview/contracts-consolidation` — B2B pokazuje
  „Bezterminowo…", Zlecenie pole daty.

## Znane ograniczenia

- Umowa przywrócona po wypowiedzeniu zachowuje `terminated_at`
  (zachowanie `reopen_contract` sprzed zmiany) — liczy się jako „zakończona
  ręcznie", więc wolno jej ustawić datę bez ponownego wypowiedzenia.
- `/bulk-extend` i „Extend" nie przedłużają umów bezterminowych — przedłuża
  się zamówienie klienta.
