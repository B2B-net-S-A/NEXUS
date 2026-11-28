# Skan plików z zewnątrz (ClamAV) i ALTCHA na formularzach zgłoszeń

<!-- indeks: clamd INSTREAM, EICAR, fail-closed / fail-open, sonda clamav w /api/health, ALTCHA proof-of-work, altcha_spent_challenges, ALTCHA_HMAC_KEY, ALTCHA_REQUIRED, przejście do 01.12 -->

Decyzja Artura z 28.11.2026: pakiet „Ochrona wejścia” jako pierwszy z przeglądu
narzędzi. Powód: publiczny upload CV przyjmował plik od dowolnej osoby
z internetu bez skanu antywirusowego i bez ochrony przed botami (był tylko limit
slowapi i pułapka `website`). Odrzucone: Cloudflare Turnstile i reCAPTCHA, bo to
zewnętrzny skrypt u kandydata (ciasteczka, zgoda RODO, a API i tak nie stoi za
Cloudflare).

## ClamAV (GPL-2.0)

- **Usługa `clamav`** w `docker-compose.yml` i `docker-compose.staging.yml`:
  obraz `clamav/clamav:<wersja>-debian13-slim` (alpine nie ma arm64, a staging
  stoi na laptopie), `clamd` i `freshclam` w jednym kontenerze, sygnatury
  w wolumenie `clamav_data`, aktualizacja 12 razy na dobę. Backend i worker
  dostają `CLAMAV_HOST=clamav` z compose; pusty `CLAMAV_HOST` = skan wyłączony
  (dev, CI bez Dockera).
- **Pamięć: `mem_limit` 1536m.** Pomiar 28.11.2026: 0,97 GiB po załadowaniu
  sygnatur. `ConcurrentDatabaseReload no`, bo przy przeładowaniu sygnatur clamd
  trzymałby dwie kopie bazy (ok. 2,3 GiB); skany czekają wtedy ok. 30 s, stąd
  `CLAMAV_TIMEOUT_SECONDS` 45. Suma limitów kontenerów na nexus-prod rośnie
  z ok. 28 do ok. 29,5 GiB przy 31,3 GiB hosta bez swapu (Artur wybrał nexus-prod
  zamiast serwera bezpieczeństwa, 28.11.2026). Podniesienie limitu clamd albo
  nowa usługa = najpierw budżet z `pamiec-postgresa.md`.
- **Skan przed zapisem:** `services/file_scan.py` wysyła bajty komendą
  `zINSTREAM` po TCP, kawałkami po 64 KB, zanim plik trafi do magazynu, bazy,
  ekstraktora tekstu albo odczytu tożsamości z CV.

### Gdzie i z jaką polityką

| Wejście | Kod | Wirus | clamd niedostępny |
|---|---|---|---|
| Strona kariery `POST /api/public/career/apply` | `require_clean_public_upload` | 422 przy `cv` | **503, bez zapisu** |
| Link rekrutera `POST /api/public/apply/{token}` | j.w. | 422 przy `cv` | **503** |
| Serwer strony WWW `POST /api/public/website-applications` | j.w. | 422 przy `cv` | **503** |
| Rekruter wgrywa CV / dokument (`_read_upload_bounded` w `api/candidates.py`: profil, etap, wtyczka LinkedIn) | `require_clean_internal_upload` | 422 „Skaner antywirusowy odrzucił ten plik” | przepuszcza, ostrzeżenie w logu |
| Załączniki z poczty M365 (`m365/attachment_handler.py`) | `scan_internal` | plik nie trafia na dysk, `parse_error = virus_found: <sygnatura>` (końcowy, bez ponowień) | zapis jak dotąd, ostrzeżenie w logu |

- **Publiczne = fail-closed.** Plik z internetu bez werdyktu skanera nie wchodzi.
  Kandydat widzi „Nie możemy teraz sprawdzić pliku. Spróbuj ponownie za kilka
  minut.”, a strona WWW dostaje 503 (jej formularz pokazuje błąd, kandydat
  ponawia). clamd ma `restart: unless-stopped`, więc przerwa to zwykle minuty.
- **Wewnętrzne = fail-open.** Rekruter ma plik od znanej osoby, a awaria skanera
  nie może zatrzymać pracy zespołu. Ostrzeżenie w logu zostaje.
- **Komunikat dla kandydata przy wirusie** jest celowo neutralny: „Nie udało się
  przyjąć pliku. Wyślij CV ponownie w PDF albo DOCX.” Nie mówimy „wirus”, bo
  zwykle to zainfekowany komputer kandydata, a nie atak, a komunikat nie ma
  podpowiadać atakującemu, co wykrył skaner.
- Pozostałe uploady w aplikacji (ok. 70 modułów: finanse, HR, kontrakty) są
  wewnętrzne i nieskanowane. Nowe wejście pliku **z zewnątrz** (formularz bez
  logowania, poczta, integracja) = skan przez `file_scan` przed zapisem.

### Zdarzenie w logu

Każdy skan to linia JSON `event_kind="file_scan"` z polami `scan_verdict`
(`clean` / `infected` / `unavailable`), `scan_source`, `scan_policy`
(`fail_closed` / `fail_open`), `size_bytes`, `sha256`, przy wirusie `signature`,
przy awarii `failure_kind`. Wirus = `WARNING`, brak skanera na publicznym
formularzu = `ERROR`. **Bez nazwy pliku** (zwykle imię i nazwisko kandydata).
Loki i Wazuh filtrują po `event_kind`.

### Sonda

`checks.clamav` w `/api/health`: `healthy` (`zPING` → `PONG` w 2 s),
`unhealthy`, `disabled` (pusty `CLAMAV_HOST`). Informacyjna, nie zmienia
`status` ani kodu HTTP: bez clamd publiczny upload odpowiada 503, ale reszta
aplikacji działa, a restart backendu clamd nie naprawi.

### Jak sprawdzić ręcznie

Sam EICAR nie przejdzie bramki formatu CV (415), a EICAR wklejony w środek PDF-a
clamd przepuszcza (sygnatura wymaga go na początku pliku). Plik testowy to DOCX
z wpisem `word/media/eicar.com` (`tests/_clamd_fake.py::eicar_docx`): przechodzi
bramkę formatu, a clamd 1.5 zgłasza `Eicar-Test-Signature` (sprawdzone na
prawdziwym clamd 28.11.2026). Testy bez Dockera używają udawanego clamd z tego
samego pliku.

## ALTCHA (MIT) na anonimowych formularzach

- **Gdzie:** strona kariery (`QuickApply`, `OfferApply` → `lib/career/submit.ts`)
  i `/apply/[token]` (`ApplyForm`). To jedyne formularze bez sekretu w linku:
  slug strony kariery jest publiczny, a link rekrutera wisi na LinkedInie.
- **Gdzie nie (decyzja Artura 28.11.2026):** „Twoje warunki”, raport kompetencji,
  panele klienta i zespołu, rezerwacje rozmów, deklaracja zaangażowania. Mają
  sekretny token z maila (bot bez tokenu dostaje 404) i limit slowapi, więc
  zagadka niczego tam nie chroni, a dokłada sekundę i punkt awarii u klienta.
- **Jak działa:** `GET /api/public/career/challenge` (limit 30/min, `no-store`)
  wydaje wyzwanie `{algorithm, challenge, maxnumber, salt, signature}`:
  `salt` = losowe 12 bajtów + `?expires=<unix>` (ważność 30 min),
  `challenge` = SHA-256(salt + liczba), `signature` = HMAC-SHA256(klucz, challenge).
  Przeglądarka (`lib/altcha.ts`, WebCrypto) szuka liczby od 0 do `maxnumber`
  (100 000, średnio pół sekundy do dwóch) i wysyła base64 JSON-a w polu `altcha`.
  Liczenie rusza przy pierwszym dotknięciu formularza; kandydat niczego nie
  klika. Format to protokół ALTCHA v1, własna implementacja bez zależności.
- **Weryfikacja** (`services/altcha.py::verify`, przed odczytem CV): algorytm,
  podpis (`compare_digest`), rozwiązanie, termin z soli (sól jest w skrócie, więc
  przedłużenie terminu psuje rozwiązanie). Odmowa = 400 „Nie udało się potwierdzić
  wysyłki formularza. Odśwież stronę i wyślij zgłoszenie ponownie.” i linia
  `event_kind="altcha"` z `reason` (`missing`, `malformed`, `algorithm`,
  `bad_signature`, `bad_solution`, `expired`, `replayed`).
- **Powtórka:** jedno rozwiązanie = jedno zgłoszenie. Kilka procesów web nie
  dzieli pamięci, więc zużyte wyzwanie trafia do tabeli `altcha_spent_challenges`
  (migracja 0805, DDL `services/altcha_schema.py`, lustro w `entrypoint.sh`, sonda
  w `/api/health/deep`) przez `INSERT … ON CONFLICT DO NOTHING`. Zapis idzie
  w transakcji zgłoszenia: zgłoszenie, które padło dalej (brak zgody, zły e-mail),
  nie zużywa zagadki. Wygasłe wiersze kasuje każde kolejne przyjęcie.
- **Klucz HMAC:** `ALTCHA_HMAC_KEY`, ustawiany wyłącznie workflow „Coolify set env”
  z `value_from_secret`. Pusty = klucz wyprowadzony z `SECRET_KEY`
  (HMAC z etykietą `nexus-altcha-v1`), więc wdrożenie nie czeka na sekret, a podpis
  zagadki nie jest podpisem JWT. Zmiana klucza unieważnia tylko wyzwania wydane
  w ostatnich 30 minutach.
- **Przejście:** strony dla osób z zewnątrz nie przeładowują się same
  (`wersja-frontu-w-otwartej-karcie.md`), a front i backend wdrażają się osobno.
  Do `MISSING_ALLOWED_UNTIL` (01.12.2026, 08:00 Warszawa) zgłoszenie **bez**
  rozwiązania przechodzi z linią `altcha_outcome=missing_allowed`; złe
  rozwiązanie odpada od razu. Po tej dacie brak = 400. Stałą można usunąć
  w dowolnym PR-ze po 01.12.
- **Wyłącznik:** `ALTCHA_REQUIRED=false` (workflow „Coolify set env”) przyjmuje
  zgłoszenia bez zagadki, jak przed 28.11 — gdyby jakaś przeglądarka jej nie
  liczyła. Testy mają ją wyłączoną w `conftest.py`; ścieżki odmowy sprawdzają
  `test_altcha.py` i `test_public_apply_protection.py`.
