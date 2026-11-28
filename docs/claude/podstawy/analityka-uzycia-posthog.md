# Analityka użycia ekranów i przycisków — PostHog Cloud EU, domyślnie wyłączona
<!-- indeks: USAGE_ANALYTICS_ENABLED, POSTHOG_PROJECT_KEY, phc_, /api/health/live usageAnalytics, lib/usage-analytics.ts, UsageAnalytics.tsx, routePattern, data-track, ui_click, $pageview, eu.i.posthog.com, CSP connect-src, notatka do zespołu -->

Decyzja Artura z 28.11.2026: PostHog Cloud EU (Frankfurt, darmowe 1 mln zdarzeń
na miesiąc) zamiast Umami na własnym serwerze. Cel: usuwać ekrany i przyciski, których
nikt nie używa, i sprawdzać, czy nowe funkcje są używane. To pomiar pracy zespołu,
więc zespół dostaje informację przed włączeniem, a zbieramy najmniej, ile się da.

## Włączenie: backend, nie build frontu

Front od 13.11.2026 jest osobną aplikacją Coolify `nexus-frontend`, której zmienne
skopiowano raz przy `create` (`.github/scripts/coolify_frontend_app.py`), a workflow
„Coolify set env” pisze tylko do aplikacji compose. Zmienna `NEXT_PUBLIC_*` ustawiona
tym workflow nie dotarłaby do builda frontu. Dlatego (wybór Artura 28.11.2026):

- backend: `USAGE_ANALYTICS_ENABLED` (domyślnie `false`, rejestr flag z terminem)
  i `POSTHOG_PROJECT_KEY` (klucz projektu `phc_…`),
- sonda przeglądarki `/api/health/live` niesie `usageAnalytics`: klucz albo `null`.
  `null` przy wyłączonej fladze, braku klucza i złym formacie, także przy kluczu
  osobistym `phx_…`, bo ten czyta dane projektu (`app/core/usage_analytics.py`),
- front ładuje `posthog-js` dopiero po kluczu z sondy (`import()` w
  `lib/usage-analytics.ts`). Bez klucza zero zapytań do PostHog i zero kodu SDK w karcie.

Kolejność:

1. Artur zakłada konto i projekt w regionie **EU** i w ustawieniach projektu włącza
   „Discard client IP data” (SDK nie umie wyciąć IP po swojej stronie).
2. Klucz projektu (Project settings → Project API key, `phc_…`) jako sekret repo
   `POSTHOG_PROJECT_KEY`, potem workflow „Coolify set env”: `key=POSTHOG_PROJECT_KEY`,
   `value_from_secret=POSTHOG_PROJECT_KEY`, `is_buildtime=false`. Klucz jest publiczny
   z natury (trafia do każdej przeglądarki), ale przez sekret nie zostaje w podsumowaniu
   uruchomienia ani w logu, a repo i logi Actions są publiczne.
3. Notatka do zespołu (szkic w opisie PR-a, który wprowadził pomiar; wysyła Artur).
4. `USAGE_ANALYTICS_ENABLED=true` tym samym workflow, Deploy w oknie 18:00–08:00
   (zmienna runtime, bez przebudowy frontu).
5. Sprawdzenie: `curl -s https://api.nexus.b2bnetwork.pl/api/health/live` ma
   `usageAnalytics: "phc_…"`, a w PostHog → Activity po kilku minutach są `$pageview`
   z `$pathname` w postaci `/candidates/[id]` i `ui_click`. Żadnego adresu z liczbą.

Wyłączenie: `USAGE_ANALYTICS_ENABLED=false` i deploy. Klucz nie jest pamiętany
w przeglądarce, więc pomiar kończy się przy następnym wczytaniu strony.

## Co wychodzi

Tylko dwa zdarzenia, resztę odrzuca `before_send` (`scrubEvent`):

- `$pageview` przy zmianie **wzorca** trasy (`routePattern`): wartości z `useParams()`
  zamienione na `[nazwa]`, inny człon niewyglądający na statyczny na `[id]`; bez query
  stringa i hasha. Każdy statyczny katalog z `src/app/` przechodzi bez zmian (test).
- `ui_click` z `target` (`data-track` albo nazwa dostępności), `source`
  (`data-track` / `nazwa` / `brak`) i `element` (tag albo rola).
- Osoba: `user-<id>` (bootstrap, bez `$identify`) i rola jako właściwość zdarzeń.
  Bez maila, nazwiska i właściwości osoby.

`before_send` wycina też każdą właściwość z adresem, tytułem strony (bywa w nim
nazwisko), źródłem wejścia (`utm_*`, referrer), `$set_once` i każdą wartość, która jest
obiektem albo adresem. `$current_url` i `$pathname` są nadpisane wzorcem.

Nazwa przycisku idzie tylko, gdy wygląda na etykietę interfejsu (`safeLabel`): do 60
znaków i 6 słów, bez cyfr i znaków adresów, bez wielkiej litery po pierwszym słowie
(imiona, nazwiska, firmy; skróty do 4 liter jak CV, DL, B2B przechodzą). W wierszach
tabel i list (`tr`, `li`, `role=row|gridcell|listitem|option`) widoczny tekst nie idzie
wcale, tylko `aria-label` / `title` wpisane w kodzie.

**Nowy przycisk, który chcemy mierzyć:** `data-track="obszar.akcja"` (małe litery,
kropki, myślniki, do 64 znaków), np. `data-track="cv.download"`. Nazwa jest stała
w kodzie, więc nie zależy od tekstu przycisku ani od danych w wierszu.

## Czego nie ma i nie włączamy bez decyzji Artura

Autocapture, nagrania sesji, heatmapy, dead/rage clicks, ankiety, product tours,
eksperymenty, flagi PostHog (`/flags`), zdalna konfiguracja i skrypty z CDN PostHog
(`disable_external_dependency_loading`), wyjątki (to robi Sentry), web vitals.
Gdyby nagrania kiedyś włączyć, konfiguracja już maskuje cały tekst i pola i blokuje
media, jak Replay w Sentry (`observability.md`), ale `disable_session_recording`
i brak skryptu rekordera trzeba wtedy świadomie zdjąć.

Nie mierzymy: stagingu (`NEXT_PUBLIC_NEXUS_ENV=staging`), harnessów `/preview/*`,
„Podglądu jako” admina, stron bez zalogowanej osoby (kariera, `/k`, `/sign`, `/apply`).
Persystencja `memory`: SDK nie zapisuje ciasteczek ani `localStorage`.

## CSP

`connect-src` ma `https://eu.i.posthog.com` (`lib/csp.ts`, `POSTHOG_CONNECT_ORIGIN`).
Żadnego hosta PostHog w `script-src`; `eu-assets.i.posthog.com` celowo nie ma, bo SDK
nie ładuje skryptów z zewnątrz. Test: `csp.test.ts`.

## Wersja SDK

`posthog-js` w dokładnej wersji w `frontend/package.json` (bez `^`). Aktualizacja to
osobny PR po co najmniej dwóch tygodniach od wydania wersji; sprawdź w notatkach
wydania, czy nie zmieniły się domyślne wartości opcji z `initOptions`.

## Testy

- `frontend/src/lib/__tests__/usage-analytics.test.ts` — wzorce tras, etykiety,
  kliknięcia w wierszach, `before_send`.
- `frontend/src/components/__tests__/UsageAnalytics.test.tsx` — brak inicjalizacji bez
  flagi, przy starszym API, kluczu `phx_`, „Podglądzie jako”, na stagingu i `/preview`;
  opcje `init` przy włączonej fladze.
- `backend/tests/test_usage_analytics_key.py` — klucz w sondzie tylko przy fladze
  i w formacie `phc_`.

## Jak czytać dane

Ekran z zerem odsłon w 4 tygodnie to kandydat do rozmowy, nie do usunięcia od razu:
sprawdź, czy to ekran rzadkiej czynności (koniec miesiąca, roczny przegląd) i czy
wejście nie idzie inną drogą (Jarvis, link w mailu). Przycisk `source=brak` to
kliknięcie bez bezpiecznej nazwy: gdy jest ważny, dostaje `data-track`.
Uzupełnia licznik obszarów do przeglądu dostępów
(`uprawnienia/licznik-uzycia-obszarow.md`), który liczy wejścia osoby w obszar.
