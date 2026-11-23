# Masowa wysyłka nowej umowy B2B do aktywnych kontraktorów (E5b, 0758, 22.11.2026)
<!-- indeks: przycisk „Nowa umowa dla aktywnych” w zakładce „Umowy” Generatora, `app_settings['b2b_mass_send']` „nowy wzór podpięty”, flaga `B2B_MASS_SEND_ENABLED`, `b2b_mass_send_batches` / `b2b_mass_send_items`, podgląd i próba bez wysyłki, partie po 50 co 15 minut -->

Decyzja Artura z 22.11.2026: ok. 600 aktywnych kontraktorów B2B dostanie nową
umowę do podpisu. Umowa przenosi autorskie prawa majątkowe, więc podpis
kwalifikowany obu stron (`podpis-umowy-b2b-w-nexusie.md`). Nowy wzór jest
w przygotowaniu, dlatego wszystko działa na **obecnym wzorze Generatora**,
a do ludzi nic nie wychodzi, dopóki admin jawnie nie oznaczy nowego wzoru jako
podpiętego. Dane firm bez umowy w Generatorze uzupełnia E5a
(`dane-firm-z-umow-do-potwierdzenia.md`).

## Blokady

- **„Nowy wzór podpięty”** (`app_settings['b2b_mass_send'].template_ready`,
  `services/b2b_mass_send/settings.py`): domyślnie `false`, zmienia tylko admin
  (`PUT /api/b2b-generator/mass-send/settings`, w oknie z potwierdzeniem). Póki
  `false`: `POST /mass-send/batches` = 409 z komunikatem
  `service.MSG_TEMPLATE_NOT_READY`, a pętla nic nie robi. Pętla czyta
  przełącznik na początku biegu, przed każdą pozycją i jeszcze raz tuż przed
  wysyłką, więc cofnięcie oznaczenia zatrzymuje też trwającą paczkę.
- **Założenie paczki też jest zablokowane**, nie tylko maile: nowy wiersz
  Generatora zużywa numer, a numer nigdy nie wraca do puli
  (`generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`). Podgląd i próba
  bez wysyłki działają zawsze.
- **`B2B_MASS_SEND_ENABLED`** (domyślnie OFF, rejestr flag): bez niej pętla
  kończy się przy starcie, a założenie paczki daje 409 (paczka by nie ruszyła).
  Na stagingu pętla stoi (`STAGING_BLOCKED_TASKS`: maile do ludzi).
- **Przycisk** widzi admin zawsze, a reszta osób, które wysyłają umowy do
  podpisu (`can_start` = poziom „Generowanie” i podpis w NEXUSIE włączony dla
  konta), dopiero po oznaczeniu wzoru. Wpis w Nowościach ma przyjść razem
  z odblokowaniem.

## Kto dostaje umowę

- Aktywne kontrakty B2B (`status = active`, `contract_type = b2b`) z osobą,
  **jedna pozycja na osobę**. Osoba z kilkoma aktywnymi kontraktami B2B idzie
  do sprawdzenia (`several_contracts`): umowa ma klienta i projekt, nie
  wybieramy za człowieka, którego.
- **Tylko osoby, których obecną umowę pytający mógłby wysłać do podpisu**
  (`service.may_send_for` = `b2b_esign._assert_row_sender` na jej podpisanym
  wierszu Generatora; bez wiersza — na wierszu z klientem i rekrutacją
  kontraktu, bez autora). Bez tej bramki wystarczyłoby zacząć paczkę, żeby
  zostać autorem cudzych umów ze stawkami (nowy wiersz ma autora = osobę, która
  zaczęła paczkę). Delivery Lead widzi więc tylko swoich klientów.
- Powody pominięcia (kolejność stała, `readiness.assess`): umowa kończy się
  w ciągu 30 dni (`end_date` albo ostatni dzień po wypowiedzeniu
  `agreement_last_day`, dzień firmy z `business_today()`; tylko przy
  zaznaczonym „Pomiń…”), umowa tej osoby czeka już na podpis w NEXUSIE, osoba
  jest już w masowej wysyłce (pozycja `pending`/`created`/`sent`, indeks
  `uq_b2b_mass_send_items_live_person`), brak danych firmy, brak e-maila
  (adres jak w oknie „Wyślij do podpisu”: z umowy, potem z profilu; okno
  wymienia te osoby z nazwiska).

## Dane nowej umowy

- **Źródło:** ostatni podpisany (`signed_both`, nie anulowany, nie umowa
  zlecenia, nie z Excela, nie z masowej wysyłki) wiersz Generatora tej osoby
  albo kontraktu (`render_payload`). Bez niego: `confirmed` z E5a i to, co
  kontrakt mówi wprost (rekrutacja, data rozpoczęcia, stawka godzinowa w PLN,
  replacement i FTE).
- **Nowa umowa = kopia danych ostatniej** z nowym numerem z Generatora
  i datą podpisania = dzień założenia wiersza. Data rozpoczęcia, stawka,
  klient i projekt zostają z ostatniej umowy. Metadane wydania starej umowy
  (snapshot klauzul, adres do zawiadomień) nie przechodzą — nowa dostaje
  własne przy wydaniu.
- **Treści nie zgadujemy.** Braki formularza Generatora (te same etykiety co
  `b2bFormMissing` w `lib/b2b-generator-wizard.ts`, plus „Forma w umowie”, gdy
  odczyt z umowy nie podał płci) dają „Do sprawdzenia” z nazwami pól.
  „Do sprawdzenia” dają też uwagi: stawka w kontrakcie inna niż w ostatniej
  umowie (stawka dzienna = 8 × godzinowa; miesięczna zawsze), inna waluta,
  stawka progresywna, aneks do ostatniej umowy, „aneks uzupełnienia danych do
  zrobienia”, inny klient niż kontrakt, niepodpisana umowa tej osoby
  w rejestrze, obszar usług usunięty z katalogu. Uwagi nie podają kwot.
- Z E5a nie bierzemy nazwy Klienta z kartoteki: rejestr klauzul wybiera
  klauzule klienta po tej nazwie (`resolve_override`), a inna pisownia dałaby
  umowę bez nich. Osoba bez wiersza Generatora zawsze idzie więc do
  sprawdzenia (brak nazwy Klienta, miasta, opisu projektu i obszaru usług).

## Paczka i pętla

- **Tabele:** `b2b_mass_send_batches` (kto zaczął, reprezentant za
  B2Bnetwork, dni linku, stan, liczby z planu) i `b2b_mass_send_items`
  (kontrakt, kandydat, wiersz-źródło, nowy wiersz, wniosek o podpis, stan
  `pending`/`created`/`sent`/`failed`/`needs_review`/`skipped`, powód, braki,
  błąd). DDL: `services/b2b_mass_send/schema_sql.py` (migracja 0758 i lustro
  w `entrypoint.sh`), sondy w `/api/health/deep`. Jedna paczka naraz
  (blokada doradcza, druga = 409).
- **Wiersz Generatora powstaje tą samą drogą co „Pobierz DOCX”**:
  `issue_standalone_contract` w `api/b2b_contract_generator.py` (bramki, para
  kandydat–rekrutacja, numer, render przed zapisem, szczegóły administracyjne).
  `/render` woła tę samą funkcję. Wiersz dostaje kontrakt, osobę i klienta
  kontraktu oraz poprzednią umowę (`previous_generated_contract_id`) w tej
  samej transakcji co zapis wiersza (`on_created`), jak umowa po powrocie
  z przerwy. Nie przez `apply_contract_link`: tamto stempluje numer i datę
  podpisu w szczegółach B2B kontraktu, a ta umowa nie jest jeszcze podpisana —
  stempel robi podpis. Bez dzwonka „placement i premia są Twoje” do prowadzącego
  (`notify_owner=False`): nowa umowa obecnego kontraktora nie jest placementem.
- **Wysyłka tą samą drogą co „Wyślij do podpisu”**: `open_signing_request`
  w `api/b2b_esign.py` (PDF z Worda, paczka „Dokumenty do startu”, zamrożenie),
  potem `_mail_link` ze skrzynki osoby, która zaczęła paczkę. Bez połączonej
  skrzynki pozycja `failed` z tym powodem i bez wniosku. Mail, który nie wyszedł,
  wycofuje wniosek tej osoby (linku nikt inny nie zna). Przed każdą wysyłką
  jeszcze raz: przełącznik, podpis w NEXUSIE dla konta, reprezentant z listy,
  `_assert_row_sender`, stan wiersza.
- **Pętla** `tasks/b2b_mass_send.py`: co 15 minut najwyżej 50 pozycji
  (`service.CHUNK`), każda we własnej transakcji. Pozycja przed utworzeniem
  wiersza jest oceniana od nowa (ktoś mógł poprawić dane, wysłać umowę sam albo
  zakończyć kontrakt). Błąd Generatora 404/409/422 = „Do sprawdzenia”
  z komunikatem; numer zajęty w międzyczasie = ponowienie (do 3 prób).
- **„Zatrzymaj wysyłkę”** (osoba, która zaczęła, albo admin): pozycje bez linku
  → `skipped`. Wysłane linki zostają i wycofuje się je w rejestrze jak
  pojedynczą wysyłkę. Utworzone, a niewysłane wiersze zostają w rejestrze
  „W trakcie” z numerem.

## Trasy (`/api/b2b-generator/mass-send`, bramka sekcji jak Generator)

`GET settings` · `PUT settings` (admin) · `GET preview?skip_ending&status&offset&limit`
(liczby po klientach i stan osoby, bez zapisu) · `POST dry-run` (plan i bramki
Generatora dla każdej gotowej osoby bez zapisu i bez numeru, z listą blokad) ·
`POST batches` · `GET batches/current` · `GET batches/{id}` (postęp: wysłane,
czeka na kontraktora, czeka na firmę, podpisane, problemy) · `GET batches/{id}/items`
· `POST batches/{id}/cancel`. Paczkę widzi osoba, która ją zaczęła, i admin.
Wzorzec bramek: `tests/data/authz_golden/b2b_mass_send.json`.

## Do decyzji przed odblokowaniem

- Data rozpoczęcia w nowej umowie: dziś zostaje data z ostatniej umowy.
- Nowy wzór i jego numer wersji (`template_version`) — dziś obecny wzór.
- Jak podpisana nowa umowa ma wpływać na „Placementy” i premie: po podpisie
  działa zwykła automatyka „Oznacz jako podpisaną” na kontrakcie osoby.

Testy: `test_b2b_mass_send_readiness.py` (reguły, bez bazy),
`test_b2b_mass_send.py` (podgląd, próba, 409, pętla przy blokadzie, partie,
skrzynka, mail), `MassSendDialog.test.tsx`.
