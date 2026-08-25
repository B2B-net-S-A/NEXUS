# Aktywacja umów bezterminowych, przedłużenia zamówień i polityki PDF — raport

Siedem zgłoszeń w jednym PR. Trzy miały diagnozę trafną co do objawu, ale nie
co do miejsca — poniżej opisane jest, co naprawdę było zepsute.

Data: 2026-08-25. Gałąź: `claude/contract-409-active-status-b37667`.

---

## T1 — 409 przy zapisie kontraktu ze statusem „Aktywny”

**Objaw:** każda próba zapisania kontraktu jako „Aktywny” kończyła się
`Request failed with status code 409`. Zapis działał wyłącznie dla „Draft”.

**Przyczyna — trzy niezależne defekty na jednej ścieżce:**

1. **`end_date` w `ACTIVATION_REQUIRED_FIELDS`.** Umowa bezterminowa
   (`end_date IS NULL`) jest w body-leasingu normalnym stanem docelowym:
   rejestr renderuje ją wprost jako „bezterminowo”,
   `_status_after_end_date_change` traktuje brak daty jako „jeszcze się nie
   skończyła” (i leczy z niej `ended`/`ending` na `active`), a
   `ending_soon_clause` po prostu jej nie łapie. Wymaganie daty W BRAMCE stało
   w sprzeczności z całą resztą modelu i dawało **stan bez wyjścia** — taka
   umowa nie wychodziła z Draftu żadną ścieżką.

   To nie jest nowe odkrycie: repozytorium wiedziało o tym od PR #1260
   („kontrakt BEZTERMINOWY nie wychodzi z Draftu żadną istniejącą ścieżką… to
   nie rekord do naprawienia, tylko stan, którego będzie przybywać”) i obeszło
   **skutek** w UI, przestawiając bramkę przycisku „Zakończ”. Ten PR usuwa
   przyczynę. Lustrzana decyzja po stronie zamówień zapadła wcześniej
   (`_order_has_required_activation_data`, PR #1258).

2. **Kolejność w `PATCH /api/contracts/{id}`.** Przejście stanu wykonywało się
   PRZED wyprowadzeniem stawek z harmonogramów. Formularz rejestru wysyła
   stawkę kandydata ALBO jako `rate_candidate`, ALBO — gdy jest progresywna —
   wyłącznie jako `candidate_rate_schedule`. Bramka oglądała więc jeszcze pustą
   kolumnę cache’u i odmawiała z `missing: rate_candidate`, mimo że stawka
   przyszła w tym samym żądaniu — a linijkę niżej ta sama kolumna była już
   wypełniana. `POST` miał tę kolejność poprawnie i opisaną w komentarzu;
   `PATCH` ją odwracał.

3. **Surowy kod HTTP w interfejsie.** `/contracts/[id]` miało
   `onError: err.message`, co dla `AxiosError` daje dosłownie „Request failed
   with status code 409”. Odmowa NIESIE powód
   (`{message: "Missing required fields", missing: [...]}`), a `extractErrorMsg`
   umie go przetłumaczyć na polskie etykiety pól — tylko nie było wołane.

**Zmiany:** `end_date` zdjęte z bramki (+ rozpoznawanie stawki z harmonogramu,
`_has_activation_value`); harmonogramy przed przejściem stanu w `PATCH`;
`extractErrorMsg` na zapisie kontraktu; lustra bramki po stronie FE
(`DraftCompletionModal`, walidacja „Nowy kontrakt”) rozluźnione.

**Dodatkowo (znalezione przy okazji):** status „Kończący się” dla umowy
bezterminowej to stan, który sam się kasuje — `_status_after_end_date_change`
i nocny cron cofają go na `active`, więc zapis zwracał 200 i nie robił nic.
Teraz odmawia po polsku (`ending_requires_end_date`), i to **po** pełnej
liście braków, żeby ładunek bez daty i bez stawek nie odsyłał operatora po
kolejną odmowę.

---

## T2 — długie nazwy klientów rozwalają układ tabel

**Objaw:** „CARDIF - ASSURANCES RISQUES DIVERS SPÓŁKA AKCYJNA ODDZIAŁ W POLSCE”
rozciągał kolumnę „Klient · Rekrutacja” na pół strony.

Wspólny komponent `ds/TruncatedText` (przycięcie + limit szerokości + pełna
treść w `title`), zastosowany w obu rejestrach modułu Kontrakty
(`ContractsListV2`, `ContractorsListV2`) — nazwa klienta, tytuł rekrutacji
i e-mail kandydata. Reguła mieszka w jednym miejscu zamiast w kilkunastu
kopiach `truncate max-w-[...]`; `max-w` jest domyślne i nadpisywalne własną
klasą (tailwind-merge deduplikuje).

Dlaczego przycięcie, a nie zawijanie: kolumny sąsiadują z datami, stawkami
i statusami — zawijanie rozciąga wiersz w pionie i rozjeżdża wyrównanie.

`ConsultantsTable` (profil klienta) sprawdzone — ma już `min-w-0` + `truncate`
i nie renderuje nazwy klienta; bez zmian.

---

## T3 — audyt „BNP Paribas Cardif” ↔ „CARDIF - ASSURANCES…”

Dwa niezależne zgłoszenia tej samej pomyłki (Marek Cyran, Maciej Rogala) to
sygnał systemowy: w liście wyboru klienta stoją obok siebie dwa rekordy
o mylnie podobnych nazwach, a wybór sąsiada nie daje ŻADNEGO widocznego
sygnału — dokument generuje się poprawnie, kontrakt zapisuje się poprawnie,
błąd wychodzi przy rozliczeniu.

**Dostarczone:** `GET /api/admin/client-mixups?q=cardif` (admin, read-only) —
rodziny klientów o wspólnym rdzeniu nazwy wraz z ich kontraktami i umowami B2B,
z dowodami przy każdym wierszu: NIP obu stron, klient REKRUTACJI, z której
powstało powiązanie, i flaga `job_client_mismatch`.

Trzy decyzje warte zapamiętania:

* **Rodzinę wyznacza wspólny TOKEN nazwy, nie podciąg.** Podciąg „BNP” łączy
  „BNP Paribas Cardif” z „BNP Paribas Bank Polska” — odrębnym, prawdziwym
  klientem. Raport mieszający poprawne przypisania z podejrzanymi przestaje
  być listą do weryfikacji.
* **Formy prawne są odsiewane** („SPÓŁKA AKCYJNA”, „ODDZIAŁ W POLSCE”) —
  inaczej połowa bazy byłaby jedną rodziną.
* **Zero mutacji.** Ticket wprost żąda listy DO WERYFIKACJI przed korektą,
  a automat trafiłby też w przypadki, w których podobna nazwa to naprawdę
  inny klient (grupa kapitałowa bywa naszym klientem kilka razy).

**Złapane przy okazji:** `ł` nie rozkłada się pod NFKD, więc naiwne składanie
diakrytyków tnie „SPÓŁKA” na „spo” + „ka” — rdzeniem nazwy zostawał przypadkowy
trzyliterowy fragment łączący firmy niemające ze sobą nic wspólnego.
Transliteracja jak w `nordea_order_import` / `md_import_parser`.

### NIEWYKONANE — korekty danych produkcyjnych

Trzy punkty tych ticketów to edycje danych na produkcji i **nie zostały
wykonane** — ta sesja nie ma dostępu do prodowej bazy (SSH martwe) ani do
zalogowanej sesji API:

1. Marek Cyran — usunięcie projektu/zamówienia „BNP Paribas Cardif”
   (zostaje kontrakt #602).
2. Maciej Rogala — umowa 1474/2026: klient → CARDIF.
3. Maciej Rogala — kontrakt #521: klient → CARDIF.

Do punktu 3 dochodzi **luka produktowa**: `ContractUpdate` nie przyjmuje
`client_id`, więc kontraktu nie da się przepiąć na innego klienta z interfejsu
w ogóle. Każde takie zgłoszenie wymaga dziś inżyniera. Świadomie nie dodałem
tego pola w tym PR — przepięcie kontraktu dotyka client-scope’u, zamówień,
grup i MRR, więc to osobna decyzja projektowa, nie poprawka przy okazji.

Kolejność, którą proponuję: najpierw `GET /api/admin/client-mixups?q=cardif`
na prodzie → weryfikacja listy przez zespół produktowy → dopiero potem korekty.

---

## T4 — Credit Agricole: stawka czytana z pola liczby MD

**Objaw:** do stawki trafiała wartość z „Szacowana ilość MD” zamiast
z „Wynagrodzenie za 1MD (8h) (PLN netto)”.

Prompt już zawierał instrukcję „do not confuse it with the rate itself” i nie
wystarczyła — model wybiera interpretację, a nie stosuje regułę. Dlatego jak
u Nordei i Banku Pocztowego: **polityka deterministyczna po odpowiedzi LLM**,
oparta na etykietach. Obie wartości wyprowadzane niezależnie, każda ze swojej
etykiety, więc zamiana miejscami jest mechanicznie niemożliwa.

Cztery zabezpieczenia, bo błąd jest cichy (liczba jest arytmetycznie poprawna
i przechodzi każdą walidację zakresu — wychodzi dopiero na fakturze):

* wypełniacz między etykietą a wartością zjada nawiasy w całości, więc cyfry
  z samej etykiety („1MD”, „8h”) nie wygrywają z wartością;
* **układ nagłówka tabeli** (obie etykiety w jednym wierszu, wartości
  w kolumnach niżej) → **odmowa, nie zgadywanie**: bez wyrównania „pierwsza
  liczba za etykietą” trafia w liczbę porządkową;
* ta sama liczba pod obiema etykietami → stawka do ręcznego uzupełnienia;
* widełki 200–5000 zł/MD jako ostrzeżenie.

Brak etykiety stawki **czyści** wartość zaproponowaną przez model — to jest
dokładnie ten kanał, którym wchodziła liczba MD podana jako kwota.

Aktywacja: `CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS` w Coolify (CSV
`client_id`, fail-closed jak sąsiednie bramki).

**Lista dotkniętych zamówień do korekty — NIEDOSTARCZONA** (brak dostępu do
prodowej bazy). Zapytanie do wykonania po stronie produ: zamówienia Credit
Agricole, w których `rate_client` jest podejrzanie niska (rzędu liczby MD,
nie kwoty) — praktycznie `rate_client < 200` przy `rate_unit = 'day'`.

---

## T5 — Erste Bank Polska: stawka w PDF jest brutto

Nowa polityka `apply_erste_order_policy`: `rate_client = brutto / 1,23`,
zaokrąglone do 2 miejsc, oryginał brutto zachowany w `rate_client_gross`
i pokazywany obok pola (jak `rate_client_md` u Banku Pocztowego).

* **`ROUND_HALF_UP`, nie `ROUND_CEILING`** jak przy MD ÷ 8 u BP: tamto
  zaokrąglenie w górę było świadomą decyzją handlową przy ROZBIJANIU stawki
  na godziny, a tu odwracamy dokładne działanie arytmetyczne.
* **`total_value` nietknięte** — ticket mówi o stawce; wartość całkowita bywa
  w tych dokumentach podana z własną adnotacją, więc ciche dzielenie „przy
  okazji” byłoby zgadywaniem na kwocie, o którą nikt nie prosił.
* **Erste jako OSTATNIA polityka w łańcuchu** — przelicza kwotę ustaloną przez
  polityki wyżej. Odwrotna kolejność dzieliłaby wartość, którą któraś z nich
  zaraz potem by nadpisała, czyli po cichu nie przeliczyłaby nic.

Aktywacja: `ERSTE_GROSS_RATE_CLIENT_IDS` w Coolify. Bramka po ID, nie po
nazwie — Traffit nadpisuje `Client.name`, a rodzina rekordów tego samego banku
bywa większa niż jeden wiersz.

**Lista istniejących zamówień do korekty — NIEDOSTARCZONA** (brak dostępu do
prodowej bazy).

---

## T6 — przelicznik jednostki stawki (godzinowa ↔ MD 8h)

Przełącznik przy stawce kosztowej i przychodowej w `ConsultantLineModal`,
**niezależny dla każdego pola** (kosztowa przychodzi zwykle z kontraktu —
godzinowa, przychodowa z zamówienia klienta — MD). Przeliczenie odpala się
przy zmianie jednostki, nie przy zapisie: operator ma zobaczyć nową liczbę
od razu i móc ją poprawić.

Reguła mieszka w `lib/rate-unit.ts`, nie w komponencie — **zapis zawsze idzie
w zł/MD** (`toMdRate`), bo taka jest jednostka rozliczeniowa modułu. Gdyby
przeliczenie zostało w komponencie, przełącznik ustawiony na „godzinowa”
zapisywałby stawkę godzinową do kolumny opisanej jako MD: błąd cichy
i ośmiokrotny.

Trzy miejsca, które musiały pójść w lockstep, bo każde karmi pole wartością
o znanej jednostce: podpowiedź stawki z kontraktu, odczyt z PDF i podgląd
budżetu MD (dzielnikiem MUSI być stawka w zł/MD, inaczej podgląd rozjeżdża się
ośmiokrotnie z tym, co zaraz się zapisze).

Zaokrąglenie do 2 miejsc jest odporne na błąd binarny (`1.005 → 1.01`) —
przy dwóch kwotach pokazywanych obok siebie operator natychmiast zauważy,
że ×8 i ÷8 nie wracają do tej samej liczby.

---

## T7 — przedłużenie z zakładki „Zakończone” nie wraca do „Aktywne”

**Diagnoza z ticketu** („mechanizm zmiany zakładki nie jest wywoływany, gdy
zamówienie źródłowe jest w zakładce Zakończone”) była trafna co do skutku,
ale nie co do miejsca: **nie istniał ŻADEN mechanizm**. `POST
/clients/{id}/orders` tworzył zamówienie i nie dotykał statusu kontraktu —
z żadnej zakładki. Widoczne było to tylko z „Zakończonych”, bo pigułki czytają
`contract_status`, a kontraktor aktywny i tak już tam był.

To trzecia ścieżka przedłużania współpracy. Aneks (`/amendments`)
i `/bulk-extend` przesuwają `end_date` i wołają `reopen_contract`; dodanie
zamówienia nie robiło ani jednego, ani drugiego.

**Zmiany:** `contract_lifecycle.sync_contract_to_live_order` (jedna reguła,
jedno miejsce) + adapter w `client_orders` synchronizujący „Koniec zamówienia
u klienta”. Decyduje WYŁĄCZNIE porównanie dat z dniem dzisiejszym, nie
zakładka, z której operator kliknął.

* Przedłużenie zaczynające się w przyszłości **nie zmienia niczego** (ląduje
  w „Przyszłym zamówieniu”) — reguła 2 z ticketu.
* Poprzednie zamówienie trafia do „Historii zamówień” **samo**: `splitOrders`
  jest date-driven i już to robiło; brakowało wyłącznie statusu kontraktu.
* Zamówienia `draft`/`cancelled` są pomijane — szkic nie jest zobowiązaniem,
  anulowane nie obowiązuje.
* **Data końca kontraktu rośnie razem ze statusem.** Bez tego nocny
  `_promote_statuses` zdemotowałby wskrzeszony kontrakt z powrotem do `ended`
  jeszcze tej nocy i poprawka kasowałaby samą siebie.

**Historia:** migracja `0243_revive_contracts_with_live_orders` leczy wiersze,
które już powstały (w tym przykład z ticketu — Mariusz Matyszczuk / Erste).
Reguła OGÓLNA, zero identyfikatorów w SQL-u: naprawiamy klasę wierszy powstałą
z jednego defektu kodu, a nie trzy znane pomyłki operatora — więc „zero
dopasowań” jest tu poprawnym wynikiem (świeża baza, CI), nie błędem.

---

## Recenzja i przebieg adwersarialny — trzy poprawki po fakcie

Warto to zapisać, bo obie znalezione rzeczy mają **ten sam kształt**: reguła
napisana dwa razy i za drugim razem inaczej. Migracja `0243` była w obu
przypadkach tą poprawną kopią.

**Z recenzji:** `client_order_end_date` nie było zerowane, gdy bezterminowe
zamówienie czyniło bezterminowym kontrakt — guard `contract.end_date is not
None` pomijał całą gałąź. Migracja robiła to poprawnie (`has_open_ended →
NULL`), więc ścieżka runtime rozjeżdżała się z własną migracją.

Uwaga do uzasadnienia, którą trzeba znać: kolumnę skanuje
`contract_alerts._client_orders_ending`, **nie** `dl_portal_expiry_scanner`,
a jego predykat wymaga `client_order_end_date >= today` — więc PRZESZŁA data
z okna wypada i **żadnego fałszywego alertu nie wygeneruje**. To czyni rozjazd
gorszym, nie lepszym: nic go nie zgłosi. Realna szkoda jest w UI — profil
kontraktu renderuje tę wartość osobnym wierszem, więc obok „Okres: … –
bezterminowo" stałaby data z przeszłości.

**Z przebiegu adwersarialnego:** `sync_contract_to_live_order` przesuwało
`end_date` NIEZALEŻNIE od statusu, a `create_order_extension` nie filtruje
statusu przy wyszukaniu umowy. Osiągalne skutki: zamówienie dopięte do umowy
`void` (soft-delete, `ALLOWED_TRANSITIONS[void]` = zbiór pusty) po cichu
przesuwało jej datę końca; `draft` dostawał przesuniętą datę z pominięciem
własnego cyklu życia; `active` dostawał rozciągnięty horyzont — zachowanie,
którego przed tą zmianą nie było i o które nikt nie prosił. Funkcja jest teraz
zawężona do `ended`/`ending`, czyli do tego samego zbioru co migracja.

**Brakujący test na zgłoszony objaw:** poprawka kolejności w `PATCH` nie miała
pokrycia, a to wariant 409, którego NIE tłumaczy zdjęcie `end_date` z bramki.

### Jak te poprawki zweryfikowano

Nie zielonym testem obok istniejącej poprawki — każda przez ODWRÓCENIE:

* zdjęta bramka statusu → 3 testy padają, przywrócona → przechodzą;
* przywrócona stara kolejność `PATCH` → test pada z
  `{"message":"Missing required fields","missing":["rate_candidate"]}`, czyli
  odtwarza zgłoszone 409 **co do treści**;
* migracja `0243` puszczona na ZASEEDOWANYCH wierszach, nie tylko na pustej
  bazie: kontrakt `ended` → audyt `from_status='ended'`, kontrakt `ending` →
  `from_status='ending'`, a wiersz z bezterminowym zamówieniem wyszedł
  z `end_date IS NULL` **i** `client_order_end_date IS NULL`.

---

## Weryfikacja

| Bramka | Wynik |
|---|---|
| Backend, przebieg celowany-szeroki (33 pliki dotykające zmienionych modułów) | **521 passed, 4 skipped** |
| Backend, trasy/OpenAPI/schema-inventory (nowy endpoint nie rusza baseline'ów) | 46 passed |
| `alembic upgrade heads` (z 0243) | OK |
| `import app.main` (cykle importów) | OK |
| Frontend `tsc --noEmit` | **0 błędów** |
| Frontend `next lint --max-warnings=300` | OK |
| Frontend `vitest run` (pełny) | **181 plików / 1623 testy passed** |

**Uwaga o flaku lokalnego frontu (zmierzone trzy razy):** pełny przebieg
potrafi zgłosić DOKŁADNIE JEDEN fail, za każdym razem INNY test i zawsze
timeout — przebieg A `CandidateSearchViewSavedSearchReapproval` („Unable to
find role=button" po 2 s), przebieg B pełna zieleń (181 plików / 1623 testy),
przebieg C `TeamAllocationBoard` („Test timed out in 5000ms"). Oba padające
przechodzą w izolacji (3/3 i 11/11) i żaden nie dotyka modułu Kontrakty.

Baseline BEZ moich zmian: 179 plików / 1608 testów, w pełni zielono — czyli
pojedynczy fail pojawia się z dołożonymi plikami, choć ich nie dotyczy
(większe obciążenie równoległe). **Frontowe joby w CI przechodziły na każdym
commicie tego PR-a**, więc problem jest lokalny, a nie w gałęzi.

**Czego NIE zweryfikowano:** nic nie zostało sprawdzone na produkcji ani
w przeglądarce — sesja nie ma dostępu do prodowej bazy ani do zalogowanej
sesji UI. Ekrany zweryfikowane wyłącznie testami i typecheckiem.

---

## Wykonane na produkcji (2026-08-25, po wdrożeniu kodu)

Punkty, które pierwotnie zostawiłem właścicielowi produktu, zostały wykonane
na jego wyraźną prośbę. Poniżej co i jak.

### Brakujące narzędzie: podgląd klientów z produkcji

Pięć polityk domenowych jest bramkowanych LISTĄ `client_id` w zmiennych
środowiskowych, a numeru nie widać ani w repo, ani w interfejsie; SSH na tym
serwerze nie działa. Włączenie którejkolwiek polityki wymagało panelu Coolify.

Powstał `backend/scripts/list_clients.py` (sam SELECT, wildcardy `LIKE`
escapowane) + akcja `client-lookup` w `coolify-ops` uruchamiająca go tym samym
mechanizmem co `eval` (zadanie jednorazowe → odczyt → kasacja). Z `--with-links`
dokłada kontrakty, umowy B2B i zamówienia — bez tego nie da się odpowiedzialnie
przepiąć kontraktu na innego klienta.

Wejście tekstowe do komendy na prodzie jest odstępstwem od zasady „operator
wnosi liczbę albo wybór", więc allowlista jest twarda (`[a-z0-9.-]`, 1–40).
**Dwie usterki tego guardu złapane przed użyciem:** `grep -qE` dopasowuje
LINIAMI, więc wartość wieloliniowa z `; rm -rf /` w drugiej linii przechodziła
(naprawione `case`, który obejmuje cały łańcuch); i spacja w allowliście
rozbijała `--like credit agricole` na dwa argumenty (naprawione zawężeniem do
jednego członu — cytowanie byłoby zgadywaniem, bo nie wiemy, jak Coolify
opakowuje komendę).

### Włączone bramki

| Zmienna | Wartość | Uwaga |
|---|---|---|
| `CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS` | `116,5182,38342` | trzy rekordy banku; `72` (Assurances) pominięty — inna linia biznesowa, a polityka przy braku etykiet CZYŚCI stawkę |
| `ERSTE_GROSS_RATE_CLIENT_IDS` | `103,38336` | oba rekordy tego samego banku (ex-Santander) |

Potwierdzony jest **zapis** (`HTTP 201`) i restart — nie działanie. Weryfikacja
funkcjonalna wymaga wgrania prawdziwego PDF jako zalogowany użytkownik. Bramki
są fail-closed, więc najgorszy skutek błędnego ID to „polityka się nie odpala".

### Awaria produkcji, którą sam spowodowałem — 28 minut

Ustawiając drugą zmienną zaznaczyłem `redeploy=true`. Coolify przyjął trigger
(`HTTP 200`), rozpoczął wdrożenie i kontener nie wrócił: `503 no available
server` na API i froncie, ~18:05–18:33 UTC. Przywrócone ręcznym
`gh workflow run Deploy`.

**Restart nie był potrzebny.** Bramki `*_CLIENT_IDS` czyta `os.environ.get(...)`
w handlerze przy każdym żądaniu — nowa wartość zadziałałaby od najbliższego
zwykłego deployu. `redeploy=true` kupiło „natychmiast" za cenę okna bez
aplikacji.

Dlaczego to wraca (trzy wcześniejsze awarie tej instalacji w pamięci projektu):
jeden kontener bez replik + deploy = pełny rebuild ze źródeł + brak
automatycznego rollbacku. Nie ma taniego „przeładuj konfigurację": zmiana flagi
kosztuje tyle samo ryzyka co wdrożenie kodu.

Dwie rzeczy diagnostyczne, które kosztowały czas: panel Coolify z kodem **302
jest ZDROWY** (przekierowanie na login), a akcja `list` w `coolify-ops` jest
**zepsuta** (`/api/v1/deployments` → 302, `/applications/{uuid}` → 404), więc
w kryzysie nie ma z niej pożytku — trzeba iść wprost `gh workflow run Deploy`.

### Potwierdzenie T7 na żywych danych

Kontrakt 479 (M. Matyszczuk, Erste) ma na produkcji status `active`,
a zgłoszenie opisywało go jako siedzącego w „Zakończonych". Sąsiednie 477 i 478
pozostały `ended`, więc nie jest to efekt hurtowy — migracja `0243` trafiła
w przykład z ticketu.

### Korekta danych CARDIF/BNP

Migracja `0244`. Zakres zawężony decyzją właściciela produktu do samego
przepięcia klienta — bez kasowania. Rzecz, która **zmienia treść pierwotnego
zgłoszenia**: kontrakt 602 („do zostawienia") NIE jest pustym duplikatem — ma
aktywne zamówienie „Projekt DHS POL0208", podczas gdy 551 („do usunięcia")
niesie podpisaną umowę. To dwa różne projekty tej samej osoby.

---

## Do zrobienia po wdrożeniu (wymaga produkcji)

1. ~~Zmienne w Coolify~~ — **zrobione** (patrz wyżej).
2. ~~Korekty danych Cyran/Rogala~~ — **w migracji 0244**, zakres zawężony do
   przepięcia klienta decyzją właściciela produktu.
3. **Umowa 1474/2026 wymaga decyzji prawnej**: po korekcie jej pola mówią
   CARDIF, a wydrukowany dokument nadal „BNP Paribas Cardif”. `render_payload`
   nie jest tykany — wystawienie dokumentu na nowo nie jest zmianą techniczną.
4. **Listy dotkniętych zamówień Credit Agricole i Erste** do korekty stawek —
   nadal niedostarczone. Teraz da się je zrobić: `client-lookup` pokazuje
   zamówienia per klient, brakuje przejrzenia stawek.
5. **Masowa korekta BNP↔CARDIF** — `GET /api/admin/client-mixups?q=cardif`
   → weryfikacja zespołu. 0244 rusza WYŁĄCZNIE cztery wskazane wiersze.
6. **Decyzja produktowa**: czy udostępnić przepięcie kontraktu na innego
   klienta z interfejsu (dziś niemożliwe — `ContractUpdate` nie ma `client_id`,
   więc każde takie zgłoszenie wymaga migracji i inżyniera).
7. **Dług operacyjny**: akcja `list` w `coolify-ops` jest zepsuta i odebrała
   wgląd w kolejkę wdrożeń dokładnie podczas awarii. Warto naprawić osobno.
