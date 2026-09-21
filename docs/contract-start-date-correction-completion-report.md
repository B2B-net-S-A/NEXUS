# Korekta dat rozpoczęcia umów — raport (21.09.2026)

Zgłoszenie: data rozpoczęcia umowy w Kontraktach i „Start date" w profilu klienta
są błędne; poprawne daty w arkuszu „Data rozpoczęcia umowy 21.09.2026.xlsx"
(arkusz „Kontrakty", kolumna „Data rozpoczęcia umowy prawidłowa", klucz = ID kontraktu).

## Diagnoza (produkcja, tylko odczyt)

| Pomiar | Wynik |
|---|---|
| Kontrakty w arkuszu | 475, wszystkie istnieją w bazie |
| Data w bazie ≠ arkusz | 291 (264 za późno, 20 za wcześnie, 3 puste w bazie, 4 puste w arkuszu) |
| Data w bazie = start zamówienia (`client_order_start_date`) | 158 z 291 |
| Zmiany `start_date` w 30 dziennych zrzutach bazy (23.08–21.09) | 11 kontraktów, każda zmiana W STRONĘ arkusza |
| Zgodność z arkuszem w zrzucie z 23.08 | 131 z 419 |
| Zapis użytkownika cofnięty przez system (dziennik vs baza) | 0 przypadków |

**Przyczyna:** błędne daty pochodzą z masowego importu rejestrów kontraktów
23–26.06.2026. Import wpisał w „datę rozpoczęcia umowy" początek bieżącego
zamówienia (Nordea masowo 2026-07-01) albo zaślepkę (BNP: wszystkie 2026-01-02).
Od tamtej pory data nie była ruszana przez żaden automat.

**Hipoteza „zmieniło się przy aktualizacji" — obalona.** Wrześniowe korekty
(`0304` synchronizacja z zamówieniami, `0307` bezterminowe umowy B2B, `0309`
stawki godzinowe, backfill okresu zamówienia 14.09 10:53) dotknęły tych wierszy —
stąd masowy `updated_at` w rejestrze — ale zmieniały okres zamówienia
(`client_order_start_date`/`client_order_end_date`), statusy, daty końca i stawki,
nie `start_date`. Starszych zrzutów niż 23.08 nie ma; dziennik aktywności nie
pokazuje zapisu `start_date` w oknie czerwiec–sierpień poza edycjami ręcznymi.

**„Zapisałam, a wróciło":** sprawdzone. Formularz edycji odsyła datę rozpoczęcia
przy każdym zapisie; 80 z 291 błędnych kontraktów było edytowanych, ale każda
edycja odesłała istniejącą (błędną) datę — nikt jej nie poprawił. Synchronizacja
zamówień nie cofa zapisu z formularza (SQLAlchemy flushuje zmiany przed
savepointem) — pilnuje tego test.

## Zmiany

- `backend/app/data/contract_start_date_corrections.py` — 287 wpisów
  `(kontrakt, kandydat, klient, data w bazie 21.09, data poprawna)`, bez nazwisk.
- `backend/app/services/contract_start_date_repair.py` + blok
  `repair-contract-start-dates` w `entrypoint.sh` — jednorazowa korekta
  (marker `0334_contract_start_date_correction` + advisory lock). Kontrakt zmienia
  się tylko przy zgodnej trójce ID i niezmienionej od 21.09 dacie; świeższa
  zmiana człowieka wygrywa (`edited_since_snapshot`). Każda zmiana zostawia
  Activity `start_date_corrected` z poprzednią datą.
- `PATCH /api/contracts/{id}` — dziennik „updated" niesie `previous_start_date`,
  gdy data naprawdę się zmieniła (wcześniej tylko nową wartość — rozjazd był nie
  do prześledzenia).
- Profil klienta czyta `contracts.start_date` wprost — poprawia się razem z kontraktem.

## Pominięte / do decyzji działu

- ID **111, 300, 453, 607** — komórka daty w arkuszu pusta (sformatowana jako
  00:00). Bez zmian; paragon wymienia je w `skipped_without_date`.

## Weryfikacja po wdrożeniu

- Paragon: `app_settings['0334_contract_start_date_correction']` (applied / skipped).
- Ponowne porównanie arkusz ↔ baza: 0 rozbieżności poza czterema pustymi komórkami.
- Profil Alior Bank S.A. → Konsultanci → „Start date" = arkusz.
