# Generator CV: reguły per klient — raport wdrożenia

**Data:** 2026-08-31 · **Migracja:** `0255_client_cv_rules`

## Po co

Każdy z 14 klientów, dla których mamy w Pomocy własny szablon „Profil
Championa", ma w tym dokumencie sekcję **„7. STANDARDY REKRUTACJI KLIENTA"**
(u Credit Agricole te same treści siedzą w sekcji 6 „INFORMACJE"). Sekcja mówi
wprost, jak ma się nazywać plik CV i w jakim ma być języku.

Generator nic z tego nie wiedział:

- nazwę pliku składał jednym globalnym wzorem `{rola}_{imię nazwisko}.docx` —
  **niezgodnym z żadnym z 14 wymagań**;
- język był ręcznym `Form("pl")`, więc dla Nordei (wyłącznie EN) domyślny wybór
  był zawsze zły;
- ścieżka `upload`, przez którą idzie **99,9% ruchu** (2043 z 2045 generacji),
  nie przyjmowała żadnego kontekstu klienta — przez co istniejący sufit
  `Client.cv_content_mode_cap` obowiązywał dla 0,1% generacji.

## Wymagania wyciągnięte z 14 szablonów

| Klient | Wzór nazwy pliku | Język |
|---|---|---|
| ALIOR, BIK, BNP PARIBAS, SANTANDER | `B2B_{STANOWISKO}_{IMIE_NAZWISKO}` | PL **i** EN |
| Nordea, PFRON | `B2B_{STANOWISKO}_{IMIE_NAZWISKO}` | Nordea: **tylko EN**; PFRON: tylko PL |
| KIR | `B2B_{STANOWISKO}_{IMIE_NAZWISKO}` (podkreślenia) | tylko PL |
| Bank Pocztowy | `Bank_Pocztowy_{STANOWISKO}_{IMIE_NAZWISKO}` | tylko PL |
| Credit Agricole | `B2B.NET_{STANOWISKO}_{IMIE_NAZWISKO}_{DATA}` | tylko PL |
| PANSA | `B2B_PANSA_{STANOWISKO}_{IMIE_NAZWISKO}` | tylko PL |
| Tauron | `B2B_Tauron_{STANOWISKO}_{IMIE_NAZWISKO}` | tylko PL |
| ENERGA | `ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}` | tylko PL |
| ORLEN | `ORLEN_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}` | tylko PL |
| PKO BP | `ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}` | tylko PL |

**Cztery tokeny i jedna flaga pokrywają wszystkie czternaście.** Nie ma osobnych
`{IMIE}` / `{NAZWISKO}`: przy `spaces_to_underscores` „Jan Kowalski" →
„Jan_Kowalski", czyli dokładnie `Imię_Nazwisko`.

## Co powstało

- **`client_cv_rules`** (1:1 z klientem): wzór nazwy, flaga podkreśleń, wymagany
  język, „wymaga też wersji EN", „wymaga zgody RODO", notatka ze standardami,
  `seed_key`, `confirmed_at` / `confirmed_by`.
- **`cv_generated_documents.client_id`** — do tej pory był tylko `job_id`, a tryb
  upload ma go pustego. Historyczne wiersze z trybu „new" zbackfillowane z oferty.
- **`app/services/cv_generator_b2b/client_rules.py`** — składanie nazwy,
  wymuszanie języka, przypomnienia, opis polityki do UI.
- **API**: `client_id` + `position` + `project_ref` w obu ścieżkach generacji,
  `GET/PUT/DELETE /api/clients/{id}/cv-rule`, `POST …/cv-rule/confirm`,
  `GET /api/settings/cv-rules`.
- **Front**: picker klienta i pole „Stanowisko" w generatorze, trójstanowy baner
  reguł, blokada języka, sekcja „Reguły CV" w oknie edycji klienta, ekran
  „Reguły CV per klient" w Ustawieniach, harness `/preview/cv-generator-client-rules`.

## Decyzje, które łatwo odwrócić przez pomyłkę

**Reguła działa dopiero po zatwierdzeniu** (`confirmed_at IS NOT NULL`).
Migracja zasiewa 14 propozycji, ale dopasowanie szablonu do wiersza w `clients`
nie jest 1:1 — samych bytów „BNP" jest siedem. Seed zakłada wiersz **wyłącznie
przy dokładnie jednym** żywym trafieniu nazwy; przy zera lub wielu nie powstaje
nic, a ekran weryfikacji pokazuje pozycję jako „wymaga wskazania klienta".
Dopasowanie po nazwie jest tu dopuszczalne **tylko dlatego**, że nic z niego nie
wchodzi w życie samo z siebie. Edycja obowiązującej reguły ZDEJMUJE
zatwierdzenie — inaczej zmiana wzoru trafiałaby na produkcję bez decyzji.

**Wybór klienta jest opcjonalny.** Generator służy też do CV robionych poza
konkretnym zleceniem. Zły klient jest gorszy niż brak klienta (cicho zła nazwa
i zły język), więc nic nie jest zgadywane, a stan reguł zawsze widać w banerze.

**W trybie „new" klienta wyprowadza serwer z rekrutacji**, front go tylko
pokazuje. Jawny `client_id` w żądaniu jest asercją — rozjazd to 422.

**`cv_language` jest NULL dla czterech klientów wymagających OBU wersji.**
Wymuszenie „pl" zablokowałoby wygenerowanie wersji EN, czyli dokładnie tego,
czego ci klienci oczekują. Ich wymóg niesie `requires_en_copy` — przypomnienie,
nie blokada.

**Reguła przekracza granicę wątku jako niezmienny snapshot**, nie jako wiersz
ORM. Pipeline generacji jest synchroniczny i leci w `run_in_threadpool`, gdzie
dostęp do atrybutu wiersza potrafi skończyć się `MissingGreenlet` — czyli 500
bez CORS, widocznym w UI jako „Network Error".

**Oba odczyty stoją na `OperationalUser`, nie na samym zalogowaniu.** Bramka jest
lustrem `GET /api/clients/{id}` — reguła to konfiguracja klienta, a `notes` niosą
jego standardy handlowe (SLA, off-limit, adresy biur). Nikomu to nie zawęża
dostępu do banera w generatorze: `CANDIDATE_DOCUMENT_ROLES`, czyli bramka obu
ścieżek generacji, to DOKŁADNIE ten sam zestaw siedmiu ról operacyjnych. Wyszło
to z `test_route_authz_contract`, który świadomie nie wpuszcza nowych tras bez
bramki zasobu.

**Brak więzu „confirmed_at i confirmed_by naraz albo wcale".** `confirmed_by` ma
`ON DELETE SET NULL`, więc taki CHECK zerwałby się przy usuwaniu konta osoby,
która regułę zatwierdziła, i zablokowałby DELETE użytkownika.

## Odstępstwo od planu: blok zgody RODO

Plan zakładał, że dla PKO BP renderer dołoży do dokumentu sekcję „Zgoda
kandydata" z miejscem na zrzut ekranu. **Nie zrobiono tego świadomie.** Klient
wymaga wklejenia na dole CV **zrzutu ekranu maila** od kandydata; generator tego
obrazu nie ma, a pusta ramka podpisana „Zgoda kandydata" wysłałaby do banku
dokument wyglądający na niedokończony — gorzej niż brak ramki. Zamiast tego
`requires_rodo_consent_block` produkuje ostrzeżenie w kanale, który rekruter już
zna, plus zdanie w banerze. Dokument pozostaje nietknięty.

## Czego świadomie NIE zrobiono

- **Nie parsujemy sekcji 7 z DOCX-a jako źródła prawdy.** Credit Agricole jej nie
  ma (standardy w sekcji 6) — parser oparty na numerze nagłówka nic by nie
  znalazł, po cichu. Szablon PFRON-u niesie błąd copy-paste z Nordei („sprzęt
  zapewnia bank Nordea") — parser utrwaliłby cudzy zapis jako regułę PFRON-u.
- **Nie liczymy limitów CV** (decyzja produktowa). W schemacie nie ma kolumny na
  limit, w runtime nie ma liczenia `cv_sent`.
- **Nie wpuszczamy standardów sourcingowych do promptu LLM.** „Kandydatów
  z doświadczeniem w bankowości rozważamy w pierwszej kolejności" to reguła
  SZUKANIA; w prompcie generatora byłaby zaproszeniem do koloryzowania
  doświadczenia bankowego.

## Aktywacja na prodzie

1. `/api/health/deep` musi widzieć `client_cv_rules` — to jedyny dowód, że tabela
   powstała (prod alembic bywa osierocony).
2. Ustawienia → **Reguły CV per klient**: 14 pozycji. Część będzie miała stan
   „wymaga wskazania klienta" (spodziewane co najmniej BNP i Credit Agricole).
3. Dla każdej pozycji: profil klienta → Edytuj → **Reguły CV** → sprawdź wzór
   z szablonem Championa → **Zapisz** → **Zatwierdź**.
4. Do czasu zatwierdzenia **nic się nie zmienia** — generator działa jak dotąd.

## Znane ograniczenia

- Modal generatora z profilu kandydata (`CVGeneratorV2`) nie pokazuje banera ani
  nie blokuje języka; reguły obowiązują (liczy je serwer), a rozjazd języka
  wraca jako czytelne 422.
- `{PROJEKT}` uzupełnia rekruter ręcznie — numeru projektu (np. `ZOB-xxxx`) nie
  da się wiarygodnie wyprowadzić z oferty.
- Format `{DATA}` to `YYYY-MM-DD`; szablon Credit Agricole mówi tylko
  „bieżąca_data". Wzór jest edytowalny, więc da się skorygować bez deployu.

## Aktualizacja 2026-09-02 — każdy Delivery Lead zakłada reguły sam + instrukcje dla AI

**Zgłoszenie:** „jak to poprawić, aby każdy Delivery Lead mógł sobie robić
reguły jakie chce?" — z ekranu `/settings/cv-rules`.

**Diagnoza:** backend wpuszczał DL od początku (`PUT/POST/DELETE` za `TacPlus`),
ale ekran był podglądem 14 zasianych szablonów bez żadnej akcji i bez linku
w Ustawieniach; reguła dla innego klienta była tu niewidoczna, a założyć ją
dało się tylko przez okno „Edytuj firmę", dwoma osobnymi kliknięciami
(Zapisz → Zatwierdź). „Reguły jakie chce" nie mieściły się też w schemacie:
jedynym wolnym polem była notatka dla człowieka.

**Decyzje Artura (02.09.2026, pytania w sesji):** reguła per klient, wspólna;
DL zatwierdza sam, dla dowolnego klienta; zapis tylko DL + admin (TAC wypada);
DL dostaje pole instrukcji, które generator AI naprawdę stosuje.

**Co się zmieniło:**

- `GET /api/settings/cv-rules` → `{rules, unassigned_templates}`: każda reguła
  w bazie + szablony Championa bez wiersza.
- `PUT /api/clients/{id}/cv-rule` przyjmuje `confirm: true` — zapis
  i zatwierdzenie jednym kliknięciem („Zapisz i zatwierdź"). Domyślny zapis
  nadal jest propozycją; edycja obowiązującej reguły bez `confirm` zdejmuje
  zatwierdzenie.
- Bramka zapisu `TacPlus` → `DeliveryLeadPlus`; front po nowej capability
  `cv_rule.manage` (lustro w `capabilities.test.ts`); TAC w oknie „Edytuj
  firmę" widzi zdanie odsyłające, nie formularz.
- `client_cv_rules.generator_instructions` (migracja `0266` + lustro
  w `entrypoint.sh`): instrukcje PREZENTACJI dla modelu, blok
  `<client_presentation_rules>` w wiadomości użytkownika (system prompt
  niezmieniony bajt w bajt → cache promptu działa), semantyka i zakaz
  dopisywania faktów w obu promptach systemowych, `<`/`>` neutralizowane,
  sufit 2000 znaków, ostrzeżenie dla rekrutera, opis w `client_policy`.
- `/settings/cv-rules`: lista wszystkich reguł, wyszukiwarka, filtr stanu,
  „Tylko moi klienci" dla persony DL (z `data_scope`, do wyłączenia),
  „Dodaj regułę" z pickerem klienta, edycja / zatwierdzanie / usuwanie
  w miejscu, sekcja szablonów bez reguły, chip „instrukcje AI".
- Link „Reguły CV per klient" w Ustawieniach → Zaawansowane (admin / DL).
- Baner w generatorze pokazuje notatkę DL („Standardy klienta") i instrukcje
  dla AI przy obowiązującej regule — wcześniej notatka nie docierała do
  rekrutera nigdzie.
- Formularz `ClientCvRulesSection` współdzielony z oknem edycji klienta;
  usuwanie z dwustopniowym potwierdzeniem w komponencie.

**Czego świadomie NIE zrobiono:** zawężenia zapisu do portfela DL (to lustro
`PATCH /api/clients/{id}` — reguła CV jest konfiguracją klienta jak jego
karta), wpuszczenia NOTATKI do promptu (reguły szukania koloryzują) ani zmian
w szablonie DOCX (instrukcje o układzie nie mają czego dotknąć).

**Testy:** `backend/tests/test_client_cv_rules_overview.py`,
`backend/tests/test_cv_generator_client_instructions.py`,
`frontend/src/app/settings/cv-rules/page.test.tsx`, rozszerzone
`ClientCvRuleBanner.test.tsx`, `capabilities.test.ts` (macierz + lustro
backendu), `test_cv_generator_client_rules.py` (snapshot).

## Aktualizacja 2026-09-02 (część 2) — pełna recepta Delivery Leada

**Cel (Artur):** rekruter ma mieć jak najmniej wyboru; CV ma się generować
tak, jak Delivery Lead chce dla klienta. Zasady: reguły per klient, jeden
szablon DOCX, blind bez zmian, stawek w CV nigdy, notatka sourcingowa też do
generatora. Wszystko w jednym PR, migracja `0267`.

**Blokady dla rekrutera:** tryb obróbki treści ustawiany dokładnie (wolny /
domyślny / zablokowany — serwer nadpisuje żądanie, sufit z karty nadal
wygrywa), wymagane wejścia (min. długość notatek, numer projektu, stanowisko,
profil Championa → 422 z listą braków przed kwotą, te same zdania widoczne
w formularzu), automatyczna druga wersja językowa, klient w uploadzie
podpowiadany z procesu kandydata, generacja bez klienta za jawnym checkboxem.
Sufit trybu i interaktywne CV prowadzone z edytora reguły (zapis na `clients`).

**Polityka prezentacji egzekwowana w kodzie:** sekcje do pominięcia, limity
stanowisk / punktów / długości punktu, liczba punktów „dlaczego ten
kandydat", format dat, słownik klienta. Model dostaje to samo jako instrukcje;
kod domyka po odpowiedzi i zgłasza, co domknął.

**Reguły AI:** instrukcje PL + wariant EN, notatka DL w osobnym bloku
`<client_notes>` pod tą samą granicą, lint linia po linii tanim modelem
(nowy klucz kwoty `cv_rule_lint`), podgląd dokładnego bloku promptu, CV
próbne z regułą i bez obok siebie (w tle, osobna tabela, dwa obciążenia
kwoty), sygnał zwrotny (pominięte instrukcje per tekst, domknięcia polityki),
historia zmian z diffem, stempel wersji reguły na każdym wygenerowanym CV,
kopiowanie reguły z innego klienta jako propozycji.

**Front:** edytor w pięciu zakładkach (Podstawy · Generator · Treść i AI ·
Podgląd · Historia) na `/settings/cv-rules` (deep link `?client=`), okno
„Edytuj firmę" tylko odsyła. Generator: kafelki trybu wyłączone przy blokadzie,
alert z brakami przed kliknięciem, picker kandydata w uploadzie.

**Poza zakresem świadomie:** reguły per rekrutacja, wzorcowe CV jako przykład
dla modelu, bramka zatwierdzania każdego CV przez DL, wariant szablonu DOCX.

**Testy:** `test_cv_rule_presentation_policy.py`,
`test_client_cv_rules_recipe_api.py`, `CvRuleEditor.test.tsx`, rozszerzone
`page.test.tsx`, `ClientCvRuleBanner.test.tsx`, `capabilities.test.ts`.
