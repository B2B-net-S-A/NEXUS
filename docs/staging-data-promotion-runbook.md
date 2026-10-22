# Kopia Hetznera, lokalne zmiany i kontrolowane przeniesienie danych

Kierunek pracy: produkcja → prywatna kopia na laptopie → testy kodu i migracji →
wdrożenie kodu zwykłą ścieżką repozytorium → podgląd wybranych zmian danych →
zatwierdzenie konkretnego digestu przez Artura → jedna transakcja na produkcji.
Nie zastępuj produkcyjnej bazy lokalnym dumpem. W czasie pracy na laptopie
produkcja nadal otrzymuje nowe dane, a sanitizacja celowo zmienia lokalny stan
integracji i tokenów. Kopia służy do testów i wyliczenia wybranej różnicy.

## 1. Przygotuj prywatne miejsce i połączenia

Wszystkie dumpy, manifesty, selection, baseline, package i preview przechowuj poza
repozytorium, w katalogu należącym do użytkownika z uprawnieniami `0700`. Pliki
zawierają dane biznesowe, potencjalnie osobowe; są zapisywane z prawami `0600`.
Nie dodawaj ich do Git, załączników PR, logów Actions ani artefaktów CI.
Przykładowe przygotowanie nowego katalogu:

```sh
umask 077
mkdir -m 700 "$HOME/.codex/private-staging-promotion"
export NEXUS_PROMOTION_PRIVATE_DIR="$HOME/.codex/private-staging-promotion"
```

Używaj pełnych ścieżek bez `..` i dowiązań symbolicznych, także w katalogach
nadrzędnych. Bezpośredni katalog nadrzędny pliku musi należeć do użytkownika
i nie może pozwalać na zapis innym. Na macOS `/tmp` i `/var` bywają dowiązaniami;
wybierz prywatny katalog w swoim katalogu domowym. Artefakty są tworzone wyłącznie
jako nowe pliki; dla kolejnej paczki/preview wybierz nową nazwę lub nowy katalog.

Użyj istniejącej tożsamości SSH i zweryfikowanego wpisu `known_hosts`. Nie wyłączaj
sprawdzania hosta. Konto, host, pełny identyfikator kontenera bazy oraz nazwa bazy
źródłowej muszą być wskazane jednoznacznie. Nie wybieraj automatycznie pierwszego
kontenera z podobną nazwą. Klucz SSH pozostaje w dotychczasowym mechanizmie SSH.

Do lokalnego Postgresa użyj `.pgpass`/`PGPASSFILE` albo bezpiecznie ustawionego
`PGPASSWORD`. DSN-y dla poleceń promotion ustaw poza historią powłoki w zmiennych
`NEXUS_LOCAL_PROMOTION_URL` i `NEXUS_TARGET_PROMOTION_URL`. Nie wpisuj hasła w
argumentach komend i nie używaj `set -x`. W razie tunelu SSH traktuj mapowanie
host:port jako część tożsamości celu — zmiana tunelu wymaga nowego preview.
Przygotuj też jawny `NEXUS_PROMOTION_ACTOR_ID` aktywnego administratora w docelowej
bazie. Preview i apply sprawdzają tę tożsamość; zapis trafia do `activities`
z identyfikatorem administratora i digestami paczki oraz zatwierdzonego preview.

## 2. Skopiuj produkcję przez SSH do nowej lokalnej bazy

Skrypt `scripts/staging/clone_from_hetzner.py` wykonuje zdalnie tylko `pg_dump`
w podanym kontenerze. Nie zatrzymuje produkcji i nie uruchamia aplikacji lokalnie.
Docelowa baza musi być nowa, mieć prefiks `nexus_staging_` i znajdować się pod
literalnym adresem `127.0.0.1` lub `::1`. Istniejąca baza pozostaje nietknięta.

Najpierw sprawdź parametry; użyte tu zmienne nie zawierają haseł:

```sh
python3 scripts/staging/clone_from_hetzner.py \
  --ssh-host "$NEXUS_SSH_HOST" \
  --ssh-identity "$NEXUS_SSH_IDENTITY_PATH" \
  --source-container "$NEXUS_POSTGRES_CONTAINER_ID" \
  --source-db "$NEXUS_SOURCE_DATABASE" \
  --source-user "$NEXUS_SOURCE_DATABASE_USER" \
  --target-host 127.0.0.1 --target-port 5433 --target-user nexus \
  --target-db nexus_staging_work \
  --output-root "$HOME/.local/share/nexus-staging-baselines" \
  --dry-run
```

Po poprawnym preflight wykonaj to samo polecenie bez `--dry-run`. Tryb `--dump-only`
zapisuje prywatny dump i manifest, ale nie odtwarza bazy; nie oznacza gotowego stagingu.
Odtworzenie i `scripts/staging/sanitize.sql` przebiegają w jednej transakcji.
Nie uruchamiaj aplikacji, jeżeli przywrócenie albo sanitizacja nie zakończyły się sukcesem.

Po wykonanym `--dump-only` wznów z zachowanego manifestu bez ponownego SSH/pobierania:

```sh
python3 scripts/staging/clone_from_hetzner.py \
  --restore-manifest "$NEXUS_CLONE_MANIFEST_PATH" \
  --target-host 127.0.0.1 --target-port 5433 --target-user nexus \
  --target-db nexus_staging_work
```

Skrypt sprawdza manifest, prywatne ścieżki i hash dumpu, odtwarza wyłącznie nową
bazę oraz zapisuje oddzielny restore receipt. Dopiero po receipt ze statusem
`restored_sanitized` operator ustawia w lokalnym `.env.staging.local`
`STAGING_DATABASE_NAME=nexus_staging_work` i uruchamia backend z `NEXUS_ENV=staging`.
Sam skrypt nie przełącza aplikacji i nie edytuje `.env`. Bootstrap Postgresa
pozostaje na bazie `nexus`; wybrana kopia jest nową bazą obok niej w tym samym
lokalnym serwerze. Obecna osobna ścieżka odtwarzania offsite nadal zakłada bazę
`nexus` — przy niej `STAGING_DATABASE_NAME` musi wynosić `nexus`.

Lokalny Docker jest dozwolony od 22.10.2026. Nieudany przebieg zostawia pustą
bazę docelową (`CREATE DATABASE` jest poza transakcją) — kolejny przebieg kieruj
do nowej nazwy zamiast kasować tamtą. Host-native restore wymaga dostępnego
lokalnego Postgresa.

Jeżeli `psql`/`pg_restore` nie są zainstalowane na hoście, użyj
klientów PostgreSQL 16 we wskazanym lokalnym kontenerze stagingu:

```sh
python3 scripts/staging/clone_from_hetzner.py \
  --restore-manifest "$NEXUS_CLONE_MANIFEST_PATH" \
  --local-postgres-container "$NEXUS_LOCAL_POSTGRES_CONTAINER_ID" \
  --target-host 127.0.0.1 --target-port 5433 --target-user nexus \
  --target-db nexus_staging_work
```

`NEXUS_LOCAL_POSTGRES_CONTAINER_ID` to jawnie wybrany pełny identyfikator
64-znakowy. Skrypt sprawdza działający kontener `nexus-staging/postgres`,
mapowanie portu tylko na loopback, lokalny Unix socket Dockera i wersję klientów.
Nie przełącza się awaryjnie na zdalny daemon ani inny kontener. Ten wariant
również tworzy nową bazę; nie wykonuje `DROP` ani odtworzenia na produkcji.

Zachowaj oryginalny `baseline.dump` i `manifest.json` bez modyfikacji. To punkt
odtworzenia i dowód pochodzenia kopii, **nie** manifest wybranych danych do promocji.
Dump nadal zawiera oryginalne dane produkcyjne; sanitizacja dotyczy odtworzonej bazy.
Nie wysyłaj dumpu z laptopa do produkcyjnego `pg_restore`.

## 3. Utrzymaj staging i wybierz zakres przed edycją danych

Uruchamiaj aplikację wyłącznie z `NEXUS_ENV=staging`, własnymi sekretami,
zaporą wyjścia i wyłączonymi zadaniami integracyjnymi, zgodnie z
`docs/claude/podstawy/staging-na-laptopie.md`. Sanitizacja nie anonimizuje osób.
Nie kopiuj wstecz tokenów, sesji, subskrypcji, kursorów ani unieważnionych kluczy.

W `selection.json`, w prywatnym katalogu, wskaż jawnie tabelę, klucz główny,
dozwolone pola i operację. Przykład zawiera wyłącznie syntetyczny identyfikator:

```json
{
  "version": 1,
  "records": [
    {"recipe": "client-descriptions", "table": "clients", "pk": {"id": 123456}, "fields": ["industry"], "operation": "update"}
  ]
}
```

Zakres obejmuje moduły biznesowe przez recenzowane, wersjonowane recipes
w `backend/app/services/staging_promotion_recipes.py` albo osobne migracje danych
w repozytorium. Samo istnienie tabeli nie daje uprawnień do jej kopiowania.
Pierwszy wbudowany handler `client-descriptions` dopuszcza aktualizacje
`industry`, `website`, `address`, `notes` istniejących, widocznych i
nieusuniętych/niescalonych klientów. Inne moduły, pola i inserty wymagają
osobnego jawnie zarejestrowanego handlera domenowego z testami integralności.
Nie jest to gotowa obsługa każdej tabeli aplikacji. Pole spoza recipe oznacza
odmowę; nie rozszerzaj jej tylko po to, żeby ominąć odmowę. Usuń z zakresu dane
testowe, skutki sanitizacji i przypadkowe zmiany. Usuwanie danych produkcyjnych
oraz kopiowanie całej tabeli nie są częścią tego mechanizmu.

Po odtworzeniu zachowaj baseline dump, następnie sprawdź lokalnie kod i wykonaj
migracje na kopii. Wykonaj snapshot wybranych pól **po** migracjach, a **przed**
lokalną zmianą wybranych wartości:

```sh
cd backend
python scripts/staging_data_promotion.py snapshot \
  --selection "$NEXUS_PROMOTION_PRIVATE_DIR/selection.json" \
  --source-url-env NEXUS_LOCAL_PROMOTION_URL \
  --out "$NEXUS_PROMOTION_PRIVATE_DIR/selected-baseline.json"
```

Snapshot dotyczy lokalnej bazy `nexus_staging_*`, nie produkcji. Jeśli dopiero po
edycji potrzebujesz dodatkowego pola, nie dorabiaj jego historii ręcznie: pobierz
jego stan początkowy z zachowanej nietkniętej kopii i przygotuj nowy poprawny zakres.
Dla jawnie dopuszczonego insertu snapshot musi potwierdzić brak docelowego klucza
w lokalnej baseline. Recipe musi wymagać odpowiednich pól i dostarczać własny
handler tworzący rekord oraz relacje domenowe w tej samej transakcji. Paczka
insertu ma `expected_before: null`; nie zamieniaj update'u na insert ręcznie.

## 4. Zmień i sprawdź lokalnie kod, migracje i dane

Pracuj w izolowanym worktree. Testuj kod i migracje na kopii stagingowej. Nie
traktuj uruchomienia aplikacji jako sprawdzenia zewnętrznych integracji:
staging celowo ich nie wykonuje. Oprócz migracji sprawdź funkcje, których dotyczy
zmiana, i brak niezamierzonych zmian w wybranych danych.

Gdy migracja zmienia strukturę promowanych pól, punktem odniesienia dla danych
musi być nietknięta kopia po zgodnej migracji, przed edycją wartości. Nie mieszaj
zmiany schematu z ręcznie poprawianym manifestem. Na produkcję wdrażaj kod i
migracje przez istniejący, zielony proces repozytorium; ten runbook nie zmienia
workflow deployu ani zasad autoryzacji. Przed preview danych potwierdź zgodność
wdrożonego SHA i schematu z wersją używaną do przygotowania paczki.

Wylicz paczkę z wybranej baseline i lokalnego stanu po edycjach:

```sh
python scripts/staging_data_promotion.py package \
  --baseline "$NEXUS_PROMOTION_PRIVATE_DIR/selected-baseline.json" \
  --source-url-env NEXUS_LOCAL_PROMOTION_URL \
  --out "$NEXUS_PROMOTION_PRIVATE_DIR/package.json"
```

Paczka zawiera oczekiwany stan początkowy i docelowy tylko wybranych pól.
Nie edytuj ręcznie paczki ani jej digestu. Pola i nowe rekordy produkcji spoza
paczki mają pozostać nietknięte.

## 5. Preview na dokładnie wskazanym celu

```sh
python scripts/staging_data_promotion.py preview \
  --package "$NEXUS_PROMOTION_PRIVATE_DIR/package.json" \
  --target-url-env NEXUS_TARGET_PROMOTION_URL \
  --actor-id "$NEXUS_PROMOTION_ACTOR_ID" \
  --out "$NEXUS_PROMOTION_PRIVATE_DIR/preview.json"
```

Snapshot, package i preview wykonują odczyty w transakcjach `READ ONLY`,
`REPEATABLE READ`. Preview nie zapisuje zmian biznesowych. Sprawdź prywatnie wszystkie operacje
i wartości przed/po w paczce oraz konflikty, docelową bazę i schemat. Sam plik
preview przechowuje hashe projekcji i statusy, bez kolejnej kopii wartości pól.
Wyniku z konfliktem nie
zatwierdzaj. Zbadaj nowszy stan produkcji i przygotuj nową paczkę lub usuń sporną
zmianę z nowego zakresu. Nie zastępuj `expected_before` wartością z produkcji
tylko po to, żeby wymusić nadpisanie.

Preview jest związane z paczką, stanem wybranych danych, tożsamością celu oraz
ograniczonym czasem ważności. Po zmianie target URL, mapowania tunelu, bazy,
schematu, paczki albo wygaśnięciu preview wykonaj nowy podgląd i zbierz nowe
zatwierdzenie. Nie przenoś zgody między celami.

## 6. Jawna zgoda na digest i jedna transakcja

Artur zatwierdza konkretny digest aktualnego preview, zakres i docelowe środowisko.
Ogólna zgoda na tworzenie stagingu albo wcześniejszy deploy nie zatwierdza
produkcyjnego zapisu danych. Agent nie pobiera sam digestu z pliku w celu
automatycznego spełnienia warunku zgody.

Po otrzymaniu zgody wykonaj:

```sh
python scripts/staging_data_promotion.py apply \
  --package "$NEXUS_PROMOTION_PRIVATE_DIR/package.json" \
  --preview "$NEXUS_PROMOTION_PRIVATE_DIR/preview.json" \
  --target-url-env NEXUS_TARGET_PROMOTION_URL \
  --actor-id "$NEXUS_PROMOTION_ACTOR_ID" \
  --approve-digest "$NEXUS_HUMAN_APPROVED_PREVIEW_DIGEST"
```

`apply` ponownie sprawdza tożsamość celu, digest i stan danych pod blokadami.
Wszystkie operacje paczki wykonuje w jednej transakcji. Konflikt współbieżnej
edycji, kolizja unikalności albo inny błąd zapisu wycofuje całą transakcję.
Nie ponawiaj wymuszająco: po błędzie ustal wynik, odczytaj aktualny stan i wróć
do preview. Ponowienie identycznej operacji już będącej w stanie docelowym jest
bez zmiany i bez dodatkowego zdublowanego wpisu audytu. Stan docelowy mógł jednak
istnieć przed promocją; no-op aktualizacji sam nie dowodzi, kto i kiedy go utworzył.
Ponowienie insertu wymaga dodatkowo pasującego wpisu audytu tej paczki, recipe
i klucza głównego. Obcy rekord z takim samym PK, nawet z identycznymi wartościami,
nie jest automatycznie uznawany za udane wcześniejsze wykonanie.

Po sukcesie sprawdź wskazane rekordy i działający widok w aplikacji produkcyjnej,
bez publikowania danych osobowych. Zachowaj prywatnie paczkę, preview,
zatwierdzony digest i wynik. Do raportu/PR trafiają tylko zakres techniczny,
liczby operacji, digest i wynik weryfikacji, bez wartości rekordów i sekretów.

## Kolejne moduły biznesowe: recipe albo migracja danych w zwykłym PR

1. Określ reguły modułu: własność i zakres rekordów, lifecycle, wymagane pola,
   klucze obce, unikalność, wartości pochodne, relacje, indeksy i audyt.
   Zidentyfikuj efekty uboczne — recipe nie wysyła maili ani wywołań zewnętrznych
   jako przypadkowego skutku kopiowania.
2. Dodaj w repozytorium jawny handler `Recipe` z identyfikatorem, wersją,
   `review_reference`, dozwolonymi operacjami/polami i pełnym kontraktem. Handler
   insertu sam tworzy rekord oraz potrzebne relacje w transakcji dostarczonej
   przez silnik. Odpowiada też za przydzielanie/mapowanie ID i ewentualne sekwencje.
   Nie wykonuje własnego `commit()` ani `rollback()`.
3. Dodaj recipe do statycznego `DEFAULT_REGISTRY`, testy syntetyczne unit oraz
   rzeczywiste testy PostgreSQL. Sprawdź walidację domenową, współbieżne kolizje
   PK/unique, FK, rollback relacji/audytu, zachowanie nowych rekordów i retry.
4. Przeprowadź standardowy PR, CI i deploy kodu/migracji. Dane produkcyjne nadal
   pozostają w prywatnych artefaktach. Dopiero potem przygotuj nową selection,
   baseline, package, preview i uzyskaj zgodę na konkretny digest oraz cel.

Szablon konstrukcji recipe dla prostego, hipotetycznego katalogu; to kod do
dostosowania i review w repozytorium, nie plik do wczytania przez CLI:

```python
from app.services.staging_promotion_recipes import FieldPolicy, Recipe, RecipeError


async def validate_catalog(conn, operation):
    values = operation["decoded_values"]
    if "title" in values and not values["title"].strip():
        raise RecipeError("catalog_title_required")


async def insert_catalog(conn, table, operation):
    values = operation["decoded_values"]
    await conn.execute(table.insert().values(
        id=operation["pk"]["id"],
        title=values["title"],
        enabled=True,
    ))
    # Relacje i wymagane dane pochodne dopisz tu w tej samej transakcji.


CATALOG_RECIPE = Recipe(
    recipe_id="business-catalog",
    version=1,
    table="business_catalog",
    entity_type="catalog_item",
    fields={"title": FieldPolicy(200, nullable=False, required_for_insert=True)},
    operations=frozenset({"update", "insert"}),
    lifecycle={"enabled": True},
    review_reference="repo:reviewed-business-catalog-promotion-v1",
    preconditions=("selected record belongs to the reviewed catalog scope",),
    constraints=("database uniqueness and foreign keys remain enforced",),
    postapply_requirements=("domain invariants and activity audit in one transaction",),
    validate_domain=validate_catalog,
    insert_handler=insert_catalog,
)
```

Dostosuj hooki do rzeczywistego modelu. Szablon nie
zastępuje walidacji domenowej ani relacji wymaganych przez konkretny moduł.
Hooki i handler insertu korzystają z `operation["decoded_values"]` — to
sprawdzone wartości natywne Pythona. `desired_after` jest formatem transportowym
i dla typów złożonych zawiera znaczniki, których nie należy zapisywać jako danych.
W polu JSON wartość całego dokumentu `null` jest przekazywana jako
`recipes.JSON_NULL`, SQL `NULL` jako `None`; `null` zagnieżdżony w obiekcie/liście
JSON pozostaje zwykłym `None`.
Recipe jawnie deklaruje typ każdego pola: `string`, `boolean`, `integer`,
`decimal`, `date`, `datetime`, `uuid`, `json`, oraz dopuszczalność `null`.
Kwoty używają skończonego `Decimal`, bez przejścia przez binarny `float`.
Daty/czas/UUID/Decimal mają typowany format w JSON artefaktu; `datetime` wymaga
jawnej strefy UTC. JSON biznesowy jest osobno kodowany
jako kanoniczny tekst, aby zachować dokładne liczby i odróżnić własne klucze
obiektu od znaczników formatu artefaktu. Nie edytuj znaczników ręcznie.
SQL `NULL` i wartość JSON `null` są odrębnymi stanami także przy zapisie JSONB;
review musi zachować zamierzoną różnicę między brakiem wartości a JSON-owym null.
Wspierany klucz główny to dodatni całkowity `id`; **klucze złożone nie są
obsługiwane**. Inne klucze i szersze wymagania transakcyjne wymagają jawnej
implementacji i testów w kodzie albo osobnej kontrolowanej migracji danych.
Nie zamieniaj liczb/obiektów na tekst tylko w celu obejścia polityki pola.
Binarne pliki CV, uploady, pliki dokumentów i snapshoty wektorów pozostają poza
paczkami danych; ich odtworzenie i ewentualne przeniesienie wymaga osobnego,
kontrolowanego procesu właściwego dla magazynu plików.

Recipe jest związana w artefaktach przez identyfikator, wersję i digest polityki
obejmujący kod handlerów. Zmiana recipe/kodu wymaga nowych artefaktów i nowej zgody.
CLI nie przyjmuje ścieżki do modułu Python, pliku recipe, `--allow-table`, SQL-a
ani mechanizmu automatycznego odblokowania tabel. Dane kont, role/uprawnienia,
sekrety, sesje, tokeny, stan integracji i kolejki operacyjne nie są promowane
przez ten rejestr. Dla danych biznesowych spoza gotowych recipes wybierz
recenzowany handler lub migrację danych ze sprawdzeniem oczekiwanego stanu,
podglądem zakresu i odrębną zgodą na produkcyjny zapis.

## Sprawdzenie mechanizmu bez danych produkcyjnych

Workflow `.github/workflows/staging-data-promotion-checks.yml` używa wyłącznie
syntetycznych rekordów i Postgresa 16. Testy tworzą izolowane schematy w lokalnej
bazie testowej. Sprawdzają zachowanie nowszych danych produkcji, konflikt dwóch
połączeń, rollback całej paczki po błędzie constraintu/unikalności, idempotencję
oraz odmowę dla błędnego digestu i zmienionego celu. Wbudowany handler klienta
odrzuca inserty. Osobna syntetyczna recipe drugiego modułu potwierdza jawnie
dopuszczony insert: brak rekordu w baseline, zachowanie nowych danych produkcji,
kolizję PK i unique po preview, błąd FK, walidację domenową, rollback relacji
i audytu oraz ponowienie oparte na potwierdzeniu audytowym.
Osobna syntetyczna recipe finansowa sprawdza dokładny roundtrip `Decimal`,
bool, integer, JSON z precyzyjnymi liczbami i obiektem przypominającym znacznik
formatu, daty/czasu i UUID, a także konflikt kwoty po preview.
Sprawdza też oba kierunki SQL `NULL` ↔ JSON `null` przez rzeczywiste `IS NULL`,
zamiast porównywania wyłącznie zdekodowanego `None`. Zmiana schematu
między preview a apply wymaga nowego podglądu i zatwierdzenia.

Ręcznie, po ustawieniu testowego DSN w `STAGING_PROMOTION_TEST_DATABASE_URL`:

```sh
cd backend
STAGING_PROMOTION_DB_ACCEPTANCE=1 python -m pytest --noconftest \
  -o asyncio_mode=auto tests/test_staging_data_promotion_db.py -q
```

Adres musi być loopback, a nazwa bazy mieć postać `nexus_staging_*_test`.
Testy nie używają backupów, sekretów ani usług produkcji. Istniejące CI
uruchamia pozostałe testy backendu; te testy DB są jawnie włączane w dedykowanym
jobie, aby nie wykonywać tej samej integracji ponownie w każdym sicie/shardzie.
Zielone testy syntetyczne potwierdzają mechanizm; nie dowodzą wykonania clone,
wdrożenia ani produkcyjnej promocji danych.
