# Outlook handlowców w Sprzedaży — bieżąca poczta i kalendarz (decyzja Artura 28.10.2026)
<!-- indeks: skrzynka handlowca bez dostępu do kandydatów, zakres skrzynki sales_ok, dopasowanie po kontakcie i domenie, deduplikacja internetMessageId/iCalUId, odwołane spotkania, emails.web_link -->

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
  subskrypcje Graph i ich odnawianie. Nie dokładaj go nigdzie indziej.

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
  NEXUSA).
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
- Zmiana `EVENT_SELECT` (0619: `iCalUId`, `webLink`) = nowy klucz
  `EVENT_SELECT_RESET_KEY` i jednorazowy pełny odczyt kalendarzy; kursorów
  poczty nie zerujemy — brak `webLink` w starej delcie zastępuje link
  zbudowany z id (`OWA_READ_ITEM_URL`). Raz na skrzynkę z „Sprzedaż: podgląd”
  synchronizacja przechodzi maile z ostatnich 30 dni już zapisane w NEXUSIE
  (`SALES_CATCH_UP_KEY`).

Testy: `backend/tests/test_sales_outlook_sync.py`,
`frontend/src/components/sales/__tests__/sales-mailbox-status.test.ts`.
