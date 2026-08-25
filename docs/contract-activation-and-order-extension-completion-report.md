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

## Weryfikacja

| Bramka | Wynik |
|---|---|
| Backend, przebieg celowany-szeroki (33 pliki dotykające zmienionych modułów) | **515 passed, 4 skipped** |
| Backend, nowe/zmienione pliki testów | 101 + 10 + 12 passed |
| `alembic upgrade heads` (z 0243) | OK |
| `import app.main` (cykle importów) | OK |
| Frontend `tsc --noEmit` | **0 błędów** |
| Frontend `next lint --max-warnings=300` | OK |
| Frontend `vitest run` (pełny) | **181 plików / 1623 testy passed** |

**Uwaga o jednym flaku:** pierwszy pełny przebieg frontu zgłosił 1 fail
w `CandidateSearchViewSavedSearchReapproval` — `findByRole` timeout (2 s)
pod obciążeniem równoległym. Test przechodzi w izolacji, przechodzi
w powtórzonym pełnym przebiegu tego samego zestawu, i nie ma żadnego związku
z modułem Kontrakty. Jest kruchy czasowo; dwa dołożone pliki testów podniosły
obciążenie na tyle, żeby to ujawnić.

**Czego NIE zweryfikowano:** nic nie zostało sprawdzone na produkcji ani
w przeglądarce — sesja nie ma dostępu do prodowej bazy ani do zalogowanej
sesji UI. Ekrany zweryfikowane wyłącznie testami i typecheckiem.

---

## Do zrobienia po wdrożeniu (wymaga produkcji)

1. `CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS` i `ERSTE_GROSS_RATE_CLIENT_IDS`
   w Coolify (workflow „Coolify set env”) — bez nich obie polityki stoją
   bezczynnie (fail-closed).
2. `GET /api/admin/client-mixups?q=cardif` → weryfikacja przez zespół
   produktowy → korekty danych (Marek Cyran, Maciej Rogala).
3. Listy dotkniętych zamówień Credit Agricole i Erste do korekty stawek.
4. Decyzja produktowa: czy udostępnić przepięcie kontraktu na innego klienta
   z interfejsu (dziś niemożliwe — `ContractUpdate` nie ma `client_id`).
