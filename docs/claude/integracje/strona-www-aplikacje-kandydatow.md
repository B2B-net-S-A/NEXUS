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
  i jest mapowany na `remote` / `hybrid` / `onsite`.

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
- E-mail już w bazie: kandydat **bez zmian** (P0-CAND-01). CV leży bezwładnie
  przy `application_submissions`.
- W obu gałęziach powstaje wpis `pending_review` w „Zgłoszeniach” (`/applications`)
  z `matched_candidate_id` (decyzja Artura 24.11.2026). Zgłoszenie nie ma linku
  ani rekrutera, więc dzwonek nie ma adresata, a kolejka jest jedynym miejscem,
  w którym ktoś je zobaczy. Przy nowej osobie „Połącz” zamyka wpis (CV nie
  dubluje się, bo `_attach_cv_as_document` porównuje skrót).
- NEXUS nie wysyła maila do kandydata, bo potwierdzenie wysyła strona.

## Zgody

Treść zgód żyje na stronie, nie w `services/career_consent.py`. Wiersz
`candidate_consents` niesie więc dosłowną treść w `consent_text` (0772) obok
`text_sha256`, `given_at` i `text_version = "www"`. To jest dowód zgody
z RODO art. 7 ust. 1. Rodzaj: `baza` ma `recruitment_current_future`, a przy
ofercie pierwsza zgoda to `recruitment_current`, kolejne `recruitment_future`
(kolejność z `src/lib/forms/parse.ts` strony).
