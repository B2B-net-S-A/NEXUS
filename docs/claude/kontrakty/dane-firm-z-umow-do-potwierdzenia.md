# Dane firm z umów do potwierdzenia przed nową umową B2B (E5a, 0755, 22.11.2026)
<!-- indeks: odczyt danych firmy Partnera z podpisanej umowy modelem (F53), propozycja z cytatem, „Zastosuj” / „Odrzuć” / „Sprawdź w rejestrze”, tylko puste kolumny kandydata, `contract_partner_reads`, flaga `CONTRACT_PARTNER_READ_ENABLED`, ekran `/contracts/dane-firm` -->

Decyzja Artura z 22.11.2026: ok. 600 aktywnych kontraktorów B2B dostanie nową
umowę do podpisu, a do jej wygenerowania potrzebne są dane firmy każdego z nich.
Na kopii produkcji z 19.11.2026: 491 aktywnych kontraktów B2B, z czego tylko 117
ma w Generatorze wiersz z danymi Partnera (`b2b_generated_contracts.render_payload`),
a 374 mają tylko stawki, klienta i daty. Artur wybrał: **dane czyta model
z podpisanej umowy, a człowiek potwierdza każdą propozycję**, zanim zostanie
użyta. Ta reguła opisuje E5a (odczyt, propozycje, potwierdzenie). Masowa
wysyłka nowej umowy to osobny PR i czyta `confirmed`.

- **Które kontrakty:** `status = active`, `contract_type = b2b`, z kandydatem,
  bez wiersza Generatora z niepustym `render_payload->>'partner_nip'` dla tego
  kontraktu albo tej osoby (`service.eligible_contracts`).
- **Który plik:** tylko `doc_type = contract` bez folderu (sekcja „Aktualna
  umowa”), PDF albo zdjęcie; DOCX to wersja robocza z Generatora. Wygrywa plik
  z numerem bieżącej umowy (dane umowy B2B, potem Generator — kolejność jak
  `contract_document_folders._current_contract_number`), bez niego najnowszy
  numer z nazwy pliku, PDF przed zdjęciem, nowszy plik (`pick_main_document`).
  Kontrakt bez takiego pliku liczy się na ekranie jako „bez pliku umowy”.
  Nowy plik umowy w kontrakcie wygrywa wybór i czeka na odczyt.
- **Odczyt** (F53, `services/contract_partner_reads/reader.py`, ten sam model
  i zapas co F52, bo to ten sam plik): pola firmy z `B2BRenderRequest` (płeć,
  imię i nazwisko, firma, typ podmiotu, NIP, REGON, adresy, e-mail, telefon,
  a przy spółce KRS, siedziba, sąd, kapitał, reprezentacja), każde z dosłownym
  cytatem. Model nie dostaje danych z NEXUSA. Kod sprawdza cyfrę kontrolną NIP-u
  i REGON-u, KRS, e-mail i telefon, odrzuca NIP spółki (`KSEF_CONTEXT_NIP`),
  a przy PDF-ie z tekstem sprawdza, czy cytat stoi w pliku. Czego nie ma albo co
  nie przechodzi sprawdzenia, zostaje puste z uwagą — niczego nie uzupełniamy.
  Wiersz `contract_partner_reads` na plik i wersję czytnika (`READER_VERSION`);
  plik z decyzją człowieka nie wraca do odczytu po zmianie wersji.
- **„Zastosuj”** (`apply_read`): człowiek może poprawić każde pole (te same
  reguły co odczyt; zła wartość = 422 z nazwą pola). Potwierdzone dane idą do
  `confirmed` (z listą poprawionych pól), a do profilu kandydata — kolumny,
  z których Generator wypełnia formularz (`legal_name`, `nip`, `regon`,
  `business_address`, `email`, `phone`) — **tylko w puste pola**. Wpisaną
  wartość firmy zmienia wyłącznie zaznaczone „Nadpisz dane wpisane w profilu”.
  E-mail i telefon trafiają tylko w puste pole także przy „Nadpisz”: e-mail to
  klucz tożsamości osoby, a oba synchronizuje Traffit (blokada jak przy ręcznej
  edycji, `lock_changed_traffit_synced_fields`); e-mail innej osoby = pominięty.
  `candidate_changes` mówi o każdej kolumnie: `written`, `same`, `kept`,
  `taken`, `no_value`. Ślad: Activity kandydata `partner_data_from_contract`.
- **„Odrzuć”** (`dismiss_read`): odczyt nie trafia ani do profilu, ani do
  nowej umowy. Zastosowanego nie da się odrzucić — poprawka w profilu.
- **„Sprawdź w rejestrze”** (`verify_read`): `registry_verification.verify_company`
  (CEIDG albo KRS) po NIP-ie albo KRS z odczytu i poprawek, wyłącznie na
  kliknięcie człowieka — biznes.gov.pl jest do pojedynczych zapytań, a biała
  lista MF ma 100 zapytań dziennie na całą firmę, więc pętla rejestrów nie woła.
  Wynik z porównaniem pól zostaje przy odczycie; ponowne kliknięcie w ciągu
  10 minut z tym samym numerem oddaje zapisany wynik. Wiersz nie jest
  zablokowany na czas zapytania (do 30 s).
- **Dostęp:** sekcja Delivery i „Kontrakty i zamówienia: tworzenie i edycja”
  na każdej trasie `/api/contract-partner-reads` (lista to kolejka pracy
  z danymi osobowymi kontraktorów); konto z rolą Delivery Leada — tylko jego
  klienci (`resolve_delivery_lead_client_ids`), cudzy odczyt = 404. Wzorzec:
  `tests/data/authz_golden/contract_partner_reads.json`.
- **Pętla w workerze** (`tasks/contract_partner_reads.py`, co 10 min, paczka
  25 plików, każdy plik we własnej transakcji). `CONTRACT_PARTNER_READ_ENABLED`
  domyślnie **OFF** (rejestr flag) — włącza Artur. Pierwszy bieg nadrabia ok.
  370 plików. Na stagingu stoi (koszt modelu, `STAGING_BLOCKED_TASKS`).
- **Ekran** `/contracts/dane-firm` („Dane firm z umów — do potwierdzenia”,
  przycisk na liście kontraktów dla „Kontrakty i zamówienia”): zakładki Do
  potwierdzenia · Nieudane · Zastosowane · Odrzucone, liczniki teczek, pola
  z cytatem obok wartości w profilu. Awaria zapytania to komunikat, nie pusta
  lista.
- Testy: `test_contract_partner_reads_reader.py`, `test_contract_partner_reads_service.py`
  (bez bazy), `test_contract_partner_reads_api.py`, `PartnerReadsList.test.tsx`.
