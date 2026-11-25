# Rozliczenia: ZIP w poczcie i raport zbiorczy Credit Agricole

<!-- indeks: ZIP, zip_files, hasło ZIP, CONSULTANT_PORTAL_ZIP_PASSWORD, ZipCrypto, AES, CP852, Unicode Path, Dokumenty.zip, PKO, Credit Agricole, Raport rozliczenia outsourcingu, report_ca, TE, Czas 0%, nadgodziny, raport zbiorczy kilku osób, odbiór usług -->

Od 23.11.2026. W próbie rozliczeń IX–X 2026 (kopia produkcji z 23.11) sześć przypadków
nie miało MD, choć raport był w poczcie rozliczeń, bo leżał w ZIP-ie: raport zbiorczy
Credit Agricole (trzy kontrakty × IX i X) i „Dokumenty.zip” konsultanta PKO za X.

## ZIP w mailu (`consultant_portal/zip_files.py`)

- Czytnik poczty (`mailbox._ingest_message`) zamienia każdy załącznik `.zip` na pliki
  ze środka, zanim cokolwiek je klasyfikuje; te pliki idą dalej jak zwykłe załączniki
  (raport T4T, raport zbiorczy, identyfikacja nadawcy, `kind_of_file`). Tak samo pliki
  przekazanego maila.
- Jeden poziom: ZIP w ZIP-ie zostaje plikiem. Arkusze i dokumenty Office (też ZIP-y)
  nie są rozpakowywane, bo rozpakowujemy tylko nazwy `.zip` bez `[Content_Types].xml`.
- Limity: 50 plików, 20 MB na plik, 50 MB razem. ZIP, z którego nic nie wyszło (złe
  hasło, uszkodzony), zostaje jak dotąd i czytnik go pomija.
- Nazwy: bez flagi UTF-8 przekodowujemy CP437 → CP852 (archiwizator Windows). Nazwę
  z pola Unicode Path (PKO) Python 3.12+ podaje już poprawnie, więc jej nie ruszamy.
- Plik szyfrowany AES (WinZip, `compress_type` 99) zostaje w archiwum: biblioteka
  standardowa go nie otwiera. W „Dokumenty.zip” PKO za X 2026 dwa pliki za IX są w AES
  (hasła nie znamy); pliki za X są bez hasła.
- Mail klienta „Odbiór usług …” (`.msg`) to raport, nie faktura (`_REPORT` w `mailbox.py`).

## Hasło ZIP-a

- `CONSULTANT_PORTAL_ZIP_PASSWORD` (kilka haseł po przecinku; czytnik próbuje po kolei,
  bo bajt kontrolny ZipCrypto przepuszcza co 256. złe hasło, a CRC je łapie).
- Decyzja Artura z 23.11.2026: zmienna środowiskowa, nie pole w regułach klienta.
  Ustawia się ją wyłącznie workflow „Coolify set env” z sekretem repo
  (`value_from_secret`): nazwa kończy się na `PASSWORD`, więc workflow odrzuci jawną
  wartość, której input byłby widoczny w publicznym logu Actions.
- Hasła ani sposobu, w jaki DL je opisuje w treści maila, nie zapisujemy w repo, PR-ach,
  testach ani logach. Testy używają fikcyjnego hasła i budują ZIP w `tests/zip_crypto.py`.
- Pusta zmienna = ZIP z hasłem czeka na człowieka (jak przed 23.11).

## Zły ZIP albo zły mail nie zatrzymuje czytnika (audyt 24.11.2026)

- Złe hasło, które przeszło bajt kontrolny, daje przy deflate `zlib.error`, a nie błąd
  CRC. Uszkodzony strumień (`zlib.error`, `LZMAError`, bzip2 `OSError`) przy pliku
  z hasłem znaczy „próbuj następnego hasła”, bez hasła — plik pominięty. Wcześniej
  `zlib.error` wychodził z `zip_files.expand` i czytnik stawał na tym mailu.
- `mailbox.run_once`: mail, na którym `_ingest_message` rzuca wyjątek, zatrzymuje
  znacznik najwyżej `MAX_MESSAGE_ATTEMPTS` (5) biegów z rzędu. Potem znacznik idzie
  dalej, w logu idzie ERROR (alarm w Sentry), a przy `internal`/`all` cały mail
  zostaje kartą `.eml` bez kontraktu do ręcznego przypisania (w pilotażu sam alarm).
- Awaria Graph (429, 5xx, brak tokenu) albo połączenia z bazą nie liczy się do limitu.
- Licznik stoi w `cp_mailbox_state.last_error` jako `message_failed:<skrót id>:<n>`
  (bez migracji), a obok, po `;`, `message_abandoned:<skrót>,<skrót>` — porzucone
  maile, które jeszcze wracają w zakładce `OVERLAP` (najwyżej `MAX_ABANDONED_KEYS`, 8).
  Porzucone trzymamy osobno od licznika, bo przy jednym polu drugi padający mail
  nadpisywał licznik, porzucony wracał, padał od nowa i znacznik stał w kółko
  (przegląd PR #3953). Błąd listy z Graph zapisuje kod błędu przed tym stanem,
  nie zamiast niego.

## Raport „Raport rozliczenia outsourcingu” (`client_settlements/report_ca.py`)

- Klient generuje go dla dostawcy co miesiąc; DL przekazuje go na rozliczenia@ z adresu
  firmowego jako „PD: … naliczenie za miesiąc RRRR.MM” z `NNNN_Raport_Rozliczenia_MM_RRRR.zip`.
- Arkusz: „Raport za miesiąc: RRRR.MM”, wiersz nagłówka „Pracownik Nazwisko Imie · Nr Ewid ·
  PID · … · Czas 0% · Czas 100% · Czas 150% · Czas 200% · TE · Stawka Netto · Kwota Netto”,
  wiersz na osobę i projekt, potem „Podsumowanie”.
- **MD = suma „TE” wierszy osoby.** Próba IX–X: 6 z 6 równe fakturom Finansów.
  „Czas 0%” (wiersz ABS) to godziny bez wynagrodzenia: informacja na karcie, nie MD.
  „Czas 150% / 200%” > 0 to uwaga dla Finansów (nadgodziny), MD bez zmian.
- Miesiąc z arkusza, nie z tematu maila; inny niż rozliczany = `proof.month` bez MD
  (`declared.evaluate`), jak w innych czytnikach.

## Komu trafia raport zbiorczy (`mailbox._store_client_reports`)

- Każda osoba z arkusza po imieniu i nazwisku (`identity.resolve_named_in_text`); ten sam
  plik zapisujemy jako raport miesiąca każdej znalezionej osoby. Czytnik rozliczenia bierze
  z niego tylko wiersz tej osoby.
- Warunki, bo arkusz może przysłać każdy: wszystkie znalezione osoby u **jednego klienta**,
  a nadawca z adresu firmy albo z domeny tego klienta. Inaczej raport idzie zwykłą ścieżką
  (karta do ręcznego przypisania).
- Osoba z arkusza bez kontraktu w NEXUS-ie nic nie dostaje (wpis w logu). Pilotaż portalu:
  tylko osoby z pilotażu, chyba że czytnik bierze wszystkich nadawców.
- Para (mail, plik) jest unikalna w `cp_documents`, więc `graph_message_id` ma tylko pierwsza
  kopia; kolejne odczyty tego samego maila to duplikaty po (kontrakt, rodzaj, plik).

## Pomiar (kopia `nexus_staging_klodko_v4r2`, tylko odczyt i rollback)

Trzy maile z archiwum rozliczeń (CA IX, CA X, PKO X) przez `_ingest_message`:
trzy osoby CA: IX 17 / 22 / 22 MD, X 22 / 22 / 22 MD, wszystkie „ok”; PKO za X 22 MD
(uwaga „Time Sheet za inny miesiąc”: szablon klienta ma w nagłówku poprzedni miesiąc).
Na main te same maile: 0 dokumentów (ZIP pominięty). Korekta CA za VIII (osobny mail)
też się czyta.
