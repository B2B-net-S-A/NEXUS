# Rozliczenia klientów — roadmapa wdrożenia

Stan na 12.11.2026. Plik jest planem dla kolejnych sesji: każda zmiana kodu
rozliczeń odnosi się do etapu stąd (`E1.3` w opisie commita i PR-a), a po
zakończeniu etapu sesja odhacza go w tabeli „Stan etapów”.

Repo jest publiczne: w tym pliku, w kodzie, testach i PR-ach nie ma nazwisk
konsultantów, stawek ani kwot z prawdziwych dokumentów. Makiety z danymi
leżą w prywatnym artefakcie Artura i w paczce `~/NEXUS-rozliczenia-makiety/`
na jego laptopie (poza repo).

## Cel

Koniec ręcznego sprawdzania maili na `rozliczenia@`. Konsultant wysyła
dowód pracy (RCP, raport klienta, arkusz godzin) panelem albo mailem, NEXUS
od razu sprawdza go regułami jego klienta i mówi, czego brakuje. Finanse
widzą miesiąc klienta jako jedną listę, przyjmują zbiorczo to, co przeszło
kontrole, przy przyjęciu z zamówienia schodzą MD, a NEXUS składa pozycje
faktury do klienta. Faktura kontraktora przychodzi z KSeF i NEXUS porównuje
ją z wyliczeniem.

Wspólny silnik, różne wejścia i wyjścia per klient: siedmiu klientów
z próbek (BNP, PKO, Alior, Bosch, CeZ, Orlen, Velo) różni się dowodem
pracy, tym, kto podpisuje, i dokumentami wychodzącymi, a nie samym
przepływem.

## Co już jest w kodzie (fundament)

| Element | Gdzie | Co daje rozliczeniom |
|---|---|---|
| Panel konsultanta z linku, sesja poza JWT, wyłącznik `off/pilot/all` | `app/api/consultant_portal.py`, `services/consultant_portal/`, reguła `docs/claude/ludzie/portal-konsultanta.md` | Kanał „panel” i tożsamość konsultanta (kontrakt) |
| Dokumenty konsultanta: `cp_documents` (kontrakt, okres, rodzaj `report`/`invoice`, kanał `portal`/`mailbox`, status `received/accepted/rejected/paid`, SHA-256; bez MD, godzin i kwot) | `services/consultant_portal/documents.py` (`store` :126, `accept` :428, `reject` :457), schemat `consultant_portal_schema.py:219` | Przyjęcie pliku z dwóch kanałów do jednego wiersza; przyjęty raport daje sygnał „wystaw fakturę” (`invoice_signal_at`) i mail do konsultanta |
| Typy plików: tylko PDF, DOCX, JPG, PNG, do 20 MB, wykrywane z treści | `services/hr/documents_store.py:28` | Excel RCP i mail `.msg`/`.eml` dziś odpadają |
| Karta Finansów w back office na (kontrakt, okres, rodzaj) i trasy `accept`/`reject`/`paid`/`assign` | `back_office/sources.py:590`, `api/consultant_portal_staff.py:403` | Dzisiejsze przyjmowanie dokumentu po jednym, bez kontroli |
| Czytnik skrzynki rozliczeń `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` co 15 min, nadawca po adresie z kontraktu | `services/consultant_portal/mailbox.py` | Kanał „mail na rozliczenia@”; **skrzynka i dostęp Graph nie są jeszcze skonfigurowane** (`mailbox.py:4`) |
| Szablon rozliczenia klienta: `client_settlement_rules` (`mode` `client_report`/`report_with_approval`/`own_report` + tekst do 5000 znaków), karta na kliencie | `models/consultant_panel.py:127`, `consultant_portal/materials.py:224`, `clients/[id]/ClientSettlementCard.tsx` | Dziś tylko tryb i opis dla konsultanta, bez reguł |
| Ekrany panelu „Rozliczenia” i „Faktury” | `konsultant/(panel)/rozliczenia`, `faktury` → `PanelScreens.tsx:286`, `DocumentsSection.tsx` | Rozbudowujemy je w E3 zamiast stawiać nowe; termin płatności stały 14 dni (`panel.py:62`) |
| Linie zamówień MD per osoba: `client_orders` (`md_total`, `md_remaining`, `md_rate_revenue`, `md_rate_cost`) w grupach `client_order_groups` | `models/client_order.py`, `client_order_group.py` | Pula MD osoby i stawki do wyliczeń |
| Zużycie MD za miesiąc: `client_order_md_consumptions`, unikat (linia, miesiąc), `upsert_consumption` | `services/client_order_lines.py:2270`, reguła `zamowienia/historia-zamowienia-zuzycie-md-i-importy-md.md` | Zejście MD; dziś źródło tylko `import`/`manual` (CHECK) |
| MD czekające na kolejne zamówienie | `services/md_awaiting_orders.py`, reguła `zamowienia/md-oczekujace-na-kolejne-zamowienie.md` | Wzorzec dla statusu „Brak MD” |
| Faktury sprzedażowe z KSeF (`Subject1`): `client_sales_invoices`, dopasowanie NIP → klient, numer zamówienia, kwota, osoba+stawka | reguła `zamowienia/faktury-do-klientow-z-ksef.md` | Weryfikacja, że faktura do klienta poszła i z jaką kwotą |
| Faktury kosztowe z KSeF (`Subject2`) do `payroll_invoices` | `services/hr/ksef/sync.py` | **Tylko od NIP-ów pracowników** z `employee_billing_details`; faktur kontraktorów B2B dziś nie zapisujemy |
| Stawki w czasie | `contract_candidate_rates`, `effective_candidate_rate` | Kwota „ile wychodzi z RCP” przy zmianie stawki w miesiącu |
| Uprawnienie do kwot klienta | `can_read_client_finance` (Finanse, DL u swojego klienta) | Marża i pozycje faktury do klienta |

### Luki w danych (kopia produkcji z 09.11, BNP: 50 aktywnych kontraktów)

- NIP konsultanta ma 10 z 50 osób BNP (tylko z generatora umów B2B,
  `b2b_generated_contracts.partner_nip`; `candidates.nip` jest pusty u wszystkich).
  Bez NIP-u nie dopasujemy faktury kontraktora z KSeF.
- Adres do panelu (`contracts.candidate_email`) ma 10 z 50 osób BNP. Bez niego
  panel się nie otworzy, zostaje mail na `rozliczenia@`.
- 2 z 50 kontraktów BNP nie mają aktywnej linii zamówienia.
- W całym NEXUSIE 70 kontraktów bez numeru zamówienia w kontrakcie (PKO 33,
  Alior 13, Orlen 10, Velo 8, Bosch 6) i kilku klientów bez NIP-u.
- Poprawka z 12.11 (kopia produkcji z 10.11): u PKO to nie jest luka. Numer
  zamówienia PKO stoi w tytule linii zamówienia (`client_orders.title`, wzór
  „NNNN/2026”, 32 aktywne linie), a numer SSGW w PDF-ie zamówienia. Lukę
  numeru liczymy więc z `client_orders`, nie z samego kontraktu; liczby
  pozostałych klientów są do sprawdzenia tym samym sposobem przy ich etapie E6.

## Zasady, które obowiązują we wszystkich etapach

1. „Dziś NEXUS robi” odróżniamy od „propozycji” na ekranach i w opisach PR-ów.
2. Każdy etap wchodzi za wyłącznikiem modułu (`app_settings['client_settlements']`,
   domyślnie wyłączony) i nie zmienia dzisiejszych ścieżek, dopóki Finanse go nie włączą.
3. Reguła klienta jest daną (katalog w kodzie, wartości w bazie), nie `if klient == …`.
4. Zejście MD idzie tylko przez `upsert_consumption`; ponowne przyjęcie RCP
   nadpisuje wpis miesiąca, a nie dokłada.
5. Konsultant nie widzi stawki klienta, marży ani mnożnika nadgodzin
   (lista dozwolonych pól w `panel.py`, testy `test_consultant_panel_screens.py`).
6. Kwoty liczymy w `Decimal`, „dziś” to `business_today()`.
7. Nowa trasa `/api/**` ma bramkę Finansów z `api/permission_access.py`
   i wpis we wzorcu `tests/data/authz_golden/`.
8. Schemat: migracja Alembic + lustro w `entrypoint.sh`; PR z migracją
   wprowadza pas migracji.

## Jak wdrażamy (decyzje Artura z 09.11.2026)

- Etapy po kolei E1 → E2 → E3 → E4 → E5, potem E6, E7 i E8 (E8.1 w M365 może iść
  od razu, bo nie wymaga kodu).
- **Jeden PR na całość do E5**, jak back office: jedna gałąź, wiele commitów
  z numerem etapu (`feat(rozliczenia): E1.2 katalog reguł`), wszystko przeklikane
  lokalnie na stagingu (`docker-compose.staging.yml`, front gałęzi na 3101),
  dopiero potem PR. Gałąź wypychamy tylko jako kopię zapasową, bez PR-a.
- PR ma migracje, więc do kolejki wprowadza go pas migracji (bez `--auto`).
- Moduł wchodzi wyłączony; włączają Finanse po przeklikaniu na produkcji (E7).
- Lokalne środowisko gałęzi: baza `nexus_branch_rozl` w Postgresie stagingu
  (kopia nocnej kopii z 09.11 bez dużych tabel CV), backend
  `nexus-staging-backend-rozl` na 8108 (obraz stagingu, kod z worktree),
  front gałęzi na 3101. Migracje: `alembic -c alembic/alembic.ini upgrade heads`
  z `backend/` na tej bazie. Po scaleniu do usunięcia.
- **Termin 08.12 przy tej kolejności:** estymacja zdąży tylko, jeśli PR z E1–E5
  wejdzie do kolejki do 03.12 (wieczorne wdrożenie, dzień na sprawdzenie).
  Sprawdzamy to 26.11: jeśli E1–E3 nie są gotowe na stagingu, estymacja
  grudnia idzie ręcznie, a E5.3 zostaje na 2027.

## Etapy

### E0. Dane i decyzje przed kodem (bez kodu, równolegle z E1)

- E0.1 NIP konsultantów: decyzja Artura z 09.11 — **nie uzupełniamy ręcznie**,
  NIP podpowiada E4 z faktur w KSeF (E4.0). Adres do panelu (10 z 50 osób BNP)
  zostaje do E3: bez niego osoba rozlicza się mailem.
- E0.2 Odpowiedzi rozliczeń na 4 pytania BNP — **są (10.11.2026)**:
  - 2 darmowe MD tylko przy nowej rekrutacji (nowe stanowisko), przedłużenie
    zamówienia bez nich — zgodne z silnikiem (kontrakt od tego lub poprzedniego
    miesiąca);
  - plan grudnia od konsultantów do 04.12 (parametr „plan do” w regule
    estymacji); najpierw listopad i zejście MD, plan grudnia nie jest
    rozpatrywany przed listopadem; listopad i grudzień to **dwie osobne
    faktury** do klienta;
  - koszty integracji: limit 2 000 zł na rok kalendarzowy, tylko BNP — do
    zrobienia przy `cl.integration_costs`;
  - zgodę banku na RCP w NEXUS-ie i ich przechowywanie zbiera DL przypisany
    do BNP (blokuje pilotaż E7, nie kod);
  - MD ponad zamówienie: zamiast „nie wystawiaj” — „wystaw fakturę na X MD,
    tyle zostało”, bez obiecywania zamówienia; przyjęcie zdejmuje pulę, nadwyżka
    czeka na decyzję Finansów (decyzja Artura 10.11);
  - przed przyjęciem zbiorczym Finanse mogą pobrać każdy plik z karty osoby;
    RCP z numerem KSeF pobiera się przy osobie albo hurtem „wystawionych”.
- E0.3 Odpowiedzi rozliczeń dla pozostałych klientów (pytania w zakładkach
  makiety) — blokują E6, nie E1–E5. **Alior, Bosch, Velo, PKO są (12.11.2026)**,
  CeZ i Orlen nadal czekają. Reguły z odpowiedzi stoją w katalogu z etapem E6
  (silnik ich jeszcze nie sprawdza).
  - Wszyscy: koszty dodatkowe (zwrot kosztów niefakturowany klientowi, dopłata
    za weryfikację techniczną) przed oznaczeniem jako błąd albo odrzuceniem
    potwierdza osoba rozliczająca klienta — ta kontrola nigdy nie blokuje sama
    (`travel.extra_costs_confirm`, domyślnie „Ostrzega”).
  - Alior: zapłata konsultantowi po podpisie klienta na KEŚU; gdy podpisujący
    jest nieobecny i nie ma zastępstwa, po mailowej akceptacji, a podpisane KEŚU
    sprawdzamy później (`pay.after_client_signature`, `pay.mail_accept_fallback`).
    Nie sprawdzamy, kto podpisał KEŚU (idzie do akceptanta z maila). KEŚU
    dostaje koordynator automatycznie z Jiry po akceptacji klienta i przekazuje
    dalej. Koszty dodatkowe mogą iść na fakturę główną, jedną pozycją albo
    osobną (`cl.extra_costs_on_invoice`). Oświadczenia o własnym transporcie
    (z danymi osobowymi) nie trafiają do NEXUS-a, a panel konsultanta nie
    pokazuje informacji o jeździe własnym autem.
  - Bosch: od listopada 2026 Service Delivery Confirmation (SDC) dla każdego
    projektu; kolumna Task ID na razie z timesheetu konsultanta, docelowo SDC
    może zastąpić TS i wypełnia go konsultant. Jedna osoba realizuje dwa
    projekty, więc ok. 270 h w miesiącu bywa poprawne, a zużycie bywa niepełne
    albo z przekroczeniami: u Boscha miesięczny limit godzin/MD nie blokuje
    (`fields.md_month_limit` wyłączona). Wszystkie osoby idą z jednego
    zamówienia (dwie stawki MD w EUR). Konsultant może wystawić jedną fakturę
    za wszystkie usługi u Boscha. Grudzień co roku na estymacjach; dla dwóch
    osób prośba o rozliczenie listopada i grudnia do 08.12.2026.
  - Velo: podpisuje jedna z trzech osób klienta (zastępują się przy
    nieobecności). Karta ewidencji klienta może zastąpić mail z akceptacją;
    podstawą faktury do klienta są podpisane arkusze zbiorcze
    (`cl.after_signed_document`). MD osoby w miesiącu nie powinno przekraczać
    dni roboczych (zamówienie określa MD); przypadek 34 MD to osoba u dwóch
    klientów, zapis błędny (`fields.md_month_limit`). Konsultanta rozliczamy, gdy
    jego arkusz jest podpisany, bez czekania na pozostałe (`pay.per_person`).
    Arkusze przekazują dwaj koordynatorzy po naszej stronie; niezależnie od
    tego, kto wrzuci je na rozliczenia@, NEXUS rozpoznaje osobę i przypisuje
    plik. Każdy arkusz do podpisu klienta do pobrania osobno, żeby wysłać go od
    razu, gdy gotowy (`cl.client_document`).
  - PKO: faktura kontraktora sprawdzana standardowo (data sprzedaży, kwota, VAT,
    nabywca B2B.net S.A., miesiąc w opisie usługi = rozliczany). Liczba godzin
    albo MD w prośbie o akceptację wystarcza, ale musi być zaakceptowana; przy
    prośbach nadpisywanych co miesiąc liczy się akceptacja za rozliczany
    miesiąc, a mail do akceptującego ma liczbę godzin w treści
    (`proof.accept_has_hours`). Kod projektu konsultant dostaje od opiekuna po
    stronie klienta. Akceptować może ktoś inny niż koordynator. Jeden zbiorczy
    protokół odbioru na wszystkie osoby (wzór z załącznika do umowy), podpisuje
    najpierw nasza spółka, potem klient; idzie razem z TS i plikami HTML
    akceptacji na skrzynkę body leasingu klienta (adres tylko w regule w bazie,
    `cl.send_to`). Paczka czeka na wszystkich, faktury do klienta dopiero po
    podpisanym protokole (`cl.client_document`, `cl.after_signed_document`).
    MD z zamówień nie wolno przekraczać (`order.no_md_holds_invoice`).
- E0.4 Skrzynka: **docelowo tylko `wsparcie@b2bnetwork.pl`** (decyzja Artura
  z 09.11, etap E8). Na start rozliczenia@ i administracja@ trafiają do wsparcie@
  (alias albo przekierowanie w M365) i dostęp rejestracji „NEXUS Kadry” do
  wsparcie@. Instrukcję i regułę `docs/claude/ludzie/jedna-skrzynka-wsparcie.md`
  przygotowuje osobna sesja.
- **Meta:** odpowiedzi wpisane w zakładce `uwagi`; poczta rozliczeń dochodzi
  do wsparcie@, a `cp_mailbox_state` na produkcji jest bez błędu konfiguracji.

### E1. Silnik miesiąca i reguły klienta (BNP jako pierwszy)

Cel: rozliczenie (kontrakt × miesiąc) jako byt z własnym statusem,
reguły klienta jako katalog z poziomami.

- E1.1 Tabela `client_settlements`: `contract_id`, `client_id`, `period_month`,
  `kind` (`actual` / `estimate`), status RCP
  (`missing` · `checking` · `ok` · `warnings` · `needs_fix` · `no_md` · `accepted`),
  `md_regular`, `md_extra` (nadgodziny przed mnożnikiem), `md_charged`
  (to, co schodzi z zamówienia), `amount_cost`, `amount_revenue`,
  `order_id` (linia `client_orders`), `report_document_id` → `cp_documents`,
  `checks` JSONB (wynik kontroli), `accepted_by/at`. Unikat (kontrakt, miesiąc, rodzaj).
- E1.2 Katalog reguł w kodzie (`services/client_settlements/rules_catalog.py`):
  klucz, sekcja (Dowód pracy, Zamówienie i MD, Pola i sumy, Nadgodziny i dyżury,
  Delegacje, Faktura kontraktora, Faktura do klienta), typ parametrów, domyślny poziom.
  Wartości per klient w `client_settlement_rule_sets` (klient, `effective_from`,
  `rules` JSONB `{klucz: {level, params}}`; poziom `block`/`warn`/`off`). Odczyt reguł
  „na miesiąc” bierze najnowszą wersję ≤ miesiąca.
- E1.3 API Finansów (bramka `FinanceModuleUser`, kwoty i marża tylko przy
  `can_read_client_finance`; wyłączony moduł = 404). Kontrakt, z którego
  korzysta front i makiety (`frontend/src/lib/api/client-settlements.ts`):
  - `GET /api/finance/settlements/clients` → klienci z aktywnymi kontraktami:
    `client_id`, `name`, `active_contracts`, `rules_set`, `todo`.
  - `GET /api/finance/settlements?client_id=&month=YYYY-MM` → `counts` per filtr
    i `rows`: `contract_id`, `settlement_id` (null, gdy nic nie wpłynęło),
    `person`, `order_number`, `status`, `issues` (tekst kontroli z uwagą),
    `md_regular`, `md_extra`, `md_charged`, `md_remaining_after`,
    `amount_cost`, `amount_revenue`, `margin`, `margin_pct`,
    `contractor_invoice` (`none` · `can_issue` · `in_ksef` · `differs`, do E4 zawsze `none`),
    `client_invoice` (`waiting` · `ready` · `issued`, do E5 `waiting`).
  - `GET /api/finance/settlements/contract/{contract_id}?month=` → karta osoby:
    nagłówek (klient, zamówienie, umowa), `documents`, `lines` wyliczenia
    (pozycja, MD, mnożnik, stawka, netto), `checks` w grupach
    (`state` `ok`/`warn`/`fail`/`none`, `title`, `detail`), `order` (pula, zejdzie, zostanie).
  - `PUT …/contract/{contract_id}/md` (`md_regular`, `md_extra`): MD z RCP wpisane
    przez Finanse — w E1 jedyne źródło liczby, od E2 poprawka odczytu.
  - `POST …/contract/{contract_id}/accept`, `POST …/needs-fix` (`reason`),
    `POST /api/finance/settlements/accept-batch` (`client_id`, `month`) — przyjmuje
    tylko `ok`.
  - `GET /api/finance/settlements/rules/{client_id}?month=` → sekcje katalogu
    z regułami (`key`, `name`, `level`, `params`, `hint`) i `effective_from`;
    `PUT` ten sam adres zapisuje całość od podanego miesiąca;
    `POST …/rules/{client_id}/copy-from/{source_client_id}`.
- E1.4 Przyjęcie RCP → `upsert_consumption(source='settlement')` na linię zamówienia
  (CHECK źródła rozszerzony), MD z mnożnikiem nadgodzin; brak MD na linii →
  status `no_md`, plik zostaje, sygnał faktury czeka na nowe zamówienie albo
  wyjątek Finansów (wzorzec z `md_awaiting_orders`).
- E1.5 MD wdrożeniowe: 2 MD za 0 zł, nie schodzą z puli, także po powrocie
  z przerwy; niewykorzystane przechodzą na kolejny miesiąc (parametry reguły).
- E1.6 Ekrany Finansów: zakładka „Rozliczenia” w `/finance` z podzakładkami
  „RCP i faktury kontraktorów”, „Reguły klienta”; karta osoby.
- **Meta:** na stagingu dla BNP za październik: lista 50 osób, ręcznie wgrany
  RCP jednej osoby przyjęty → wpis w `client_order_md_consumptions` z właściwym
  MD, ponowne przyjęcie nadpisuje; testy reguł brzegowych (brak MD, MD wdrożeniowe
  z przeniesieniem, nadgodziny × 1,2, klient bez reguł); zrzuty 1280 × 720.
  Zmiana stawki w trakcie miesiąca przechodzi do E2, bo wymaga dni z RCP.
  MD wdrożeniowe liczą się na kontrakt; odnowienie po przerwie czeka na E0.2.

### E2. Odczyt dowodu pracy BNP i kontrole przy wgraniu

- E2.1 Parser RCP BNP: PDF z podpisem (pyHanko: ważność podpisu, wystawca
  certyfikatu, plik bez zmian po podpisie; numer seryjny certyfikatu nie trafia
  do bazy, bo zawiera PESEL) i Excel z szablonu banku; odczyt miesiąca, godzin
  dziennych, Product ID, kodu CMDB.
- E2.2 Kontrole z katalogu: miesiąc, podpis, sumy MD od nowa (1 MD = 8 h,
  szablon BNP obcina do 0,99 MD), limit 24 h dziennie, weekend, nazwisko na RCP.
- E2.3 Nadgodziny: mail akceptujący (`.msg`/`.eml`/PDF) jest w dokumentach miesiąca.
  Zrobione 13.11 (`acceptance_mail.py`): czytamy każdą wiadomość łańcucha (nagłówek
  pliku i bloki „From/Od … Sent/Wysłano/Data” w treści i w wydruku PDF), bo zgoda
  przychodzi zwykle jako „FW: FW: …”. Data zgody = najwcześniejsza wiadomość
  z domeny z parametru `extra.mail_accept` (dokładnie, bez poddomen: konsultant
  BNP pisze z `external.` w domenie banku) i ma być nie później niż pierwszy dzień
  pracy dodatkowej z RCP; ten sam parametr `domain` sprawdza mail przy Excelu
  (`proof.excel_with_mail`). `.msg` czyta wspólny czytnik `mail_file.py`
  z E6.3 Aliora (kontener OLE bez zależności); `olefile`, zgodzony przez Artura
  13.11, okazał się zbędny, a `extract-msg` odpada (GPL). Mail bez daty albo
  nadawcy = „sprawdza człowiek”. Próbka BNP za październik: przełożony potwierdza
  nadgodziny 02.11, razem z akceptacją RCP — przy `extra.mail_before` na
  „Ostrzega” taka osoba dostaje uwagę „Akceptacja z 02.11.2026, po pracy dodatkowej”.
- E2.0 Typy plików: XLSX, `.msg`, `.eml` dla dokumentów rozliczeń (wykrywane
  z treści jak dziś, bez rozszerzania pozostałych ścieżek `documents_store`).
- E2.4 Uruchomienie kontroli w `documents.store` (oba kanały), wynik w
  `client_settlements.checks`; awaria parsera = status `checking` do ręcznego
  sprawdzenia, nigdy blokada pliku.
- **Meta:** 3 prawdziwe komplety RCP z `BNP.zip` przechodzą lokalnie z wynikiem
  zgodnym z ręcznym przeliczeniem (dane testowe zanonimizowane w repo,
  oryginały tylko lokalnie).

### E3. Panel konsultanta: rozliczenia

- E3.1 **Styl A „Do zrobienia”** (decyzja Artura z 04.11.2026, pamięć
  `consultant-panel-vision-2026-11-04`): bez paska kroków miesiąca ze stylu C
  i z makiety BNP. Rozliczenie wchodzi do listy „Do zrobienia” („Popraw RCP” z powodem,
  „Dołącz mail z akceptacją”, „Wyślij fakturę” z kwotą) i do wiersza miesiąca na
  ekranie „Faktury”: wynik sprawdzenia RCP (lista dozwolonych pól: bez stawki klienta,
  marży i mnożnika), MD i zużycie zamówienia (gdy reguła `order.md_visible` włączona).
  Status faktury do czasu eBI24: „Przyjęta” z terminem (numer KSeF + dni z reguły).
- E3.2 „Wystaw fakturę w KSeF”: dane nabywcy, data sprzedaży, kwota z przyjętego
  RCP, pozycje do skopiowania (kopiowanie, nie wystawianie); termin płatności
  z reguły klienta zamiast stałego `PAYMENT_DAYS`.
- **Meta:** testy listy dozwolonych pól; przeklikanie w stanie `pilot` na jednym
  kontrakcie stagingu.
- E3.2 dokończone 10.11 razem z E4: w wierszu miesiąca „Dane do faktury” z
  przyciskami „Kopiuj” (nabywca, NIP, adres, jedna pozycja „Usługi zgodnie z
  umową za <miesiąc>”, ilość, kwota netto, data sprzedaży). Jedna pozycja, bo
  osobna na pracę dodatkową zdradzałaby mnożnik. Faktura już w KSeF zastępuje
  te dane stanem „Faktura w KSeF: płatność do …”, inna kwota daje zadanie
  „Wystaw korektę faktury”.

### E4. Faktura kontraktora z KSeF

- E4.0 NIP z faktur (decyzja Artura z 09.11): faktura `Subject2` od nieznanego
  NIP-u, której sprzedawca (imię i nazwisko) i kwota wskazują jedno rozliczenie
  miesiąca, daje podpowiedź „NIP kontraktora” do zatwierdzenia przez Finanse;
  zatwierdzony NIP trafia do kontraktu i od tej chwili wiąże faktury sam.
  Pierwszy miesiąc dopasowań idzie wolniej, bo każdy NIP ktoś zatwierdza.
- E4.1 Pobieranie `Subject2` zapisuje też faktury od NIP-ów kontraktorów
  (NIP z kontraktu/generatora B2B) — nowa tabela albo rozszerzenie `payroll_invoices`
  o `contract_id` (decyzja przy E4 po przeczytaniu `hr/ksef/sync.py`).
- E4.2 Dopasowanie faktury do rozliczenia: NIP nabywcy, kwota = wyliczenie
  (tolerancja z reguły), termin płatności, nazwa usługi; statusy „Może wystawić”,
  „W KSeF”, „Inna kwota”.
- **Meta:** na kopii produkcji faktury kontraktorów BNP z października dopasowane
  do wyliczenia; różnice wypisane z powodem.
- Jak zrobione (10.11): nowa tabela `client_contractor_invoices` (migracja 0679),
  nie `payroll_invoices` — tam faktura poszłaby do dopasowania Płac
  (`settlements.match_invoice`). Zapis z samych metadanych KSeF, bez pobierania
  XML-a (limit pobrań zostaje dla Płac), tylko przy włączonym module rozliczeń;
  faktura kontraktora nie trafia już do kosztów „Zgód”. NIP osoby: `candidates.nip`,
  potem `partner_nip` z generatora umów. Termin płatności = data numeru KSeF +
  `ci.payment_days` (metadane nie mają terminu z faktury), nazwy usługi nie
  sprawdzamy (jest tylko w XML-u). Miesiąc faktury: równa kwota w miesiącu
  wystawienia albo poprzednim, inaczej od 25. dnia bieżący, wcześniej poprzedni.
  Korekty sumują się z fakturą pierwotną po netto.
- Kontrole korekt i białej listy (13.11, po teście Finansów na fakturze z sześcioma
  korektami, którego sama suma netto nie łapała): XML FA pobieramy tylko dla korekt
  i faktur, które one korygują (najwyżej 10 na przebieg KSeF, po Płacach), kolumny
  `details` i `vat_whitelist` (migracja 0688). Na karcie osoby ostrzeżenia:
  łańcuch po netto, VAT i brutto („Korekty zostawiają X zł VAT”), numer i data
  faktury korygowanej kontra dokument wskazany numerem KSeF, „stan przed” kontra
  stan dokumentu korygowanego (jego pozycje, jego zmiana albo stan łańcucha),
  korekta bez zmian kwot jako uwaga; biała lista VAT na dzień wystawienia (VAT od
  podmiotu spoza listy czynnych, „zw” od czynnego), wynik przy fakturze, najwyżej
  60 ze 100 zapytań dziennie, awaria wykazu = „nie sprawdzono”. Korekta przechodzi
  do kontraktu i miesiąca faktury, którą koryguje. Kod: `invoice_chain.py`,
  `contractor_details.py`. Wymaga `WHITE_LIST_MODE=live`, inaczej biała lista
  „nie sprawdzono (wyłączone)”.
- Po wdrożeniu: znacznik pobierania na produkcji jest już za październikiem,
  więc faktury z października wymagają „Pobierz ponownie okres” (Płace).

### E5. Faktura do klienta i estymacja BNP (termin 08.12)

- E5.1 „Do faktury dla klienta”: pozycje jak dziś w KSeF (opis, ilość MD,
  cena, przyrostek `_nadgodziny`), marża w zł i % (Finanse, DL swoich klientów),
  koszty integracji do limitu ze zgodą DL.
- E5.2 Załączniki: RCP nazwane numerem KSeF faktury do klienta, reszta plików
  w tej samej paczce; pobranie zip.
- E5.3 Estymacja: rozliczenie `kind='estimate'` = RCP z planem na każdy dzień,
  przyjmowane dopiero po przyjęciu listopada i zejściu MD, nie ponad resztę puli;
  wyrównanie tylko w dół, w RCP za styczeń i na kolejnej fakturze.
- E5.4 Ekran „Listopad i plan grudnia” i krok estymacji w panelu.
- **Meta:** do 05.12.2026 na produkcji lista BNP pozwala złożyć fakturę z
  listopadem i estymacją grudnia; inaczej estymacja wraca na 2027 (zapis w tabeli stanu).
- Jak zrobione (10.11):
  - E5.1 podzakładka „Do faktury dla klienta”: nazwa pozycji z ostatniej faktury
    do klienta za tę grupę zamówienia (bez przyrostka), MD × stawka klienta,
    nadgodziny osobną pozycją z przyrostkiem z `cl.overtime_item` po stawce ×
    mnożnik, MD wdrożeniowe pozycją `_onbording` za 0 zł; bez poprzedniej faktury
    nazwa zastępcza z ostrzeżeniem. „Kopiuj pozycje” (tabulatory, przecinek
    dziesiętny), netto i marża tylko z dostępem do kwot. Stan „Wystawiona”, gdy
    faktura z KSeF jest przypięta do grupy zamówienia i miesiąca.
  - E5.2 „Pobierz RCP (zip)”: RCP pierwsze, potem maile; przy `cl.attachment_name`
    nazwa = numer KSeF faktury do klienta, inaczej numer zamówienia i osoba.
  - E5.3 reguła `cl.estimate` (`months`, np. 12): plik za miesiąc, który trwa, to
    plan (`kind='estimate'`); plan przyjmujemy po przyjęciu poprzedniego miesiąca
    i nie ponad resztę puli; faktura za ten miesiąc idzie z planu; RCP faktyczne
    ponad plan odrzucone, mniej MD = ujemna pozycja `_korekta_estymacji` na
    fakturze za kolejny miesiąc; zejście MD nadpisuje się faktycznym.
  - E5.4 podzakładka „Plan miesiąca” (poprzedni miesiąc, zostało MD, plan, stan,
    do faktury, „Przyjmij plany bez uwag”) i w panelu konsultanta zadanie
    „Wyślij RCP z planem na <miesiąc>” oraz stan planu w wierszu miesiąca.
  - Decyzja Artura z 10.11: konsultant fakturuje miesiąc z planem dopiero po
    faktycznym RCP (dane do faktury po przyjęciu RCP z następnego miesiąca);
    z planu fakturujemy tylko klienta.
  - Dokończone 13.11 (migracja 0691):
    - Koszty integracji `cl.integration_costs` (`integration_costs.py`, tabela
      `client_settlement_extras` z rodzajem `integration`, wspólna z dodatkami do
      rozliczenia kontraktora): Finanse wpisują koszt na karcie osoby
      (kwota, czego dotyczy, miesiąc), DL klienta daje zgodę albo odrzuca; Finanse
      ani admin zgody nie zastępują. Limit z parametru `limit` na konsultanta
      (kandydat, bez niego kontrakt) u klienta w roku kalendarzowym miesiąca
      kosztu: wpis odmawia, gdy przyjęte i czekające z nowym przekroczą limit,
      zgoda — gdy przyjęte z tym przekroczą; pusty limit = bez limitu. Czekający
      koszt Finanse mogą cofnąć. Marżę miesiąca obniża tylko koszt ze zgodą
      (lista miesiąca, „Do faktury dla klienta”, widok DL-a).
    - Marża dla DL-a swoich klientów: `GET /api/my-clients/{id}/settlements`
      (sekcja Delivery, bo DL nie ma modułu Finanse) zwraca „Do faktury dla
      klienta” z marżą w zł i % według `can_read_client_finance` i koszty
      integracji do decyzji (`…/integration-costs/{id}/approve|reject`). Na ekranie:
      Klient → Faktury → „Rozliczenie miesiąca i marża”. Wyłączony moduł = 404.
    - Panel konsultanta: w trwającym miesiącu z `cl.estimate` przycisk „Wyślij plan”
      (pole `plan` w wierszu miesiąca), a przyjęty plan nie otwiera „Wyślij fakturę”
      przed RCP za cały miesiąc (decyzja z 10.11).

### E6. Kolejni klienci (każdy po odpowiedziach z E0.3)

Odpowiedzi z E0.3 (12.11) dla Alior, Bosch, Velo i PKO są w katalogu reguł
z etapem E6: sekcja „Zapłata kontraktorowi” (`pay.*`), `proof.accept_has_hours`,
`fields.md_month_limit`, `travel.extra_costs_confirm` i w „Fakturze do klienta”
`cl.extra_costs_on_invoice`, `cl.client_document`, `cl.after_signed_document`,
`cl.send_to`. Finanse mogą je ustawić; silnik zacznie je sprawdzać w kolejnych
krokach E6.

- E6.1 PKO: dowód od konsultanta (TS i plik HTML akceptacji), ten sam silnik
  (najbliżej BNP).
  - Odczyt TS: miesiąc z widocznego nagłówka „Liczba godzin realizacji usług
    <miesiąc>”. Ten sam miesiąc stoi też w ukrytej kolumnie D (wiersze 16–18)
    i w próbce był inny niż w nagłówku: parser bierze nagłówek i ostrzega
    o rozbieżności z ukrytą kolumną, nigdy odwrotnie.
  - Akceptacja: plik HTML z liczbą godzin/MD za rozliczany miesiąc
    (`proof.accept_has_hours`); akceptujący nie musi być koordynatorem.
  - Kontrola MD z zamówienia (numer zamówienia z `client_orders.title`).
  - Wychodzące: jeden protokół odbioru na wszystkie osoby miesiąca (podpis
    spółki, potem klienta), paczka protokół + TS + HTML na adres z `cl.send_to`
    dopiero, gdy wszystkie osoby są gotowe; faktura do klienta po podpisanym
    protokole.
- E6.2 Velo, Bosch: dokumenty wychodzące generowane z NEXUS-a, godziny zamiast MD.
  - Velo: arkusz do podpisu klienta per osoba, każdy do pobrania osobno;
    zapłata konsultanta po jego podpisanym arkuszu (`pay.per_person`), faktura
    do klienta po podpisanych arkuszach zbiorczych; `fields.md_month_limit`
    „Ostrzega”. Arkusze od koordynatorów przypisuje NEXUS po osobie, nie po
    nadawcy maila (do czasu tego kroku: karta do ręcznego przypisania).
  - Bosch: SDC per projekt od listopada 2026 (Task ID z TS konsultanta), jedna
    osoba może mieć dwa projekty i jedną fakturę za całość,
    `fields.md_month_limit` wyłączona, wszystkie osoby z jednego zamówienia.
  - **Bosch w NEXUS-ie do 08.12.2026** (decyzja Artura z 12.11.2026): odczyt TS
    Boscha, generator SDC i estymacja grudnia, żeby listopad i grudzień dwóch
    osób rozliczyć w NEXUS-ie do 08.12. Osobne zadanie (osobna sesja i PR), nie
    część wspólnego PR-a E1–E5.
  - Jak zrobione (12.11, osobny PR, bez migracji):
    - Odczyt Time Sheet (`client_settlements/timesheet.py`): XLSX z tabelą
      „Date · Project · Description · Total Hours · Billable · Non-billable ·
      Nr strumienia”, każda tabela z każdego widocznego arkusza (tygodnie).
      Godziny = „Billable”, bez niej „Total Hours” − „Non-billable”; MD = godziny
      / `fields.md_hours`. Projekt z wiersza, bez niego z „Project Name”. Plik
      spoza szablonu RCP BNP idzie do tego odczytu, inny plik = MD od Finansów.
      Kontrole: miesiąc, wpisy spoza miesiąca, nazwisko z „Consultant(s)”,
      suma „Total Hours” = suma wierszy, limit dnia, `fields.md_month_limit`
      (dni robocze), mail z akceptacją przy `proof.excel_with_mail`.
    - Potwierdzenie usług (`service_confirmation.py`): reguła
      `cl.client_document` z `per` = „projekt” i `from` (Bosch: 2026-11). Jeden
      PDF na projekt z Time Sheet osób miesiąca: Supplier, Customer, Project
      Name, Date, Order Number, Stage, „Tasks List” (Task ID = „Nr strumienia”,
      bez niego liczba godzin jak w dokumencie za październik), TOTAL MDs. Bez
      nazwisk i bez autora w metadanych. Miesiąc z planem (estymacja) = etap
      FORECAST z planu. Lista na „RCP i faktury kontraktorów” nad tabelą
      (projekt, osoby, godziny, MD, „PDF”), bez kwot: kwota do klienta z limitem
      puli zamówienia jest tylko w „Do faktury dla klienta”. Osoby bez Time
      Sheet w Excelu albo z RCP do poprawy są wypisane pod listą.
    - Faktura do klienta w walucie zamówienia: linia ze stawką klienta w innej
      walucie niż zł i stawką dzienną daje pozycje po `rate_client` (Bosch:
      EUR/MD); marża zostaje w zł po kursie z linii (`md_rate_revenue` /
      `rate_client`). Tak samo „Plan miesiąca” (dwie faktury: listopad, plan
      grudnia). Linie w zł bez zmian.
    - Estymacja grudnia: bez zmian w mechanizmie E5.3 (`cl.estimate`, miesiąc 12),
      plan to Time Sheet z godzinami wysłany przed końcem grudnia.
    - Reguły Boscha ustawiają Finanse w „Reguły klienta” (dane, nie kod):
      `fields.md_month_limit` wyłączona, `cl.estimate` 12, `cl.client_document`
      (Service Delivery Confirmation, projekt, 2026-11), `proof.excel_with_mail`
      wyłączona (akceptacja per projekt z ESP sprawdza człowiek).
    - Blok maila ESP-MANAGER (12.11, osobny PR): reguła `cl.cost_mail_block`
      z parametrem `vendor` (puste = nazwa spółki z SDC). Przy liście SDC
      „Kopiuj blok ESP” per projekt: Stage (ACTUAL, przy planie FORECAST jak
      SDC), Project, PO (numer zamówienia grupy), Month, Vendor, MD, „Cost net
      <waluta>”, pusty Comment. MD i kwota z pozycji faktury do klienta
      (`client_invoice.positions`: limit puli, waluta linii), osoba w kilku
      projektach dzieli się w proporcji godzin z Time Sheet, reszta z zaokrągleń
      w ostatnim projekcie osoby. Korekta planu zostaje na fakturze, w bloku jej
      nie ma. Blok gotowy po przyjęciu wszystkich osób projektu, z numerem
      zamówienia i stawką klienta; kwota i tekst tylko dla `has_financial_access`.
    - Zostaje: etap INVOICE bloku (Ref-ID z odpowiedzi „Approved”, numer
      faktury; wymaga czytnika rozliczenia@), odczyt odpowiedzi „Approved”, Time Sheet w PDF (dziś MD od Finansów), projekt dla
      dwóch osób z akceptacją mailową (z Time Sheet, gdy konsultant go wpisze).
- E6.3 Alior, Orlen, CeZ: dokument na wiele osób, podpis klienta i spółki,
  protokół jako warunek faktury.
  - Alior: zapłata po podpisanym KEŚU (`pay.after_client_signature`), awaryjnie
    po mailowej akceptacji z późniejszym sprawdzeniem KEŚU
    (`pay.mail_accept_fallback`); kto podpisał KEŚU, nie sprawdzamy. KEŚU
    przychodzi od koordynatora (z Jiry), więc trafia jako karta do
    przypisania. Koszty dodatkowe na fakturze głównej
    (`cl.extra_costs_on_invoice`). Oświadczeń o własnym transporcie nie
    przyjmujemy do NEXUS-a; panel nie pokazuje jazdy własnym autem.
  - Jak zrobione (13.11, osobny PR, bez migracji):
    - Czytnik rozliczenia@: mail z Jiry („Rozliczenie kontraktora <osoba> za
      miesiąc MM-RRRR”) i odpowiedź „KEŚU <miesiąc> - <osoba>” przypisuje do
      kontraktu po imieniu i nazwisku z tematu, nie po nadawcy (koordynator,
      opiekun klienta). Jedna pasująca osoba = przypisanie, inaczej karta do
      ręcznego przypisania; w pilotażu tylko osoby z pilotażu
      (`identity.resolve_by_name`). Mail z Jiry zapisuje się też cały (EML
      z Graph `$value`), bo treść ma opiekuna i czas akceptacji. Załączniki
      „oświadczenie … transport/samochód” są pomijane. Ręczne przypisanie
      dokumentu przelicza rozliczenie tak samo jak czytnik.
    - Plik `.xls` z Jiry to XML Spreadsheet 2003 (zdublowany nagłówek XML,
      niezamienione `&`): `client_settlements/kesu.py` czyta go sam (typ
      `application/vnd.ms-excel`), MSG bez nowej zależności
      (`client_settlements/mail_file.py`, czytnik kontenera OLE), EML z biblioteki
      standardowej. MD = godziny z dni / `fields.md_hours`.
    - Stawka MD do KEŚU: stawka klienta z kontraktu (godzinowa × godziny MD,
      dzienna wprost, tylko zł). „Razem w PLN BRUTTO” = stawka MD / godziny MD
      × 1,23 × godziny + „Suma kosztów dodatkowych”, jak formuły w pliku klienta.
      Różnicę ze stawką linii zamówienia karta pokazuje tylko, gdy jest.
      Na dwóch prawdziwych KEŚU za październik (jedno z noclegiem) kwota
      zgadza się co do grosza z podpisanym KEŚU, a MD × stawka kosztowa
      z fakturą kontraktora (sprawdzone na próbkach; w testach w repo stawki
      są fikcyjne, a pliki KEŚU zanonimizowane).
    - Karta osoby („KEŚU z Jiry”): opiekun i czas akceptacji, godziny i dni,
      stawka i „Razem brutto” (kwoty tylko z dostępem do kwot), „Paczka do
      podpisu (PDF)” = KEŚU ze stawką i faktury kosztów z maila z Jiry w jednym
      pliku (pyHanko), „Mail do opiekuna” = adres opiekuna z linii „To:” maila
      z Jiry, temat i treść ze wzoru rozliczeń. Na liście: stan KEŚU przy RCP
      i pasek „Do podpisu spółki / Czeka na podpis klienta / Oba podpisy”.
    - Podpisy: dwa ważne podpisy w odesłanym PDF = podpisane, jeden = „Czeka na
      podpis klienta”; kto podpisał, nie sprawdzamy. Podpisany plik po
      przyjęciu odświeża sam stan KEŚU, bez zmiany przyjętych MD i kwot.
    - `cl.after_signed_document`: „Do faktury dla klienta” dopiero po podpisie
      klienta (stan `awaiting_signature`). `pay.after_client_signature`:
      w „Fakturze kontraktora” kontrola zapłaty; `pay.mail_accept_fallback`:
      przycisk „Podpisujący nieobecny” zapisuje zapłatę po mailowej akceptacji
      (w danych rozliczenia, przeżywa przeliczenie), podpisane KEŚU zostaje do
      sprawdzenia. `cl.extra_costs_on_invoice`: koszty z KEŚU na fakturze
      głównej, netto = brutto / 1,23 (brutto faktury = „Razem” z KEŚU); pusty
      parametr = jedna pozycja na całość, nazwa = osobna pozycja.
      `travel.extra_costs_confirm`: koszty dodatkowe zawsze tylko ostrzegają.
      Te pięć reguł ma etap E6.3.
    - Reguły Aliora ustawiają Finanse w „Reguły klienta” (dane, nie kod):
      `pay.after_client_signature` „Blokuje”, `pay.mail_accept_fallback`
      „Ostrzega”, `cl.after_signed_document` „Blokuje”,
      `cl.extra_costs_on_invoice` (pozycja według decyzji rozliczeń).
    - Zostaje: limity delegacji (hotel do 340 zł, pociąg 2. klasa) jako reguły,
      zadanie dla konsultanta „dodatkowa faktura na koszty”, netto kosztów
      dodatkowych do potwierdzenia przez rozliczenia (przyjęte brutto / 1,23).
  - Orlen, CeZ: czekają na odpowiedzi z E0.3.
- E6.4 Nordea (293 osoby): plan N1–N4 i stan w `docs/rozliczenia-nordea-plan.md`.
  N1 (13.11, osobny PR z migracją 0689): kartoteka numerów osób i NIDS z faktur
  do klienta w KSeF, wersje raportu T4T, status osoby w miesiącu (raport ×
  faktura kontraktora, godziny = netto ÷ stawka), ekran „Raport klienta (T4T)”
  za regułą `report.time_for_teams`.
- **Meta per klient:** reguły ustawione w „Reguły klienta”, jeden pełny miesiąc
  na stagingu, akceptacja autora instrukcji.

### E8. Jedna skrzynka wsparcie@ (decyzja Artura z 09.11.2026)

Cel: wszystkie maile i tickety wchodzą przez `wsparcie@b2bnetwork.pl`;
rozliczenia@, administracja@ i inne adresy wsparcia najpierw się z nią łączą,
potem są wygaszane. Dziś NEXUS ma trzy osobne skrzynki z osobnymi czytnikami:
`ADMIN_CASES_MAILBOX` (administracja@ → sprawy, `tasks/hr_loops.py:96`),
`CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` (rozliczenia@ → `cp_documents`)
i `CONSULTANT_PORTAL_MAILBOX` (wsparcie@: nadawca linków i organizator rozmów).

- E8.1 M365: rozliczenia@ i administracja@ jako aliasy albo przekierowania do
  wsparcie@, z zachowaniem pierwotnego odbiorcy w nagłówkach (bez kodu, robi Artur).
- E8.2 Jeden czytnik wsparcie@ z jednym znacznikiem i routerem: załącznik
  RCP/faktury od nadawcy z kontraktem albo mail na dawny adres rozliczeń →
  dokument rozliczenia (`documents.store`); reszta → sprawa w back office.
  Dwa czytniki na tej samej skrzynce przetworzyłyby każdy mail dwa razy, więc
  stare czytniki wyłączamy w tym samym kroku.
- E8.3 Wygaszenie: szablony umów B2B (`templates/contract/umowa_b2b_pl.html:125`,
  `umowa_b2b_en.html:126`) i treści w panelu, mailach i przewodnikach wskazują
  wsparcie@; autoodpowiedź na starych adresach; wyłączenie po okresie przejścia.
- **Meta:** mail wysłany na każdy stary adres ląduje jako jedna sprawa albo jeden
  dokument w NEXUS-ie; brak wzmianek o starych adresach w szablonach i ekranach.

### E7. Start na produkcji

- **Decyzja Artura z 12.11.2026: „Wszyscy klienci od listopada”.** Czytnik
  rozliczenia@ i panel konsultanta w stanie `all` od rozliczenia listopada.
  Kontrole działają tylko u BNP; u pozostałych klientów NEXUS zbiera pliki,
  a dokumenty od koordynatorów (Velo, Alior) trafiają jako karty do ręcznego
  przypisania. To odejście od kolejności E7.1 (pilot BNP w stanie `pilot`).
  Kroki:
  1. Artur w M365: rejestracja „NEXUS Kadry” dostaje Application Mail.Read na
     skrzynkę, do której trafia rozliczenia@ — wzór
     `docs/claude/ludzie/jedna-skrzynka-wsparcie.md` §1c z adresem rozliczenia@
     zamiast wsparcie@, po ustaleniu w §1a, gdzie ta skrzynka fizycznie jest.
  2. `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` przez workflow „Coolify set env”,
     wejście przy wdrożeniu w oknie.
  3. Admin w Ustawieniach: moduł `back_office` i moduł rozliczeń włączone,
     panel konsultanta `all`.
  - Związek z E8: do czasu routera E8 na tę skrzynkę patrzy tylko czytnik
    rozliczeń — czytnik spraw (`ADMIN_CASES_M365_MAILBOX`) nie może wskazywać
    tej samej skrzynki, bo każdy mail stałby się i sprawą, i dokumentem
    (ryzyko opisane w `jedna-skrzynka-wsparcie.md` §2). Jeśli rozliczenia@
    już wpada do wsparcie@, tamtejszy „bezpieczny stan przejściowy” (pusta
    zmienna czytnika rozliczeń) trzeba zmienić razem z tym krokiem.
- E7.1 Pilot: moduł włączony dla BNP, panel w stanie `pilot` dla kilku osób,
  mail na `rozliczenia@` dla reszty.
- E7.2 Kontrole przenoszone stopniowo z „Ostrzega” na „Blokuje” po miesiącu bez fałszywych alarmów.
- E7.3 Raport sprawdzający po pierwszym miesiącu (ile RCP przeszło bez uwag,
  ile ręcznych poprawek, czas od wpływu do przyjęcia).

## Makiety

Dwa źródła, oba z danymi tylko poza repo:

1. **Makiety E1 na kodzie gałęzi** (09.11): zakładka „Rozliczenia” w `/finance`
   (`components/finance/settlements/`), wołająca API z E1.3. Na zrzutach odpowiedzi
   `/api/finance/settlements*` podstawia skrypt z `~/NEXUS-rozliczenia-makiety/`:
   `scripts/gen_e1.py` (BNP, październik 2026, z kopii produkcji) i
   `scripts/e1_shots.cjs` (Playwright, 1280 × 720, konto Finansów stagingu).
   Zrzuty: `shots/e1-*.png`. Gdy backend E1 działa, te same ekrany idą na
   prawdziwym API, a skrypt służy już tylko do porównania.
2. **Makiety całości** w prywatnym artefakcie Artura (zakładki `przeglad`,
   `uwagi`, `bnp`, klienci) i ich kod w `~/NEXUS-rozliczenia-makiety/kod-makiet/`.

| Ekran | Gdzie | Etap | Makieta |
|---|---|---|---|
| Lista miesiąca klienta | `/finance?view=settlements` | E1.6 | kod gałęzi, `e1-lista.png` |
| Karta osoby (kontrole, wyliczenie) | ta sama zakładka, `stContract=` | E1.6, E2 | kod gałęzi, `e1-karta.png` |
| Reguły klienta | ta sama zakładka, `stSub=rules` | E1.6 | kod gałęzi, `e1-reguly.png` |
| Panel konsultanta: rozliczenia | `/konsultant/rozliczenia`, `/konsultant/faktury` | E3 | artefakt, `kod-makiet/.../konsultant/makieta` |
| Do faktury dla klienta | podzakładka w „Rozliczeniach” | E5.1 | artefakt (`?widok=bnp`) |
| Listopad i plan grudnia | podzakładka w „Rozliczeniach” | E5.4 | artefakt, `kod-makiet/.../estymacja` |
| Ekrany klientów (lista, panel, reguły) | jak wyżej, z regułami klienta | E6 | artefakt, zakładki klientów |

## Stan etapów

| Etap | Stan | Dowód |
|---|---|---|
| E0 | w toku: E0.1 rozstrzygnięte (NIP z KSeF w E4.0), E0.2 odpowiedzi BNP (10.11), E0.3 Alior, Bosch, Velo, PKO (12.11), CeZ i Orlen czekają; E0.4 instrukcja w osobnej sesji | odpowiedzi w E0.2 i E0.3, reguły E6 w `rules_catalog.py` |
| E1 | gotowe lokalnie (09.11), czeka na wspólny PR z E2–E5 | 22 testy BE (silnik, katalog, serwis na kopii z 09.11), 331 FE; ścieżka na kopii BNP październik: przyjęcie zdejmuje MD, ponowne nadpisuje, brak MD odmawia; zrzuty `e1r-*.png` |
| E2 | gotowe (09.11), E2.3 data i domena maila 13.11 | E2.3: próbki BNP `.msg` (łańcuch FW) i PDF z wydrukiem odczytane — zgoda z domeny banku z właściwą datą; na stagingu prawdziwe RCP z podpisem + `.msg` osoby z nadgodzinami: „Akceptacja z domeny bnpparibas.pl” i uwaga „Akceptacja z 02.11.2026, po pracy dodatkowej”; 12 testów bez bazy (`.eml`, `.msg` z kontenera OLE, daty w 5 układach, domena bez poddomen, przed/po/ten sam dzień). Wcześniej: 3 prawdziwe RCP z `BNP.zip` (2 PDF z podpisem, 1 XLSX) odczytane przez `documents.store`; osoba z nadgodzinami: MD z RCP × stawka = kwota z jej faktury; z mailami „Bez uwag”, przyjęcie zbiorcze zdjęło MD; 40 testów rozliczeń + 156 portalu |
| E3 | gotowe lokalnie (10.11), styl A bez kroków; E3.2 dane do skopiowania dokończone z E4 | panel jako konsultant BNP na kopii: „Do zrobienia” = „Wyślij fakturę · <kwota> netto”, „Faktury” z wynikiem sprawdzenia i danymi do faktury, 1280 i 390 px; 200 testów BE (portal + rozliczenia), 349 FE; zrzuty `e3-*.png` |
| E4 | gotowe lokalnie (10.11) | 3 prawdziwe faktury konsultantów BNP za październik (wizualizacje KSeF z próbek, metadane odtworzone lokalnie) przypięte po imieniu i nazwisku do właściwych osób i miesiąca, kwoty = wyliczenie co do grosza (3 z 3); zatwierdzenie NIP-u przez API zmienia stan na „W KSeF”; panel konsultanta i karta Finansów przeklikane 1280 i 390 px; 9 testów BE E4, 8 FE; prawdziwego pobrania z KSeF lokalnie nie ma (token tylko na produkcji) |
| E5 | gotowe (10.11), marża dla DL-a, koszty integracji i „Wyślij plan” 13.11 | 13.11: 6 testów na bazie (limit roku, drugi koszt ponad limit, koniec roku, obniżony limit przy zgodzie, odmowa bez zgody DL-a, marża DL-a przez API i 403 dla obcego DL-a), wzorzec authz z 6 trasami; staging na kopii z 09.11 (13.11, 1280 × 720): Finanse wpisują 1 500 zł osobie BNP za październik („czeka”), drugi koszt 600 zł odmówiony („zostało 500 zł z 2 000 zł”), DL BNP widzi marżę w zł i % i daje zgodę → marża tej osoby z 8,8% na 5,2%, na liście Finansów „w tym −1 500 zł integracja”; konsultant w trwającym listopadzie z planem widzi „Wyślij plan”. Wcześniej: kopia BNP październik: pozycje dla 2 osób z prawdziwym RCP = faktury w KSeF co do nazwy, ilości, ceny i netto (2 z 2); osoba z nadgodzinami w tym samym układzie co jej wrześniowa faktura (pozycja zasadnicza i `_nadgodziny`); zip z RCP i mailem; plan listopada „Ponad pulę o 10,2 MD”; 7 testów BE E5, 2 FE; zrzuty `e5-*.png` |
| E6 | reguły Alior, Bosch, Velo, PKO w katalogu (12.11, silnik ich nie sprawdza); Bosch E6.2 w osobnym PR-ze (12.11: odczyt Time Sheet, SDC per projekt, faktura w EUR, estymacja grudnia na E5.3); CeZ, Orlen czekają na E0.3 | testy katalogu: reguły E6 z `stage == "E6"`, koszty dodatkowe nie blokują; Bosch: 13 testów BE bez bazy, 2 na bazie (Time Sheet → faktura w EUR → SDC, plan → FORECAST), 4 FE; staging z kopii 10.11 (12.11): listopad 6 osób z syntetycznych Time Sheet, MD × stawka klienta w EUR równe kwocie z bloku ESP za październik (próbka), SDC bez autora i nazwisk, plan grudnia jednej osoby 16 MD → faktura z planu; druga osoba „Brak MD”, bo nowa linia zamówienia jest w szkicu (dane, nie kod) |
| E7 | decyzja 12.11: wszyscy klienci od listopada (panel `all`, kontrole tylko BNP); czeka M365, zmienna skrzynki i włączenie modułów | — |
| E8 | do zrobienia (E8.1 po instrukcji z osobnej sesji) | — |
