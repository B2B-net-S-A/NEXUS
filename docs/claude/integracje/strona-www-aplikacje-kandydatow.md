# Aplikacje kandydatów ze strony B2B Network (`POST /api/public/website-applications`)

Decyzja Artura 24.11.2026: CV i aplikacje ze strony WWW idą do NEXUSA, a briefy
klientów e-mailem. Strona (osobne repo) wysyła formularz ze swojego serwera, nie
z przeglądarki kandydata. Kod: `app/api/public_website_applications.py` (trasa)
i `app/services/website_applications.py` (logika), testy w
`tests/test_public_website_applications.py`.

## Kontrakt

- `multipart/form-data`, puste pola nie są wysyłane: `source` (`baza` | `oferta`),
  `offer_slug`, `offer_title`, `first_name`, `last_name` (przy ofercie), `email`,
  `linkedin` (przy `baza`, zamiast CV albo obok), `rate`, `available_from`, `city`,
  `work_mode`, powtarzane `consent` (dosłowna treść każdej zaznaczonej zgody) i `cv`.
- Każda odpowiedź inna niż 2xx kończy się błędem u kandydata. Dlatego 422 dostaje
  tylko to, bez czego zgłoszenia nie ma: e-mail, zgoda, CV albo LinkedIn, imię
  i nazwisko przy ofercie, poprawny plik CV (413/415 jak w `/apply`). Pole
  opcjonalne, które się nie czyta, nie blokuje zgłoszenia. Przykłady: „Dostępny od”
  to wolny tekst („1 grudnia”), stawka może wypaść poza 1–10 000. Takie pole zostaje
  surowe w `raw_payload` i w opisie wpisu w kolejce.
- Tryb pracy przychodzi jako etykieta strony („Zdalnie”, „Hybryda”, „Stacjonarnie”)
  i jest mapowany na `remote` / `hybrid` / `onsite`. Od 25.11.2026 pole może się
  powtarzać i nieść wartości techniczne (`remote`, `hybrid`, `onsite`).

## Raport kompetencji (`report=1`, decyzje Artura 25.11.2026)

Nowy formularz `/dla-specjalistow#raport` wysyła na `source=baza` dodatkowe pola.
Strona wybiera je z list, więc zła wartość to błąd strony i dostaje 422 z `loc`
pola (wyjątek od zasady „pole opcjonalne nie blokuje”). `report=1` wymaga CV
(sam LinkedIn nie wystarczy, bo bez CV nie policzymy technologii) i stawki 1–2000;
przy `oferta` dostaje 422.

| Pole | Wartość | W NEXUSIE |
|---|---|---|
| `report` | `1` | wiersz `competence_reports` (`waiting_cv`, termin `send_due_at` = zgłoszenie + 23 h, opiekun) |
| `rate` | zł/h netto, 1–2000 | `expected_rate_hourly`: nowa osoba w konstruktorze, osoba w bazie przez `update_candidate_profile_rate` (`source = website`) |
| `current_rate` | zł/h, 1–2000 | tylko `conditions` raportu i `raw_payload.current_rate_hourly`; writera obserwacji stawki „obecnej” nie ma, a `expected_rate_hourly` w zgłoszeniu czyta historia stawek |
| `contract` | `b2b` \| `uop` \| `any` | `b2b_willingness` (`b2b` → `b2b`, `uop` → `employment_only`, `any` bez zmiany) i `preferences.contract_types` |
| `work_mode` (powtarzane) | `remote` \| `hybrid` \| `onsite` | `set_profile_work_mode`; samo `remote` = 0 dni w biurze |
| `office_days_max` | 0–5 | `max_onsite_days_per_week` (przy `hybrid`/`onsite`; bez trybu tryby wynikają z dni) |
| `office_city` (powtarzane, najwyżej 10) | do 120 znaków | `preferences.office_cities` (przycięte, bez powtórek) |
| `start` | `now` \| `1m` \| `2-3m` \| `browsing` | `now` = dziś (kalendarz firmy) i 0 dni wypowiedzenia; `1m`/`2-3m` = 1/2 miesiące wypowiedzenia; `browsing` = `availability_status = open_to_offers`, gdy było `unknown` |

Zapis idzie przez `services/website_application_terms.py` (te same writery co
`candidate_terms_apply`). Nowa osoba: wszystkie pola od razu. **E-mail już
w bazie**: osoba też dostaje raport, a warunki idą do profilu, ale pole, które
człowiek zmienił w ostatnich 14 dniach (`profile_rate_changed`,
`candidate_work_mode_changed` albo zwykła edycja profilu `updated`), zostaje.
CV dalej czeka w zgłoszeniu i profilu nie zmienia. Co zapisano, a co zostało:
`details.terms` wpisu `applied_via_website`. Bez `report=1` osoba w bazie
zostaje bez zmian jak dotąd.

Opiekun raportu: po kolei z `competence_report_owners` (lista admina; najdawniej
przypisany, remis po `position`; konto wyłączone pomijane). Pusta lista = raport
bez opiekuna. Kod: `services/competence_report_store.py`, DDL
`services/competence_report_ddl.py` (migracja 0785 i siatka `entrypoint.sh`).

## Poświadczenie: sekret w env, świadomy wyjątek

`Authorization: Bearer <WEBSITE_APPLICATIONS_TOKEN>`, porównanie
`secrets_equal` w stałym czasie, sprawdzane **przed** odczytem treści multipart.
Pusty sekret oznacza 401 na wszystko.

Reguła z `podstawy/konta-serwisowe-klucze-api-x-api-key.md` mówi, że globalny
sekret z env-a jest do wycofania. Tu Artur 24.11.2026 wybrał jednak sekret w env.
Klucz konta serwisowego wygasa najpóźniej po 365 dniach, a wtedy kandydaci
widzieliby błąd, dopóki ktoś nie wyda nowego. Strona wysyła już Bearer. Nie
przenoś tej trasy na `X-API-Key` bez nowej decyzji.

Wartość ustawia się tylko przez workflow „Coolify set env” (`value_from_secret`).
W Coolify strony ten sam sekret leży w `NEXUS_APPLY_TOKEN`.

## Limit

Cały ruch przychodzi z jednego adresu (serwer strony), więc kubełek
`client_ip_key` jest wspólny dla wszystkich kandydatów. Limit per osoba stosuje
strona. W NEXUSIE jest sufit `60/minute; 300/hour` (decyzja Artura 24.11.2026).
Limit z `/apply` (5/min, 30/h) odrzucałby kandydatów przy zwykłym ruchu.

## Gdzie trafia zgłoszenie

- Nowy e-mail: kandydat ze źródłem `strona WWW`, `created_by` puste, CV jako główny
  dokument (`external_source = website`), odczyt CV w tle. Proces nie powstaje,
  bo oferty żyją na stronie, nie w `/jobs`.
- E-mail już w bazie: kandydat **bez zmian** (P0-CAND-01), poza warunkami przy
  `report=1` (sekcja wyżej). CV leży bezwładnie przy `application_submissions`.
- W obu gałęziach powstaje wpis `pending_review` w „Zgłoszeniach” (`/applications`)
  z `matched_candidate_id` (decyzja Artura 24.11.2026). Zgłoszenie nie ma linku
  ani rekrutera, więc dzwonek nie ma adresata, a kolejka jest jedynym miejscem,
  w którym ktoś je zobaczy. Przy nowej osobie „Połącz” zamyka wpis (CV nie
  dubluje się, bo `_attach_cv_as_document` porównuje skrót).
- NEXUS nie wysyła maila do kandydata, bo potwierdzenie wysyła strona.
  **Wyjątek: raport kompetencji** (decyzja Artura 25.11.2026). Osoba, która
  wysłała `report=1`, dostaje od NEXUSA raport w 24 godziny; potwierdzenie
  zgłoszenia dalej wysyła strona.

## Zgody

Treść zgód żyje na stronie, nie w `services/career_consent.py`. Wiersz
`candidate_consents` niesie więc dosłowną treść w `consent_text` (0772) obok
`text_sha256`, `given_at` i `text_version = "www"`. To jest dowód zgody
z RODO art. 7 ust. 1. Rodzaj: `baza` ma `recruitment_current_future`, a przy
ofercie pierwsza zgoda to `recruitment_current`, kolejne `recruitment_future`
(kolejność z `src/lib/forms/parse.ts` strony).
