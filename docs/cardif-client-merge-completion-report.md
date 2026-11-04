# Scalenie „BNP Paribas Cardif” z Cardif Assurances + umowa 1520/2026 — raport

Stan na 13.10.2026. Zgłoszenie: dwa rekordy tego samego klienta w module Klienci
i umowa 1520/2026 ze znacznikiem „Kontrakt usunięty — brak kontraktora”.

## Co się stało

- Rekord 52 („BNP Paribas Cardif”) pochodzi z Traffita, rekord 38335 z arkusza
  klientów. Migracja `0244_cardif_client_reassignment` przepięła w sierpniu
  dwa kontrakty, dwa zamówienia i dwie umowy; reszta historii została na 52.
- Umowa 1520/2026 (id 110): podpis 29.09 założył kontrakt #679 u klienta
  rekrutacji (52). Dwie próby usunięcia tego kontraktu zostały zablokowane,
  trzecia — wymuszona — odpięła podpisaną umowę. Właściwy kontrakt #689 powstał
  osobno u 38335. Znacznik w rejestrze to wyłącznie „podpisana obustronnie
  i bez kontraktu”.

## Decyzja

Zgłoszenie prosiło, by rekord 52 został na liście jako pusty. Decyzja Artura
z 13.10.2026: rekord zostaje w bazie, ale **oznaczony jako scalony** z 38335
(znika z list i wyboru klienta, profil przekierowuje na cel, import z Traffita
i poczta zamówień idą za wskazaniem).

## Stan przed korektą (produkcja, odczyt 13.10.2026)

| Dane na rekordzie 52 | Liczba | Po korekcie |
|---|---|---|
| Rekrutacje (wszystkie zamknięte) | 5 | u 38335 |
| Procesy rekrutacji | 210 | u 38335 |
| Kontakty | 7 | u 38335 |
| Karta klienta + jej zdarzenie | 1 + 1 | u 38335 (cel nie miał karty) |
| Alerty DL (zamknięte) | 3 | u 38335, z poprawionym linkiem |
| Umowa z Generatora (1520/2026) | 1 | u 38335, powiązana z kontraktem #689 |
| Kontrakty, zamówienia, umowy ramowe, wiedza, warunki umowy | 0 | — |
| Zakres portfela, wiersz importu, przydział DL | 1 + 1 + 1 | zostają (wpis katalogu) |
| Historia zdarzeń o kontrakcie #679, historia rekordu | 3 + 1 | zostają (dziennik) |

Pola pojedyncze rekordu (notatki, NIP, adres) były puste po obu stronach albo
wypełnione tylko u celu — nic nie zostało nadpisane.

## Co zrobiono

| Część | Stan | Dowód |
|---|---|---|
| Serwis korekty `app/services/cardif_client_merge_repair.py` | w PR | testy `tests/test_cardif_client_merge_repair.py` |
| Wydzielenie `apply_contract_link` z akcji „Powiąż z kontraktem” | w PR | `tests/test_b2b_generated_link_contract.py` bez zmian |
| Blok `repair-cardif-client-merge` w `entrypoint.sh` | w PR | test obecności bloku |
| Wpis „Scalenie klientów” w Historii zdarzeń | w PR | etykieta `client.merge` |
| Reguły w `docs/claude/klienci/scalenie-cardif-pelne-przeniesienie-danych.md` | w PR | indeks w `CLAUDE.md` |
| Wykonanie na produkcji | wykonane 13.10.2026 | paragon `app_settings['0435_cardif_client_merge']` |

## Jak sprawdzić po wdrożeniu

1. `/api/health` → `version` to SHA z maina z tą zmianą; `/api/health/deep` = 200.
2. Paragon `0435_cardif_client_merge`: bez `skipped`, `jobs_moved` 5 pozycji,
   `processes_moved` 210, `materials_moved` 7 kontaktów + karta + zdarzenie,
   `alerts_moved` 3, `agreement.skipped` puste, `merged` prawda,
   `unexpected_references` puste.
3. Rekord 52: `merged_into_client_id = 38335`, `archived_at` ustawione,
   `deleted_at` puste. Na rekordzie zostają tylko zakres portfela, wiersz
   importu i przydział DL.
4. Umowa 110: `client_id = 38335`, `contract_id = 689`, nazwa klienta celu
   w rejestrze, `render_payload` bez zmian.
5. Ekran: Generator umów → 1520/2026 bez znacznika; Klienci → brak
   „BNP Paribas Cardif” na liście, `/clients/52` przekierowuje na cel.

## Wynik na produkcji (13.10.2026)

PR #2171 wdrożony (`fda268bbe`). Paragon `0435_cardif_client_merge`: bez
pominięć, 5 rekrutacji, 210 procesów, 7 kontaktów, karta i jej zdarzenie,
3 alerty, umowa powiązana z kontraktem #689, rekord 52 oznaczony jako scalony,
`unexpected_references` puste. Na rekordzie 52 zostały tylko zakres portfela,
wiersz importu i przydział DL.

## Znaleziska po scaleniu i co z nimi zrobiono (drugi PR)

Jak naprawdę doszło do osierocenia umowy (historia kontraktów na produkcji):
podpis 29.09 założył kontrakt #679 u klienta rekrutacji (52); 1.10 automat
z zamówienia założył drugi kontrakt tej osoby (#689) u 38335, bo jej kontraktu
u tego klienta nie było; 5.10 administrator usunął #679 wymuszeniem, a umowa
została bez kontraktu. Scalenie rekordów usuwa źródło (zamówienia i rekrutacje
trafiają odtąd do jednego klienta).

| Znalezisko | Co zrobiono |
|---|---|
| Okno wymuszonego usunięcia nie mówiło, co stanie się z podpisaną umową | dopisane zdanie o skutku i o akcji „Powiąż z kontraktem” |
| Kontrakt #689 bez rekrutacji i numeru umowy | „Powiąż z kontraktem” uzupełnia odtąd puste pola kontraktu; #689 dociąga jednorazowy bieg `0436_cardif_contract_fill` |
| Wpis o powiązaniu umowy na osi czasu kontraktu jako „Zdarzenie systemowe” | polska etykieta |
| Rodzina „BNP” | sprawdzona odczytem: 5 nieaktywnych rekordów to odrębne spółki z samymi kontaktami — nic do scalania |
| Nieaktualne zdanie w regule o audycie pomylonych klientów | poprawione |
| „Ciche odpięcie przy zwykłym usunięciu kontraktu” | nie było przyczyną i nie jest błędem: reguła `signed_generated_link_filter` jest świadoma, a na produkcji nie ma ani jednej umowy z klientem innym niż klient jej kontraktu |

## Zostaje

- Skan podpisanej umowy 1520/2026 trzeba dołączyć ręcznie w dokumentach
  kontraktu #689.
- Umowy 1474/2026 i 1520/2026 drukują „BNP Paribas Cardif” — to treść
  dokumentów podpisanych przez obie strony (reguła z 0242/0244).
- Umowa 1460/2026 nadal nie ma kontraktu: jej rekord osoby nie ma żadnego
  kontraktu, więc właściwy musi wskazać człowiek („Powiąż z kontraktem”).
- Kontrakt #600 ma podpisaną umowę 1476/2026, ale nie ma szczegółów B2B
  (inna przyczyna niż tutaj, niezbadana).
