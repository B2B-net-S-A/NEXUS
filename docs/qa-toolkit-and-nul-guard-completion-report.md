# Pakiet testowy QA, jego odbiór i guard NUL — raport (15–16.09.2026)

Raport obejmuje dwie rzeczy, bo druga wynika wprost z pierwszej:

1. **odbiór wdrożenia pakietu testowego** (PR #1549, `8b6b739e`) — co pakiet
   dostarcza i co wyszło przy sprawdzaniu go na produkcji,
2. **naprawy, które ten odbiór wymusił** (PR #1553, `d54beecc`) — systemowe
   odrzucanie NUL w całym API oraz koniec z traktowaniem `detail` z FastAPI
   jak tekstu w interfejsie.

## 1. Pakiet testowy (#1549) — stan

Dostarczone (opis techniczny i uruchamianie: `qa/README.md`):

| Warstwa | Zakres |
|---|---|
| Hypothesis + time-machine | właściwości stawek, walut i jednostek; precyzja MD i godzin; daty Europe/Warsaw, DST, rok przestępny; polskie kwoty i permutacje kolumn XLSX; idempotencja budżetu przy wielokrotnym imporcie |
| Schemathesis | 5 uwierzytelnionych kontraktów GET na efemerycznym stacku CI, OpenAPI eksportowane z uruchomionej aplikacji |
| k6 | rekrutacja, kontrakty i zamówienia, dashboardy; smoke automatycznie, rampa do 100 VU ręcznie |
| Zabezpieczenia | testy HTTP wyłącznie przeciw localhostowemu stackowi E2E, wymagane `QA_CONFIRM=nexus-e2e`, tokeny z prawami 0600 poza artefaktami |

Wdrożenie: PR zmergowany 15.09 o 15:17 UTC, [Deploy 34987664618](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34987664618)
zakończony sukcesem, produkcja serwowała `8b6b739e` (`deployedAt` 15:20 UTC).
`/api/health` i `/api/health/deep` healthy, `/api/health/alembic` zgodny
(`0310_dl_alerts_my_clients_panel`, `orphaned: []`). Ten PR nie miał migracji.

### Post-deploy E2E: czerwony, ale nie z powodu regresji

[E2E 34988319871](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34988319871):

- job **produkcyjny `prod-smoke` wykonał 0 testów** — padł na warunku wstępnym,
  bo w repo nie ma sekretów `E2E_USER_EMAIL`/`E2E_USER_PASSWORD`; job
  skomentował [issue #1551](https://github.com/B2B-net-S-A/NEXUS/issues/1551).
  Zmienną `E2E_POST_DEPLOY_ENABLED` włączono o 15:07 UTC mimo braku konta
  i cofnięto o 15:30 UTC. Szczegóły i kroki właściciela (konto, wyjątek
  break-glass dla produkcji SSO-only, sekrety) są w
  `docs/integrations-monitoring-deploy-fixes-completion-report.md` (MON-02),
- job **stackowy przeszedł**: Playwright `@stack` 16/16 bez pominięć,
  Schemathesis 17/17 (0 porażek, błędów i pominięć), k6 smoke bez przekroczonych
  progów.

Uwaga do czytania wyników: ręczne i nocne biegi bez sekretów kończą się
„zielonym częściowym" (tylko `preview-chromium`), więc zielony job produkcyjny
sam w sobie nie dowodzi, że `prod-smoke` przeszedł.

### Co znalazł odbiór w przeglądarce

Lista kandydatów renderowała się, zwykłe wyszukiwanie działało (200). Natomiast
fraza z NUL:

- interfejs **nie usuwał** NUL (wartość pola: `Java` + U+0000, adres `?q=Java%00`),
- backend odpowiadał **poprawnie 422** w 102 ms — czyli regresja z #1549 była
  naprawiona,
- ale strona przechodziła w globalny ekran „Coś poszło nie tak" i raportowała do
  Sentry: panel błędu listy wstawiał do JSX tablicę `detail`
  (`{type, loc, msg, input, ctx}`), co React odrzuca błędem #31.

Czyli zmiana, która na papierze jest poprawą (500 → 422), zamieniła czytelny
panel błędu w crash całej strony; wcześniejsze 500 niosło `detail` jako tekst.

## 2. Naprawy (#1553)

### Backend: jeden guard zamiast wzorca na parametrze

Najpierw commit RED (`ef0c18a2`) — na prawdziwym PostgreSQL potwierdził **500**
(`asyncpg CharacterNotInRepertoireError: invalid byte sequence for encoding
"UTF8": 0x00`) dla `location`, `q_all`, `q_any` i `q_none`, nie tylko dla `q`
([shard 0](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34991797656)).

`backend/app/core/null_character_guard.py` (czyste ASGI):

| Obejmuje | Nie obejmuje |
|---|---|
| query string (nazwy i wartości, po zdekodowaniu `%00`) | formularzy `multipart/form-data` i `x-www-form-urlencoded` |
| zdekodowaną ścieżkę | nagłówków |
| ciała `application/json` / `+json` oraz bez Content-Type na POST/PUT/PATCH/DELETE | WebSocketów i lifespan (przechodzą bez zmian) |

- Odpowiedź 422 w kształcie błędu walidacji FastAPI, `type: "null_character"`,
  `loc` wskazuje parametr, ścieżkę albo miejsce w ciele. Najwyżej 20 pozycji,
  `input` przycięty do 100 znaków.
- Czyste ciało JSON kosztuje jedno przeszukanie bajtów i trafia do aplikacji
  bajt w bajt (także w kawałkach i przy zerwaniu połączenia). JSON parsuje się
  wyłącznie przy trafieniu; literalny tekst ucieczki przechodzi.
- **Kolejność w `main.py` jest load-bearing:** guard tuż nad
  `UnhandledErrorMiddleware` (ta zostaje najgłębiej), pod korelacją i CORS.
  Odrzucenie bez nagłówków CORS przeglądarka pokazuje jako „Network Error".
  Pilnują tego test kolejności i test na prawdziwej aplikacji.
- `pattern=` przy `q` **zostaje** jako defense-in-depth: opisuje kontrakt
  w OpenAPI, z którego generator Schemathesis bierze dozwolone wartości.
- Sprawdzone przed wdrożeniem: w backendzie nie ma przepływu, który przyjmuje
  NUL i po cichu go czyści (`help_materials` już odrzucał znaki sterujące).

### Frontend: `detail` nigdy jako „na pewno string"

- Nowy czysty moduł `frontend/src/lib/api-error.ts` z `apiErrorMessage(error,
  fallback)` i logiką tłumaczenia `detail`, na której stoi też
  `extractErrorMsg`. Moduł nie zależy od instancji axios, więc jest bezpieczny
  dla stron publicznych (CV, engagement, rejestracja) i **nie ginie pod mockiem
  `@/lib/api`** w testach komponentów — dlatego import idzie z `@/lib/api-error`.
- Ponad 70 miejsc (`data?.detail ??`/`||`, warianty wielolinijkowe oraz odczyty
  dwuetapowe z rzutowaniem `{ detail?: string }`) przepiętych na `apiErrorMessage`
  z dotychczasowym polskim fallbackiem. Formularze rzucające własny `Error`
  (e-mail, szablony) dalej pokazują jego komunikat; eksport kandydatów tłumaczy
  `detail` odtworzony z Bloba; rejestracja nie wywraca już bloku `catch` na
  `.toLowerCase()` tablicy.
- **Test-strażnik** `frontend/src/lib/__tests__/api-error-detail-guard.test.ts`
  czyta źródła ze znormalizowanymi białymi znakami i odrzuca oba wzorce. Na
  `origin/main` sprzed zmiany znajdował **117 trafień w 48 plikach**, po zmianie
  0. Drugi test pilnuje, że wyrażenia dalej łapią znane złe kształty (żeby
  strażnik nie umarł po cichu).

### QA i dokumentacja

- Schemathesis: 17 → **19** przypadków (NUL w `location` i `q_all`).
- `qa/README.md`: opis guardu i zakresu; `CLAUDE.md`: reguły kolejności
  middleware oraz zakaz czytania `detail` jako tekstu.

## 3. Weryfikacja

CI na końcowym commicie gałęzi (`c5a45b43`) — wszystko zielone: 4 shardy
backendu, `coverage combine`, bramka „Backend (pytest)", CI Gate, E2E stack
(Playwright `@stack` 17/17, Schemathesis 19/19, progi k6 bez przekroczeń), build
frontendu, Trivy, gitleaks. Lokalnie (bez Dockera): testy guardu 16/16, ruff
czysty, `tsc --noEmit` bez błędów, ESLint bez nowych ostrzeżeń, `vitest related`
dla wszystkich zmienionych plików 2138/2138.

Produkcja po wdrożeniu `d54beecc` (15.09 19:10 UTC; pomiary 16.09 rano):

| Sprawdzenie | Wynik |
|---|---|
| `/api/health`, `/deep`, `/alembic` | healthy, healthy (0 degraded/unhealthy), bookmark = heads |
| `GET /api/candidates?q=Java%00` | 422, `type: null_character`, `loc: ["query","q"]` |
| `GET /api/candidates?location=Warszawa%00` | **422** (przed zmianą 500) |
| `GET /api/candidates?q=Java` bez tokena | 401 — guard nie miesza się w uwierzytelnianie |
| `version.json` frontendu | `d54beecc`, komunikat o niewidocznym znaku obecny w wdrożonym chunku |

Retest w zalogowanej przeglądarce (16.09):

- fraza z NUL → **422 w 67 ms**, brak ekranu „Coś poszło nie tak", panel
  „Nie udało się wczytać listy — Tekst zawiera niedozwolony, niewidoczny znak
  (NUL) — usuń go albo wpisz tekst ponownie" z przyciskiem „Spróbuj ponownie";
  pasek narzędzi, filtry i pole wyszukiwania pozostają sprawne,
- poprawienie frazy na `Java` → lista wraca **bez przeładowania** (200, 21 722
  wyniki).

## 4. Co zostaje po stronie właściciela

1. **Konto E2E na produkcji** z rolą recruiter i ukończonym onboardingiem, jego
   adres w `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` (produkcja jest SSO-only) oraz
   sekrety `E2E_USER_EMAIL`/`E2E_USER_PASSWORD`. Dopiero po zielonym ręcznym
   biegu `e2e.yml` → `gh variable set E2E_POST_DEPLOY_ENABLED --body true`
   i zamknięcie #1551. Bez tego smoke po deployu nie wykonuje żadnego testu.
2. **Rampa k6 do 100 VU** pozostaje działaniem ręcznym i jest pomiarem na małym
   syntetycznym stacku CI z dwoma współdzielonymi kontami — nie jest dowodem
   pojemności produkcji.

## 5. Znane granice i pułapki na przyszłość

- Guard NIE obejmuje formularzy multipart i urlencoded ani nagłówków. Jeśli
  pojawi się tam tekst trafiający do SQL-a, trzeba go osobno domknąć.
- Dokładając walidację parametru albo zmieniając kształt błędu API, odbierz
  zmianę **klikając w interfejsie**: CI, Schemathesis i testy backendu nie
  renderują UI i nie zobaczą crashu React #31.
- Nowy komunikat błędu w UI buduj przez `apiErrorMessage(error, fallback)`.
  Strażnik odrzuci powrót starego wzorca, ale nie wymyśli za nikogo treści
  komunikatu.
- Obserwacja bez rozstrzygnięcia: wyszukiwanie „Java" trwało 15.09 wieczorem
  ~13 s, a 16.09 rano 1,4 s (pojedyncze pomiary z przeglądarki). Nie badane.
