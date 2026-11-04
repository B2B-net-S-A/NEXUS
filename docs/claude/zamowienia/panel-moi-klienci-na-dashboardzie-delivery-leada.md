# Panel „Moi klienci" na dashboardzie Delivery Leada (09.2026, migracja 0310)

Sprawy zamówień i kontraktów klientów mają osobny kanał od „Moje zadania →
Powiadomienia". Widget „Moje zadania" na pulpicie **Delivery Leada**
(`recruitmentNotificationsOnly`) pyta `GET /api/notifications?exclude_section=delivery`
(filtr działa na listę **i** `unread_count`). Inne pulpity i dzwonek widzą
wszystko jak dotąd — nie mają panelu, a sekcja delivery obejmuje też podpisy
i zwroty sprzętu, dla których kart nie ma. Panel `MyClientsAlertsPanel` (`preset === "delivery-lead"`, zaraz pod
„Moje zadania") czyta `GET /api/dl-alerts/cards`. Migracja 0310 + lustro w `entrypoint.sh`.

- **Karta = sprawa = `dl_alerts.event_key`** (`{typ}:{encja}:{odbiorca}`,
  `dedupe_key` bez okna). Powtórki zostają osobnymi wierszami (raport), serwer
  składa je w kartę (priorytet = najwyższy w sprawie). `POST /{id}/handled`
  zamyka **wszystkie** otwarte wiersze sprawy i pisze `Activity`
  `dl_alert_handled` na zamówieniu/grupie/kontrakcie/dokumencie.
- **`stage` w `emit`** nazywa próg (`t14`, `t7`, `high`) zamiast numeru tygodnia;
  bez `stage` klucz zostaje numeryczny jak dotąd (stare klucze się nie zmieniają).
  `email=True` → `payload.email`, wysyła `send_pending_alert_emails` PO commicie
  skanu (claim + stempel jak w `job_deadline_alerts`, ponowne sprawdzenie odbiorcy).
- **`status='resolved'`** = przyczyna ustąpiła (przedłużenie, uzupełniony szkic,
  zweryfikowany mail) — `handled_by_user_id` pusty, to NIE odhaczenie DL. Każda
  reguła stanowa kończy się `resolve_stale(live_event_keys)`; `entity_prefix`
  zawęża, gdy typ ma kilka ścieżek emisji (`order:` vs `mail-draft:`). Resolve
  kończy EPIZOD wspólnym stemplem `episode_closed_at` na WSZYSTKICH wierszach
  sprawy — także odhaczonych. Bez stempla na odhaczonych sprawa odhaczona raz
  (np. pula MD) nie alarmowałaby już nigdy, nawet po uzupełnieniu i ponownym
  spadku. Powrót warunku alarmuje z prefiksem `e{n}` w kluczu (bez tego
  `ON CONFLICT` zdusiłby pierwsze przypomnienie). `_episode_state` porównuje
  stemple, nie `created_at` (dwa zegary). Odhaczenie blokuje sprawę do końca
  epizodu — **także etapy t14/t7/high** (ticket: „zatrzymuje dalsze
  przypomnienia"). Karta mail-review zamyka się od razu przy apply/dismiss.
- **Cykl datowy** (`date_cycle_stage`): okno 30 dni z ZAKRESU dat, nie równości
  (dzień bez skanera nie gubi progu) → **pierwszy wiersz sprawy = mail** → co 7
  dni bez maila → T-14 mail → T-7 high + mail.
  Encja niesie datę końca (`order:{id}:end:{data}`), więc przedłużenie = nowy cykl.
  Dotyczy zamówień okresowych (`order_group_id IS NULL`), umów ramowych
  i kontraktów (kontrakt, którego zamówienie okresowe kończy się tego samego
  dnia, nie dostaje drugiej karty).
- **Klienci z rozszerzonymi alertami zamówień: `EXTENDED_ORDER_ALERT_CLIENT_IDS`**
  (CSV, fail-closed, dziś BNP — `services/order_alert_policy.py`). Jedna lista,
  DWA niezależne sygnały o tym samym zamówieniu, nigdy łączone w jedną kartę
  (ticket 09.2026):
  1. **`rule_periodic_order_ending` obejmuje u nich także LINIE zamówień
     wielo-konsultantowych** (`or_(order_group_id IS NULL, client_id IN …)`
     + wymóg `ClientOrderGroup.status == active`). U pozostałych klientów te
     linie zostają pominięte, bo tam zamówienie kończy wyczerpanie budżetu, nie
     kalendarz. Dzwonek (`_scan_orders`) widział je od zawsze — linia dziedziczy
     `end_date` grupy — ale daje jeden sygnał na próg; maila przy pierwszym
     wierszu i powtórkę co 7 dni ma wyłącznie karta w panelu.
  2. **`md_base_usage_high`** — zużycie PODSTAWY MD (`md_total`) ≥
     `DL_ALERT_MD_BASE_USAGE_PERCENT` (80%), per konsultant. Zakres opcjonalny
     NIE wchodzi ani do licznika, ani do mianownika. Zużycie liczone z SUMY
     ZEJŚĆ (`client_order_md_consumptions`), nie z `md_remaining` — ta niesie też
     `md_manual_adjustment`, czyli korektę BUDŻETU, więc wyprowadzenie z niej
     przesunęłoby próg. Podział podstawa/opcja przez `split_md_usage` (te same
     liczby co paski `MdScopeBars`). **Bez eskalacji i bez maila** — wysoki
     priorytet ma `md_budget_low`; w paśmie, gdzie oba warunki są spełnione, DL
     widzi dwie karty i to jest zamierzone.
- **Dzwonek 30/14/7 (`_scan_orders`) i kafel pulpitu „kończy się w 30 dni”**
  wołają regułę z `include_date_closed_lines=True`: linie zamówień BEZ budżetu
  MD (kosztowe) liczą się u KAŻDEGO klienta, bo `_promote_statuses` domyka je
  datą. Karta w panelu DL ich nie obejmuje. Kontynuacją „do wyczerpania budżetu
  MD” jest wyłącznie linia zamówienia MD (`order_group_id IS NOT NULL`), nigdy
  samodzielne zamówienie okresowe z `md_total` (audyt 24.09.2026).
- **`DL_ALERT_MD_THRESHOLD=21` zostaje GLOBALNY i bezwzględny** — `md_base_usage_high`
  go nie zastępuje ani nie konfiguruje per klient. „Mało MD" ma znaczyć to samo
  w każdym raporcie (pilnuje `test_md_threshold_is_global_not_per_client`);
  próg procentowy to OSOBNY typ alertu i osobna karta, nie wariant tamtego.
- **Pusta lista = zero zmian dla wszystkich.** `client_id.in_(frozenset())` daje
  `IN ()` = fałsz, a `rule_md_base_usage_high` kończy się przed zapytaniem.
  Aktywacja na prodzie = jedna zmienna przez workflow „Coolify set env"; id
  ustala się NA PRODUKCJI (`/api/admin/client-mixups`), bo „BNP" to RODZINA
  rekordów klienta (oddział vs bank vs Cardif) i zaszycie `12` na ślepo mogłoby
  włączyć alerty złej spółce.
- **Miesięczne uprzedzenie mailem to `email_on_first` w `emit`, NIE etap `t30`**
  (09.2026, decyzja Artura: mail + dzwonek, progi 14/7 zostają). Mail idzie przy
  pierwszym wierszu sprawy — `first_seen is None`, liczone PER ODBIORCA, więc
  nowy DL przypisany w połowie okna dostaje swój pierwszy mail, a pozostali nie
  dostają drugiego. Osobny etap `t30` zjadłby powtórki tygodniowe w paśmie
  30→15 dni (etap i numer okna to ta sama pozycja `dedupe_key`), wysłałby zaraz
  po wdrożeniu mail każdej sprawie już wiszącej w oknie i **nie objąłby
  zamówienia wpisanego 20 dni przed końcem** — próg 30-dniowy już by minął.
  `date_cycle_stage` zostaje nietknięte.
- **Dzwonek (`dl_portal_expiry_scanner`) liczy progi z ZAKRESU, nie z równości**
  (09.2026). Do tej zmiany pytał `end_date == today + N` dla `N ∈ (30, 14, 7)`,
  więc jeden dzień bez biegu — albo zamówienie wpisane/przedłużone na mniej niż
  30 dni — gubił próg 30-dniowy BEZPOWROTNIE i pierwszy dzwonek wypadał na 14
  dni. Teraz `_threshold_bucket(days_left)` wybiera najciaśniejszy pasujący próg
  (jeden na encję na bieg), dedup po `_end_phrase` zostaje bez zmian, a zegar to
  `business_today()` jak w `_promote_statuses` (koniec rozjazdu UTC/Warszawa).
  Tytuł niesie FAKTYCZNĄ liczbę dni (`_lead_phrase`), bo próg 30 bywa wysłany
  przy 22 dniach; `message` nietknięty — to on jest kluczem dedupu.
  `contract_alerts` (90/60/30/14/7 na kontraktach) bez zmian.
- **MD** start `DL_ALERT_MD_THRESHOLD=21` (`<=`), **kosztowe** start
  `DL_ALERT_COST_BUDGET_THRESHOLD=10000` (treść bez kwot — panel widzą też
  hybrydy bez finansów). Wysoki priorytet + mail: pozostałość ≤ tempo ×
  `DL_ALERT_HIGH_PRIORITY_WORKDAYS` (7). Tempo liczy czysty
  `services/order_burn_rate.py`: suma miesięcznych raportów (MD albo
  `invoice_amount`) ÷ dni robocze (polskie święta) od startu zamówienia do końca
  ostatniego raportowanego miesiąca. MD bez raportów = szacunek 1 MD/dzień na
  osobę; kosztowe bez faktur = brak etapu `high`.
- **Nowy kontraktor**: `_ensure_open_order` (ścieżka podpisu z Generatora) emituje
  `new_contractor_draft` w savepoincie, fail-soft; skaner powtarza, dopóki brakuje
  stawki przychodowej / okresu / numeru (tytuł-zaślepka albo „Imię — rekrutacja").
  Takie szkice są WYŁĄCZONE z `draft_consultant_unassigned` (jedna karta, nie dwie).
- **`notify_review`** bierze odbiorców z `dl_user_ids_for_client` (rola + sekcja
  Delivery; wcześniej surowe przypisania), fallback admini zostaje; treść niesie
  klienta i osoby z odczytu.
- **Deep linki**: `?order=` (linia grupy → jej grupa, zamówienie okresowe → karta
  kontraktora, szkic → od razu „Uzupełnij zamówienie"), `?group=`, `?framework=`.
  Rozwiązuje `resolveOrderFocus` (`lib/client-order-list.ts`); zakładka zdejmuje
  filtry, przewija i podświetla, potem strona usuwa parametry z adresu. Cel
  niewidoczny = toast, nigdy cisza.
- **Harness `/preview/dl-alerts`** renderuje panel z `refetchIntervalMs={false}`
  i cache z `updatedAt` w przyszłości — zero zapytań (401 przerzuciłby na /login).
  Checkbox w harnessie woła API — nie klikaj go w podglądzie.
