# Rozliczenia: informacja zwrotna o wadach — co jest źle, jak poprawić, do skutku
<!-- indeks: informacja zwrotna, wada rozliczenia, komunikat do konsultanta, akceptujący u klienta, opiekun, przypomnienia co N dni roboczych, na sucho, dry_run, client_settlement_feedback, settlement_feedback, wysyłka poza firmę, external, powtórka próby, settlement_feedback_report -->

Powtórka 7 próby IX–X (24.11.2026, kopia produkcji, poczta 01.09–20.11): 16 uwag
NEXUS-a było prawdziwych, a 5 przypadków to proces. Uwaga stała na karcie
Finansów, ale nie docierała do osoby, która ma ją poprawić. Finanse pisały więc
maile same. Kod: `backend/app/services/client_settlements/feedback.py`, pętla
`app/tasks/settlement_feedback.py`, trasy w `app/api/settlement_reminders.py`
(`/settings`, `GET /feedback`), tabela `client_settlement_feedback` (migracja 0774).

## Wada i katalog

Wada to uwaga `warn` albo `fail` z `client_settlements.checks`, która ma wpis
w `CATALOG` (klucz `rule` albo początek tytułu). Do tego dwie wady spoza `checks`:
raport-zdjęcie przy rozliczeniu bez MD (`proof.image_file`) i „Do poprawy” od
Finansów (`finance.needs_fix`, treść = powód Finansów).

| Kod | Kto poprawia | Przypadek z próby |
|---|---|---|
| `proof.excel_with_mail` | konsultant | BNP 377 IX |
| `proof.signed_pdf` | konsultant | BNP 367 IX i X |
| `fields.rows_sum`, `fields.total_hours` | konsultant | BNP 355 X, 654 X, Bosch 624 X |
| `proof.image_file` | konsultant | CA 603 IX (zdjęcie z prywatnej poczty) |
| `accept.no_reply` | akceptujący u klienta, konsultant w kopii | PKO 717 X |
| `accept.fix` | konsultant | inne uwagi akceptacji godzin |
| `amount.protocol` | opiekun (KAM/DL), przed fakturą | Orlen 429 X, 716 X |
| `finance.needs_fix` | konsultant | „Do poprawy” Finansów |

Uwagi spoza katalogu (nadgodziny, zmiana stawki w miesiącu, ta sama osoba
u dwóch klientów, nieznany szablon RCP) rozstrzygają Finanse i nikt nie dostaje
komunikatu. Nowa wada do poprawy poza Finansami = wpis w `CATALOG` i test.
Sesja „zamówienia” (nadwyżka ponad pulę, zakończone zamówienie) dopisuje swoje
uwagi tak samo: stały `rule` w `checks` i wpis w katalogu.

Brak raportu (Orlen 704 X, mLeasing 438 X) to nie wada, tylko „Brak RCP”
z przypomnień 3., 5. i 7. dnia roboczego (`rozliczenia-przypomnienia-o-raporcie.md`).
Klient z regułą `report.consultant_declaration` dostaje tam prośbę o zdanie
z deklaracją („We wrześniu nie miałam/em dni wolnych”), a nie o plik RCP.

## Jeden komunikat na wadę i miesiąc, przypomnienia, koniec

- Wiersz `client_settlement_feedback` ma unikat (kontrakt, miesiąc, kod). Wada,
  która wraca po poprawce, otwiera ten sam wiersz z powrotem.
- Wady jednego kontraktu i miesiąca dla tej samej osoby idą w jednym mailu albo
  dzwonku. Treść mówi, co jest źle, i podaje konkretną instrukcję. Do konsultanta
  trafiają tylko MD i godziny, nigdy kwoty ani stawki klienta.
- Pierwszy komunikat idzie od razu, kolejne co `every_days` dni roboczych
  (domyślnie 3, kalendarz firmy). Temat drugiego i dalszych zaczyna się od
  „Przypomnienie:”.
- Koniec przypomnień: wady nie ma w nowym przeliczeniu (nowy plik bez uwagi) albo
  rozliczenie ma status `ok` lub `accepted` (Finanse przyjęły mimo uwagi). Wtedy
  wiersz dostaje `resolved_on`.
- Rezerwacja `last_sent_on` jest zatwierdzana przed wysyłką (jak w przypomnieniach),
  więc restart i drugi przebieg tego samego dnia niczego nie dublują.
- Automat pilnuje dwóch miesięcy przed bieżącym i tylko klientów z regułami
  rozliczeń (`reminders.automatic_clients`).

Raport-zdjęcie nie jest wadą u klienta rozliczanego z raportu klienta
(`report.time_for_teams`, Nordea): godziny przysyła klient, a zdjęcie od konsultanta
nie jest jego raportem (powtórka 7: 15 takich rozliczeń Nordei w IX–X).

## Adresat

- **Konsultant:** `contracts.candidate_email`, a bez niego adres z kartoteki kandydata
  (jak rozpoznanie nadawcy w `consultant_portal/identity`); opiekun w kopii. Powtórka 7:
  bez kartoteki 10 z 14 wad konsultanta szło do opiekuna z powodem `no_email`.
- **Akceptujący u klienta:** adres z „Do:”/„DW:” prośby o akceptację
  (`mail_text.request_recipients`, tylko domena klienta, bez konsultanta),
  zapisany w uwadze jako `acceptors`. Konsultant jest w kopii. Bez adresu
  komunikat idzie do konsultanta z prośbą, żeby sam dopytał akceptującego.
- **Opiekun:** `reminders.pick_owner` (opiekun kontraktu, opiekun klienta, DL klienta),
  dzwonek `settlement_feedback` (sekcja Delivery, grupa „Rozliczenia: wada do
  poprawy”, bez maila, bez kwot).
- Gdy do konsultanta albo klienta nie wolno pisać, opiekun dostaje dzwonek
  „Przekaż konsultantowi: …”. Bez opiekuna wpis zostaje w dzienniku jako
  `no_recipient`, więc nic nie znika po cichu.

## Wyłącznik i tryb na sucho

`app_settings['client_settlement_feedback']`, zmienia admin w karcie „Start rozliczeń”
(„Informacja zwrotna o wadach” i „Poza firmę”, każda zmiana z potwierdzeniem) albo
`PUT …/reminders/settings` z polem `feedback`; wpis w dzienniku zdarzeń:

- `mode`: `off` (domyślnie, nic), `dry_run` (zapisuje w `sends` wpis „wysłałbym”:
  komu, z jakiego powodu nie do osoby z `audience`, temat, treść, dzień; nic nie
  wysyła), `on`;
- `external`: `off` (domyślnie, do ludzi spoza firmy nic, tylko dzwonki opiekunów),
  `panel` (konsultant i klient tylko przy otwartym panelu kontraktu, przez
  `portal_mail.send`), `all` (ten sam nadawca bez względu na panel);
- `every_days`: 1–20.

**Start na produkcji (decyzja Artura z 25.11.2026): najpierw na sucho.** Wdrożenie 0774
zasiewa raz `mode: dry_run`, `external: off` (`SEED_DRY_RUN`, `ON CONFLICT DO NOTHING`,
więc późniejsza zmiana admina wygrywa). Ok. 4.12 liczby z dziennika za XI i ponowne
pytanie o wysyłkę poza firmę.

**`external` zmienia się wyłącznie po wyraźnym „tak” Artura w czacie**, bo to
wysyłka do konsultantów i do pracowników klientów. Na stagingu pętla jest
zatrzymana (`STAGING_BLOCKED_TASKS`).

## Odczyt i pomiar

- `GET /api/finance/settlements/reminders/feedback?month=` (Finanse): wady miesiąca,
  dziennik i podsumowanie (`summarize`: wady, otwarte, poprawione, komunikaty,
  adresaci).
- Powtórka próby: `python -m scripts.settlement_feedback_report --months 2026-09,2026-10`
  (bez nazwisk; `--names` tylko w terminalu na laptopie). Pomiar na kopii:
  `feedback.run(db, dzień, months=[…], settings=Settings(mode="dry_run", …))`
  w transakcji z `ROLLBACK`. Liczba komunikatów przy rozliczeniach bez wady ma
  wynosić 0.

## Pomiar na kopii produkcji (powtórka 7, 24.11.2026)

Klon `nexus_staging_klodko_v7`, przeliczenie 369 rozliczeń IX–X kodem gałęzi i dwa biegi
na sucho (24.11 i trzy dni robocze później) w jednej transakcji z `ROLLBACK`:

- 19 wad: 10 z listy powtórki i 9 przy rozliczeniach spoza populacji próby (ERSTE 614 IX,
  PKO 444 IX, 637 X, 681 X, VIP 427 IX i X, Polkomtel 476 X, Orlen 566 IX i X);
- przypadki z listy: BNP 377 IX, 367 IX i X, 355 X, 654 X, Bosch 624 X, CA 603 IX → konsultant;
  PKO 717 X → akceptujący u klienta (adres z „Do:” prośby), konsultant w kopii;
  Orlen 429 X i 716 X → opiekun; przy `external=off` wszystko dzwonkiem opiekuna;
- Orlen 704 X i mLeasing 438 X to „Brak RCP” z przypomnień (dzwonek DL-a klienta przy panelu
  „Tylko zespół”; mLeasing z prośbą o deklarację). Bez Nordei „Brak RCP” spadł z 302 do 20 (IX)
  i z 310 do 24 (X);
- przy 287 rozliczeniach bez uwag i przy 199 przypadkach „zgodne bez człowieka”: 0 komunikatów;
- drugi bieg tego samego dnia: 0 komunikatów; po trzech dniach roboczych: przypomnienie przy
  każdej z 19 otwartych wad.
