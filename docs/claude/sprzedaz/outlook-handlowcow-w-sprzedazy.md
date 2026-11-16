# Outlook handlowców w Sprzedaży — bieżąca poczta i kalendarz (decyzja Artura 28.10.2026)
<!-- indeks: skrzynka handlowca bez dostępu do kandydatów, zakres skrzynki sales_ok, dopasowanie po kontakcie i domenie, deduplikacja internetMessageId/iCalUId, autor = pierwsza skrzynka, Mój dzień każdego uczestnika _in_own_calendar, odwołane spotkania, emails.web_link, przypięcie do szansy, szansa ze spotkania, bramka klienta -->

„Tak, jak w Atlasie”: maile i spotkania handlowca z kontaktami firm są
widoczne dla każdego z „Sprzedaż: podgląd” — na osi firmy i (przez
`with_company_mail`) na karcie szansy. Zastępuje to pozycję „synchronizacja
poczty i kalendarza M365 na żywo” z listy „Poza zakresem” w
`sprzedaz-w-nexusie-decyzje-i-reguly.md`.

## Kto podłącza skrzynkę

- Osoba z dostępem do kandydatów (jak dotąd) **albo** z „Sprzedaż: podgląd”
  (`services/m365/access.py`: `mailbox_scope` → `MailboxScope(candidates, sales)`).
  Role tylko do odczytu (Automatyzacje) dalej nie.
- Trasy `/api/microsoft365/authorize|connection|sync/trigger` mają bramkę
  `require_mailbox_owner`; `free-busy`, poczta kandydatów i wysyłka zostają
  przy bramce kandydatów. Status skrzynki mówi, dokąd idzie poczta
  (`mail_to_candidates`, `mail_to_sales`); w Sprzedaży pasek
  `SalesMailboxStatus`, powrót z logowania Microsoft do Sprzedaży
  (`lib/m365-return.ts`, tylko ścieżki `/sales`).
- **Skrzynka handlowca bez dostępu do kandydatów nigdy nie zasila kandydatów:**
  sync nie dopasowuje maili ani spotkań do kandydata i nie pobiera załączników
  (z nich `m365_cv_parse` zakłada kandydatów). `eligible_m365_owner`,
  `require_eligible_connection_owner` i `GraphClient` bez `sales_ok=True` są
  bramką kandydatów — `sales_ok=True` podają wyłącznie synchronizacja,
  subskrypcje Graph i ich odnawianie, wysyłka podsumowania spotkania do klienta
  (`services/sales/meeting_client_mail.py`, od 09.11.2026) oraz zaproszenie na
  przekazane spotkanie (`services/sales/handoff_invite.py`, decyzja Artura
  z 10.11.2026). Obie wysyłki idą ze skrzynki osoby, która klika, i odrzucają adresy
  z bazy kandydatów przed wywołaniem Graph. Nie dokładaj go nigdzie indziej.

## Dopasowanie do firmy (`services/sales/outlook_activities.py`)

- Tylko skrzynki z „Sprzedaż: podgląd” (handlowcy i admin). Skrzynka samego
  rekrutera nie zasila Sprzedaży.
- Adresy spoza firmy (`matcher.external_addresses`): najpierw kontakt
  sprzedaży (`sales_contacts.email`) → firma główna i bieżące powiązania
  z `sales_company_contacts`; potem domena firmy (`sales_companies.domain`,
  bywa zapisana jako adres strony — wyrażenie `COMPANY_DOMAIN_SQL` = indeks
  `ix_sales_companies_mail_domain`, zmieniaj oba naraz). Atlas po domenie nie
  dopasowywał; tu jest na życzenie Artura, ale bez darmowych skrzynek
  (`PUBLIC_EMAIL_DOMAINS`), a domena wspólna dla więcej niż
  `MAX_DOMAIN_COMPANIES` firm nie wskazuje firmy.
- Jedna aktywność na firmę (`email` / `meeting`, `opportunity_id` puste),
  treść = podgląd z Graphu, nie cały mail. Nie trafiają: mail z kategorią
  `M365_IGNORE_CATEGORY` (jedyny znacznik prywatności maila — Graph v1.0 nie
  ma `sensitivity` przy wiadomości, dodanie go do `$select` zepsułoby sync;
  Atlas też patrzył tylko na kategorie) i spotkanie prywatne/poufne
  (`sensitivity`). Oznaczone później znikają (tylko wiersze synchronizacji
  NEXUSA); przypięte do szansy zostają bez treści (sekcja o przypięciu niżej).
- **Korespondencja z kandydatem nie idzie na oś firmy** (przegląd
  bezpieczeństwa 28.10.2026): mail z `candidate_id` i spotkanie z kandydatem
  wśród uczestników — dla skrzynek z dostępem do kandydatów (admin), bo
  zespół Sprzedaży kandydatów nie widzi. Kandydat z adresem w domenie firmy
  sprzedaży trafiłby tam inaczej przez dopasowanie po domenie.

## Deduplikacja i odwołania

- Klucz jak w Atlasie: `internetMessageId` maila (`msgraph-mail`), `iCalUId`
  spotkania (`msgraph-event`) + firma. Historia z importu Atlasa
  (`external_ref`) zostaje — synchronizacja tylko uzupełnia jej luki
  (link, kierunek, czas). UNIQUE `ux_sales_activities_outlook` obejmuje
  wyłącznie wiersze bez `external_ref`, żeby nie wywrócić się na imporcie.
- `iCalUId` leży też w `calendar_events.m365_ical_uid`: `@removed` z Graphu
  niesie samo id wydarzenia. Odwołane / usunięte spotkanie znika z osi, tylko
  gdy jeszcze się nie odbyło i nie stoi w kalendarzu innej osoby z NEXUSA.
- **Autor aktywności to skrzynka, która zsynchronizowała spotkanie pierwsza**
  (`on_conflict_do_nothing` w `record`), i tak zostaje: po autorze liczą KPI
  i Skuteczność. „Mój dzień” pokazuje spotkanie każdemu uczestnikowi z NEXUSA,
  który ma je w swoim kalendarzu: kopia w `calendar_events` (`created_by` = właściciel
  skrzynki, ten sam `m365_ical_uid`, status inny niż `cancelled`) →
  `my_day._in_own_calendar`. Jeden wiersz na osobę i dzień, bez drugiej aktywności
  i bez migracji. Lista dzwoniących z 13.11.2026: prowadzący zaproszony przez
  dzwoniącego nie widział spotkania. Kto odrzucił albo usunął spotkanie u siebie, temu
  znika, a autorowi zostaje. Spotkanie bez dopasowanej firmy nie trafia do Sprzedaży
  ani do „Mojego dnia”, bo wiersz dnia to karta firmy.
- Zmiana `EVENT_SELECT` (0624: `iCalUId`, `webLink`) = nowy klucz
  `EVENT_SELECT_RESET_KEY` i jednorazowy pełny odczyt kalendarzy; kursorów
  poczty nie zerujemy — brak `webLink` w starej delcie zastępuje link
  zbudowany z id (`OWA_READ_ITEM_URL`). Raz na skrzynkę z „Sprzedaż: podgląd”
  synchronizacja przechodzi maile z ostatnich 30 dni już zapisane w NEXUSIE
  (`SALES_CATCH_UP_KEY`).

## Przypięcie do szansy i ekran Spotkania (09.11.2026)

Synchronizacja przypina aktywność do firmy. Do szansy przypina handlowiec
przy wierszu w Sprzedaż → Spotkania, bo przy kilku szansach tylko on wie, której
dotyczy spotkanie. Logika: `services/sales/meeting_decisions.py`, `client_gate.py`.
Od 10.11.2026 spotkanie firmy z jedną otwartą szansą przypina się samo
(`meeting_autopin.py`, reguły w `przekazanie-spotkania-i-werdykt.md`); „Cofnij
przypięcie” działa na nie tak samo i takie spotkanie nie przypina się ponownie.

- **Trasy** za `SalesEditUser`: `POST` i `DELETE /api/sales/activities/{id}/pin`
  (mail i spotkanie z Outlooka, otwarta szansa tej samej firmy) oraz
  `POST /api/sales/opportunities/from-activity/{id}` (tylko spotkanie).
  Odczyt `GET …/{id}/opportunity-draft` za `SalesViewUser`.
- **`last_activity_at` dostaje datę spotkania, nie kliknięcia**, i nigdy się nie
  cofa. Przyszłe spotkanie zmienia je dopiero, gdy się odbędzie: robi to `record()`,
  a spotkanie, które po prostu minęło, `settle_pinned_meetings` po każdym przebiegu
  skrzynki z dostępem do Sprzedaży, bo delta Graph nie oddaje czegoś, co się nie zmieniło.
- **Poprzednia data leży w historii** (`field = 'last_activity_at'`), bo przy
  części szans z Atlasa nie wynika z aktywności. Cofnięcie bierze późniejszą
  z poprzedniej daty i świeższej pracy przy szansie.
- **`record()` nie zdejmuje przypięcia.** `forget()` przy oznaczeniu jako prywatne
  nie kasuje wiersza przypiętego: czyści temat, treść i link, a transkrypt usuwa,
  żeby prywatne nie zostało widoczne. Odwołane przyszłe spotkanie znika także
  przypięte, bo się nie odbyło. Historia szansy (`field = 'outlook_activity'`) trzyma
  id aktywności, a temat czyta z wiersza, bo zapisany temat zostałby tam po
  oznaczeniu jako prywatne. Nie wpisuj do historii tematu ani treści z Outlooka.
- **Bramka klienta przy szansie ze spotkania:** firma powiązana z klientem albo
  o nazwie lub aliasie klienta (ta sama reguła co `is_existing_client`) dostaje
  409 z nazwą Delivery Leada. Pozostałe ścieżki zakładania szansy jej nie mają.
- **Nasza spółka to nie klient do przekazania.** Jest w `clients` (projekty
  wewnętrzne, bez Delivery Leada) i ma kartę w Sprzedaży (`OWN_COMPANY_KEY`), więc
  bez tego wyjątku spotkania przy niej dostawały fałszywe „zgłoś do Heada”. Wiersz ma
  stan „Spotkanie wewnętrzne”, a próba założenia szansy kończy się 409.
- **Firma w oknie jest tylko do odczytu,** bo przypiąć można wyłącznie do szansy
  firmy tej aktywności.
- **Lista:** jedno spotkanie to jeden wiersz (`external_id`), najpierw kopia
  przypięta, potem firma, przy której jest co zrobić (nie nasza spółka ani klient
  NEXUSA), a wśród nich ta z otwartą szansą. Para z importu Atlasa (nagranie przy
  szansie i wydarzenie z kalendarza o tej samej firmie, minucie i temacie) też
  jest jednym wierszem, inaczej spotkanie już przy szansie wisi w kolejce.
  Kolejność: dziś i 7 dni naprzód, przeszłe, dalsza przyszłość, bo tam lądują
  błędne daty. Podgląd notatki jest w dymku tematu, żeby przy 1280 × 720 weszło
  około 11 wierszy; podsumowanie transkryptu zostaje pod tematem.
- **„Przypisanie” i zakres dat są pod przyciskiem „Filtry”,** bo przy 1280 × 720
  nie mieszczą się w rzędzie z czterema przełącznikami.

Testy: `backend/tests/test_sales_outlook_sync.py`,
`backend/tests/test_sales_meeting_decisions.py`,
`frontend/src/components/sales/__tests__/sales-mailbox-status.test.ts`,
`frontend/src/components/sales/__tests__/sales-meetings.test.tsx`.
