# Rozdzielenie zamówień MD i okresowych — raport z wdrożenia

Data: 2026-09-01. Pięć zgłoszeń z modułów **Klienci → Zamówienia** i **Kontrakty**,
jedna zmiana — spotykają się na tym samym wierszu `client_orders` i tym samym
kontrakcie.

## 1. Zamówienia MD i okresowe są niezależne (moduł Klienci → Zamówienia)

**Przyczyna, dwuczęściowa.** Kontrakt opisuje parę *osoba × klient*, nie
pojedyncze zamówienie, więc linia grupy MD i samodzielne zamówienie okresowe
wiszą na TYM SAMYM kontrakcie. Hook zatrudnienia (`_ensure_open_order`) zakładał
szkic-zaślepkę „(bez numeru)" **zanim** Delivery obsadził osobę na zamówieniu MD
— stąd dwa równoległe zapisy tej samej współpracy. „Zakończ" na karcie
okresowej wypowiadał CAŁĄ umowę (`POST /contracts/{id}/terminate`), a to domyka
wszystkie zamówienia kontraktu, w tym linię MD.

**Naprawa.**

* `POST /api/clients/{c}/orders/{o}/close` — nowa, wąska akcja: domyka JEDEN
  wiersz, nie dotyka umowy ani sąsiednich zamówień. Linia grupowa odrzucana 409
  (grupa ma własne zakończenie z budżetem i historią).
* Karta kontraktora ma teraz **dwa** przyciski: „Zakończ zamówienie" i „Zakończ
  współpracę". Jeden przycisk o dwóch znaczeniach nie da się opisać etykietą.
* `/terminate` bez zmian — domyka wszystkie zamówienia i otwiera sprawy
  offboardingowe MD, bo umowa opisuje CAŁĄ współpracę u klienta. Zawężenie jej
  zabiłoby po cichu workflow decyzji Delivery Leada.
* Hook zatrudnienia nie tworzy szkicu, gdy żywa linia grupowa już jest; wejście
  na linię grupy kasuje zostawioną zaślepkę (`absorb_auto_draft_shells` —
  wyłącznie szkic bez pliku PO, bez budżetu i bez `filled_at`).
* Ręczne założenie zamówienia okresowego obok żywej linii **MD** → 409.
  Współistnienie z zamówieniem KOSZTOWYM zostaje (dwa modele rozliczenia
  u jednego klienta to wspierany scenariusz; ticket mówi o MD).

**Dane.** Migracja `0261_separate_md_periodic` + lustro w `entrypoint.sh`
(jedno źródło SQL: `app/services/order_separation_repair.py`). Reguła, **zero
`client_id` w SQL-u** — czterej klienci ze zgłoszenia są przypadkiem reguły.
Puste zaślepki kasowane, pozostałe duplikaty ANULOWANE (mogą nieść numer i PDF,
a `DELETE` kasuje też plik). Paragon w `app_settings`.

## 2. Kontrakty: domyślny widok to Aktywne **i** Kończące się

`DEFAULT_CONTRACT_STATUS_FILTER` = `["active", "ending"]`. Queryless
`/contracts` rozwija się do `?status=active&status=ending`; filtrowanie do
jednego statusu i sentinel `status=all` bez zmian. Licznik („N kontraktorów /
M aktywnych kontraktów") liczy cały zbiór obowiązujących zamiast wymagać
dokładnie jednego statusu.

## 3. Zakończenie u jednego klienta nie sięga do drugiego

`client_orders.client_id` to własna kolumna, a baza nie ma więzu wiążącego ją
z klientem kontraktu. Kaskada offboardingu bierze teraz wyłącznie zamówienia
`ClientOrder.client_id == Contract.client_id`. Wiersze rozjechane zostają
nietknięte i widać je w `GET /api/admin/engagement-inventory`
(`order_client_mismatch`) — która strona rozjazdu jest prawdziwa, rozstrzyga
człowiek, tak jak w `GET /api/admin/client-mixups`.

## 4. Data końca zamówienia nie nadpisuje daty zakończenia umowy

`_contract_for_candidate` kopiował `end_date` linii/grupy na szkic kontraktu,
więc umowa B2B, która ma być bezterminowa, dostawała datę, której nikt nie
zadeklarował — a nocny `_promote_statuses` przestawiał ją na „Kończąca się",
potem „Zakończona". Kopiowana jest wyłącznie data ROZPOCZĘCIA.

`sync_contract_to_live_order` **zostaje**: wydłuża horyzont zakończonego
kontraktu do końca żywego zamówienia. To mechanizm wskrzeszania („Przedłużenie
zamówienia wskrzesza zakończony kontrakt"), bez niego nocny cron demotowałby
wskrzeszony kontrakt tej samej nocy.

Krok B migracji czyści datę i przywraca `active` wyłącznie tam, gdzie widać, że
nikt współpracy nie zakończył: brak `terminated_at`, brak powodu wypowiedzenia,
brak aneksu `early_termination`, żywa linia grupowa obejmująca dziś.

## 5. Eksport do Excela: stan NA DZIŚ, jeden wiersz na konsultanta

Reguła `is_current_order_period` / `isCurrentOrder` po obu stronach: status
`completed`/`cancelled` odpada, okres musi obejmować dziś (brak końca =
bezterminowo, brak startu = już obowiązuje). „Kończące się" JEST aktualne.
Deduplikacja po KONTRAKCIE (nie po imieniu) obejmuje też linie grup, więc
konsultant nie pojawi się raz w grupie i raz jako karta. Filtr linii czyta okres
linii, a w jego braku okres grupy — inaczej przepuszczałby całą obsadę
zamówienia zakończonego rok temu.

## 6. Nordea: numer zamówienia zamiast losowego słowa

Poprzednie wyrażenie brało pierwszy token za etykietą, a klasa
`[A-Z0-9._/-]` z `IGNORECASE` pasuje też na litery — więc do pola „numer
zamówienia" trafiało zwykłe SŁOWO z dokumentu. Teraz etykieta i wartość są
rozdzielone: wartość musi zawierać CYFRĘ, nie może być datą, a okno
wyszukiwania (160 znaków / do następnej etykiety) obejmuje ten sam wiersz
i następny. Układ dwukolumnowy (nagłówki obok siebie, wartości pod nimi) kończy
się PUSTYM polem i komunikatem „sprawdź", nie numerem umowy ramowej.

**Uwaga wdrożeniowa:** polityka jest fail-closed i bramkowana po `client_id`.
Bez `NORDEA_ORDER_NUMBER_CLIENT_IDS` w Coolify reguła nie działa dla nikogo
i pole `client_policy` w odpowiedzi odczytu jest puste. Ustawienie zmiennej —
workflow „Coolify set env"; ID klienta:
`SELECT id, name FROM clients WHERE name ILIKE '%nordea%';`

## Weryfikacja

* Backend, realny Postgres: `tests/test_md_periodic_order_separation.py`
  (8 testów) + przebieg celowany-szeroki po 53 plikach dotykających zmienionych
  modułów — **987 passed**, po korekcie dwóch atrap **194 passed** w podzbiorze.
* Migracja `0261` zaaplikowana na świeżej bazie (`alembic upgrade heads`, exit 0).
* Frontend: `tsc --noEmit` czysto, `next lint` czysto, vitest (client-order-list,
  contracts-list-navigation, OrdersAndContractsTab, harnessy zamówień) zielone.
* Przeglądarka, pełny flow na lokalnym stacku (kontrakt 434, klient 391):
  duplikat okresowy `ZAM_1453_2026` domknięty z karty przyciskiem „Zakończ
  zamówienie" → linia MD `active` z własną datą 2026-09-30 **nietknięta**,
  kontrakt `active`, `end_date` puste, `terminated_at` puste. Po odświeżeniu
  osoba jest na liście RAZ (2 pozycje → 1). `/contracts` bez parametrów
  rozwija się do `?status=active&status=ending`, licznik „289 kontraktorów /
  310 aktywnych kontraktów".

## Znane ograniczenia

* Rozjechane wiersze `client_orders.client_id ≠ contracts.client_id` są
  **raportowane, nie naprawiane**. Nie da się z samych danych rozstrzygnąć,
  która strona jest prawdziwa, a cicha zmiana czyjegoś stanu na podstawie
  niespójnych danych jest gorsza niż jej brak.
* Migracja nie ma dostępu do produkcji z tej sesji — liczby duplikatów
  u BNP / Polkomtel / BIK / Wedel będą znane z paragonu w `app_settings`
  po wdrożeniu (`SELECT value FROM app_settings WHERE key =
  '0261_separate_md_periodic';`).
