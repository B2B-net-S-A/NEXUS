# Sprzedaż: przekazanie spotkania, werdykt i tożsamość firmy (decyzje Artura 10.11.2026)
<!-- indeks: „Umów spotkanie”, szansa z umówionego spotkania, prowadzący = opiekun, autor szansy = źródło, custom_fields.handoff, „Przekazane do Ciebie”, potwierdzenie terminu, werdykt (kwalifikuje się / nie teraz / nie nasz klient / nie odbyło się), liczby tygodniowe bez celu, spotkanie przypina się samo, tożsamość firmy i domena, zaproszenie z Outlooka poza zakresem -->

Pakiet „Przekazanie i werdykt” (rekomendacje A3, A4, C1, C3):
https://claude.ai/artifact/PEfTGijHaxrPDZS2mkxKty. Stan sprzed zmiany, kopia
z 10.11: dwie osoby dzwoniące założyły w 3 dni robocze 94 szanse, w tym 30 ze
spotkaniem wstępnym; termin był tekstem w opisie, 14 spotkań nie miało daty,
żadna z 30 szans nie zmieniła opiekuna, a prowadzący od 26.10 nie przypiął
żadnego z 15 spotkań z kalendarza.

## Zasady, których nie cofamy

- **Szansa powstaje z umówionego spotkania.** „Oferta ogólna wysłana” to wynik
  rozmowy z datą oddzwonienia, nie szansa.
- **Moduł podpowiada, nie blokuje.** Brak terminu, osoby, usługi i odpowiedzi nie
  zatrzymuje zapisu. Potrzebna jest tylko firma i prowadzący. Kolizja w kalendarzu,
  podobna karta i brak domeny to ostrzeżenia.
- **Bez kontroli pracy.** Liczby tygodniowe (umówione → odbyte → zakwalifikowane)
  widzi tylko osoba, której dotyczą. Nie ma celu dziennego, paska postępu, rankingu
  ani przełącznika „pokaż osobę”; trasa list nie przyjmuje identyfikatora osoby.
- **Nic nie wychodzi samo do ludzi z zewnątrz.** „Potwierdź termin u klienta” daje
  numer i adres do kliknięcia, a potem zapisuje „Klient potwierdził”. Zaproszenie
  do klienta wysyła człowiek z Outlooka (sekcja „Zaproszenie” niżej).
- **Klient NEXUSA nie dostaje szansy** (409 z nazwą Delivery Leada, `client_gate`),
  także gdy ktoś wpisuje jego nazwę jako nową firmę. Nasza spółka też nie.

## „Umów spotkanie” (`services/sales/handoff.py`, `POST /api/sales/handoffs`)

- Zapis zakłada szansę w lejku `sales` na etapie `qualifying-meeting`:
  **opiekun = prowadzący**, **autor szansy (`created_by_user_id`) = osoba, która
  umówiła**. To pole jest znacznikiem źródła, nowej kolumny nie ma.
- **Stan przekazania leży w `custom_fields["handoff"]` szansy**, bez migracji
  (`handoff_state.py` opisuje klucze). Zapis trzyma blokadę wiersza szansy, bo to
  odczyt JSON-a, zmiana i nadpisanie. Każdy krok zostawia wiersz historii:
  `field = 'handoff'` (`booked`, `term`, `confirmed`) albo `'handoff_verdict'`
  (rodzaj werdyktu). W wartościach nie ma nazwisk ani treści odpowiedzi.
- **Termin jest też aktywnością `meeting` przy szansie**, żeby szansa miała krok
  (`next_step.py`), a odbyte spotkanie było dotykiem (`touch.py`) i liczyło się
  w KPI. Autorem tej aktywności jest prowadzący, jak przy synchronizacji
  kalendarza: po autorze „Mój dzień” wie, czyje to spotkanie.
- **Osoba zapisuje się jako kontakt firmy.** Osoba o tym samym imieniu i nazwisku
  albo mailu w tej firmie jest używana ponownie i dostaje tylko brakujące pola.
  Sprzeciw wobec kontaktu działa jak w kontaktach (409 przy numerze).
- **Własna szansa zamiast drugiej:** z `opportunity_id` formularz przekazuje
  istniejącą szansę (Lead przechodzi na „Spotkanie kwalifikujące”, dalszych etapów
  nie cofamy). Robi to jej opiekun albo admin; cudza szansa to 403. Tak wchodzi do
  procesu 28 otwartych szans ze spotkaniem, które dzwoniący mieli 10.11 u siebie.
  Gdy zmienia się przy tym opiekun, otwarte zadania poprzedniego przy tej szansie idą
  do prowadzącego (`owner_tasks.hand_over`, decyzja Artura 10.11.2026). Zadania
  przypisane komuś innemu niż poprzedni opiekun zostają na miejscu.
- **Prowadzący** to dowolne aktywne konto z „Sprzedaż: edycja” (`handoff_hosts.py`);
  roli „Handlowiec” nie ma. Formularz podpowiada tego z ostatniego przekazania.
- **Kalendarz prowadzącego** (`GET …/host-busy`) to wydarzenia zsynchronizowane
  z jego skrzynki (`calendar_events`) i spotkania zapisane w Sprzedaży: same
  przedziały, bez tytułów, tylko dla kont, którym można przekazać spotkanie. Bez
  połączonej skrzynki (`calendar: unavailable`) termin wpisuje się ręcznie. Nie
  dokładaj tu wywołania Graph ani `GraphClient(..., sales_ok=True)`.
- **Formularz jest samodzielnym komponentem** (`handoff/BookMeetingForm.tsx`,
  w oknie jako `BookMeetingDialog`): przyjmuje firmę, szansę, osobę i usługę
  z miejsca wywołania, więc zakładka „Dzwonienie” podpina go pod wynik rozmowy.

## „Przekazane do Ciebie” i werdykt (`handoff_views.py`, `GET /api/sales/handoffs`)

- **Faza liczy serwer** (`phase_of`): `no_term`, `upcoming`, `confirm` od
  poprzedniego dnia roboczego (poniedziałkowe spotkanie potwierdza się w piątek,
  święta z kalendarza firmy), `verdict` od godziny spotkania.
- **Werdykt daje opiekun szansy albo admin** (403 dla pozostałych, także dla osoby,
  która umówiła):
  - „Kwalifikuje się” → etap `qualified` (ustawia `qualified_at`, więc liczy się
    w KPI „Leady”); ekran od razu proponuje krok.
  - „Nie teraz” → zadanie dla opiekuna w dniu powrotu (bez daty za 30 dni)
    i `keep_open_until`, żeby automat archiwizacji nie uznał szansy za porzuconą.
  - „Nie nasz klient” → etap `not-qualified` z powodem (powód nie jest wymagany).
  - „Nie odbyło się” → zadanie dla osoby, która umówiła, na następny dzień
    roboczy; wpis terminu znika, bo spotkanie, które się nie odbyło, nie może być
    dotykiem ani spotkaniem w KPI. Ponowne umówienie tej samej szansy czyści werdykt.
- **Ruch po etapach ma te same skutki co `POST /move`** (`apply_stage` i historia).
  Front dalej rusza szansę tylko przez `/move` albo przez werdykt.
- **Termin zmienia** osoba, która umówiła, prowadzący albo admin; zmiana kasuje
  potwierdzenie. Termin z kalendarza (niżej) zmienia się w Outlooku (409).
- **Jedno spotkanie to jeden wiersz:** spotkanie szansy z „Przekazane do Ciebie”
  nie stoi drugi raz w „Spotkania dziś”.
- **Liczby tygodnia** liczą się z historii szans: umówienie w tygodniu zapisu,
  odbycie i kwalifikacja w tygodniu werdyktu.

## Spotkanie z kalendarza przypina się samo (`meeting_autopin.py`)

- Po każdym przebiegu skrzynki z dostępem do Sprzedaży automat przypina spotkanie
  z Outlooka, gdy **firma ma dokładnie jedną otwartą szansę**, a spotkanie nie jest
  starsze niż dzień jej założenia. Pomiar na kopii z 10.11: z 71 nieprzypiętych
  spotkań z Outlooka pierwszy przebieg przypiął 13, drugi 0; bez warunku daty
  kandydatów byłoby 30.
- Drugi sposób: spotkanie trafia w **termin przekazania** (15 minut). Wtedy
  wiadomo, której szansy dotyczy, także gdy firma ma ich kilka, a wpis terminu
  z formularza zastępuje spotkanie z kalendarza i odtąd termin czytamy z niego.
  Przekazanie bez terminu dostaje termin z takiego spotkania.
- **Poza automatem:** kilka otwartych szans bez pasującego terminu (wybór jak
  dotąd), nasza spółka, klient NEXUSA, wiersze z importu Atlasa i jedno
  wydarzenie, które wskazywałoby szanse w kilku firmach.
- **Da się odpiąć i odpięte nie wraca:** warunek to wiersz odpięcia tej aktywności
  w historii szansy. Przypięcie automatu ma puste `user_id`; po tym ekran pokazuje
  „samo” i „Odepnij”.
- **Brak szansy:** wiersz „Spotkania dziś” po „Po spotkaniu” proponuje „Załóż
  szansę” (`can_create_opportunity`), z istniejącą bramką klienta.

## Tożsamość firmy przy zakładaniu (`GET /api/sales/companies/identity`)

- Z 93 firm dotkniętych przez dzwoniących 56 było nowymi kartami, a domenę miało
  6, bo okno „Nowa firma” nie miało jej pola. Bez domeny nie działa dopasowanie
  poczty, kalendarza ani punkty z researchu.
- Trasa podpowiada **karty, które już mogą być tą firmą** (ta sama nazwa
  kanoniczna, ta sama domena, podobna nazwa; do 6, najpierw z otwartymi szansami)
  i **domenę**: najpierw z adresu strony, potem z maila osoby, nigdy z darmowej
  skrzynki (`PUBLIC_EMAIL_DOMAINS`).
- To podpowiedź w formularzu „Umów spotkanie” i w oknie „Nowa firma”. Zapis nie
  jest blokowany, a domena już wpisana na karcie nigdy nie jest nadpisywana.
- Karta bez domeny dostaje ją z adresu strony także przy zwykłym zapisie firmy.
- Nowa karta o nazwie istniejącej dostaje z formularza 409
  `sales_company_duplicate` z wyborem „Użyj tej karty” albo „Załóż mimo to”.

## Zaproszenie z Outlooka: poza tym pakietem

Zapis nie wysyła zaproszenia. Obecne uprawnienia Graph (delegowane
`Calendars.ReadWrite` połączonej skrzynki) technicznie na to pozwalają, ale
wymagałoby to nowego użycia `GraphClient(..., sales_ok=True)`, którego
`outlook-handlowcow-w-sprzedazy.md` zabrania poza trzema miejscami, oraz decyzji,
z czyjej skrzynki idzie zaproszenie do klienta: 10.11 skrzynkę miały połączoną
dwa z czterech kont Sprzedaży. Do decyzji Artura. Do tego czasu zaproszenie
wysyła człowiek, a gdy trafi do kalendarza prowadzącego, przypnie się samo.

Testy: `backend/tests/test_sales_handoff.py`, `test_sales_meeting_autopin.py`,
`test_sales_company_identity.py`,
`frontend/src/components/sales/__tests__/sales-handoff.test.tsx`, `my-day.test.tsx`.
