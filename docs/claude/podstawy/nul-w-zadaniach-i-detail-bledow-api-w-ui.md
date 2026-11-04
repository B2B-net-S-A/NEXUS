# NUL w żądaniach i `detail` błędów API w UI (odbiór #1549, 15.09.2026)

Schemathesis znalazł 500 dla NUL (`%00`) w `q`; odbiór na produkcji pokazał, że
poprawne 422 wywracało listę kandydatów ekranem „Coś poszło nie tak" (React #31),
a testy na PostgreSQL — że `location`, `q_all`, `q_any`, `q_none` miały ten sam
500 (`asyncpg CharacterNotInRepertoireError`).

- **NUL odrzuca JEDNO middleware** (`app/core/null_character_guard.py`): query
  string, zdekodowana ścieżka i ciała JSON (także bez Content-Type) na
  POST/PUT/PATCH/DELETE → 422 `{type: "null_character", loc, msg, input}`.
  Nie obejmuje formularzy multipart/urlencoded, nagłówków ani WebSocketów.
  **Kolejność w `main.py` jest load-bearing:** guard tuż nad
  `UnhandledErrorMiddleware` (ta zostaje najgłębiej), pod korelacją i CORS —
  odrzucenie bez nagłówków CORS przeglądarka pokazuje jako „Network Error".
  Pilnuje `test_nul_guard_sits_inside_cors_and_outside_the_unhandled_error_net`.
  Nie dokładaj `pattern=` NUL do kolejnych parametrów; ten przy `q` zostaje, bo
  opisuje kontrakt w OpenAPI, z którego generator Schemathesis bierze wartości.
- **Ciało żądania sprawdzane ręcznie w handlerze idzie przez `validated_body`**
  (`app/api/body_validation.py`, 02.10.2026). FastAPI zamienia na 422 tylko
  błędy modeli z sygnatury trasy; model budowany w ciele handlera (ciało
  przyjęte jako `dict`, ponowna walidacja po PATCH-u) rzucał
  `pydantic.ValidationError` → 500, a wyjątek z wartościami z żądania szedł do
  logu i Sentry (12 tras, m.in. opis stanowiska ponad 50 000 znaków w „Generuj
  draft”). Odmowa to zdanie po polsku z nazwami pól albo własne zdanie
  wołającego. **Globalnego handlera na `ValidationError` nie dokładaj** — ten
  sam wyjątek rzucają modele budowane z danych wewnętrznych (odpowiedzi, JSON
  z bazy, odczyt AI) i tam ma zostać błędem serwera widocznym w Sentry. Pilnuje
  strażnik AST w `tests/test_body_validation.py` (widzi też `Model(**ciało)`,
  `Annotated[dict, …]`, `request.json()` i lokalny alias ciała).
- **Liczba z żądania większa niż kolumna bazy = 422 w JEDNYM miejscu**
  (`app/core/integer_range.py`, wpięte w `UnhandledErrorMiddleware`,
  02.10.2026). Identyfikatory to int4, a Python przyjmuje dowolny `int`;
  asyncpg nie koduje takiego parametru (`OverflowError("value out of int32
  range")` → `DBAPIError`) i `/api/…/99999999999` albo `{"job_id": 99999999999}`
  kończyło się 500 i zdarzeniem w Sentry. Do tej daty łatano to trasa po trasie
  (cztery różne stałe w `jobs`, `candidates`, `clients`, `contracts`) — nie
  dokładaj kolejnej granicy `le=2_147_483_647` do parametru ani pola.
  Rozpoznawany jest wyłącznie wyjątek kodera asyncpg (int2/int4/int8), po
  łańcuchu przyczyn; przepełnienie zgłoszone przez Postgresa (22003: sekwencja,
  arytmetyka, NUMERIC) zostaje błędem serwera. Odpowiedź: `detail` = „Liczba
  w żądaniu jest poza dopuszczalnym zakresem.”, w logu WARNING, bez Sentry.
- **Publiczny formularz aplikacyjny stawia odmowę PRZY POLU** (18.09.2026):
  `lib/apply-form-errors.ts` mapuje `loc: ["body", <pole>]` na komunikat obok
  inputa, a `status` wraca do `idle` — kandydat poprawia i wysyła ponownie
  z tym samym CV. Wcześniej `body.detail` szło wprost do JSX: dla błędu
  walidacji `Form(...)` to TABLICA obiektów → React #31 → granica błędu zjadała
  całą stronę razem z wypełnionym formularzem i załączonym plikiem, a kandydat
  nie dowiadywał się, że chodziło o e-mail (zod 4 przyjmuje `jan@firma-.pl`,
  `EmailStr` odrzuca — ta rozbieżność ZOSTAJE, dlatego komunikat musi być
  konkretny). Strażnik `api-error-detail-guard.test.ts` nie wymaga już nazwy
  `data` (to ona przepuściła `body.detail`); świadomy wyjątek dla własnego
  endpointu z `detail: string` znaczy się markerem `// api-detail-ok: <powód>`.
- **Harness `/preview/*` ma zasiany KAŻDY stały klucz react-query**
  (`app/preview/__tests__/harness-seeds.test.ts`). Klucz, który się rozjechał
  z komponentem, uruchamia `queryFn` → 401 → przerzut na `/login`, czyli
  harness przestaje pokazywać cokolwiek — tak przestał działać
  `/preview/contracts-consolidation`, gdy `AddProjectDialog` dołożył do klucza
  klientów drugi element. Strażnik pomija `invalidateQueries` (nie pobiera) i
  klucze z parametrami (zależą od stanu), a komentarze wycina przed
  porównaniem — inaczej klucz wymieniony w komentarzu uciszałby go sam.
- **`detail` z FastAPI nigdy nie jest „na pewno stringiem"** — bywa obiektem
  albo tablicą walidacji. Tekst błędu do stanu, toasta lub alertu budujesz
  wyłącznie przez `apiErrorMessage(error, fallback)` z `@/lib/api-error`
  (czysty moduł: bez axios, więc bezpieczny dla stron publicznych i nie ginie
  pod mockiem `@/lib/api` w testach komponentów). `extractErrorMsg` stoi na tej
  samej funkcji. Test `api-error-detail-guard.test.ts` czyta źródła i odrzuca
  `data?.detail ??`/`||` oraz rzutowania `data?: { detail?: string }` — na
  `origin/main` sprzed zmiany znajdował 117 takich miejsc w 48 plikach.
  Odczyty strukturalne (`detail?: unknown` + sprawdzenie typu, np.
  `{missing}`/`{blockers}`) są w porządku.
