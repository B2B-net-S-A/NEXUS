# Bot Listy: listy do dzwonienia z briefu kampanii — decyzje Artura 13.11.2026
<!-- indeks: Bot Listy, brief kampanii bot_brief (0690), Zbuduj listę, dosypka w poniedziałek 7:00 zawsze do pełnej paczki, Co działa po roli i źródle, rola Manager/Lead przed zarządem, kolejność ról z wyników, bramki importu listy, baza NEXUSA jako pierwsze źródło, rejestr.io w Grok Bocie (L3), NIP i KRS do bota, plan Biznes, podobne firmy (L4), SALES_BOT_LISTS_ENABLED, /api/sales/bot-lists -->

Artur 13.11.2026 zapytał o bota, który przygotowuje listy pod cold calle z wybranymi
kampaniami. Raport z makietami: https://claude.ai/artifact/2Hxqi6uLTSE4AYp1GPqtpV
(sekcja „Piąty bot: Bot Listy”). Decyzje: budować L1–L4, NIP i KRS firm mogą iść do
bota, plan rejestr.io Biznes (wykupuje Artur), dosypka zawsze.

**Zmienia** regułę „Import listy: to nie jest silnik leadów” z
`dzwonienie-kampanie-i-import-listy.md`: listę może teraz złożyć Bot Listy z briefu.
Import pliku zostaje bez zmian.

## Dlaczego tak (kopia produkcji z 13.11.2026)

- Jedyna kampania „BE Leady”: 1 696 rekordów z jednego Excela, 30 spotkań (1,8%).
- Skuteczność po roli: Manager/Lead 2,9% (15 z 517), CTO/CIO 1,4% (8 z 562),
  zarząd 0% (0 z 131). Domyślne role briefu: Manager/Lead i Head/Director.
- 7 251 firm bez telefonu z kolejki i bez otwartej szansy, 435 z osobą Manager/Head/Lead
  z telefonem; branżę albo wielkość ma 113 z nich, więc segment po PKD i wielkości
  daje dopiero rejestr.io (L3) i Dane firm.

## Brief i budowa (L1, `services/sales/bot_lists.py`)

- **Brief** w `sales_call_campaigns.bot_brief` (0690, lustro w `entrypoint.sh`,
  `sales_schema.BOT_LISTS_DDL`), model `bot_lists.Brief` (`extra="forbid"`): role,
  słowa branży, miasta siedziby (`cities`), wielkości (`1-49`…`1000+`), PKD i województwa
  (dla L3),
  wyzwalacze, źródła, `include_unknown` (domyślnie tak: karty bez danych też wchodzą),
  paczka na osobę tygodniowo (5–200, domyślnie 40), osoby dzwoniące (aktywne konta),
  `auto_refill`.
- **Kandydaci z bazy:** kontakt z telefonem i stanowiskiem, bez sprzeciwu, w firmie
  bez archiwum, nie klient NEXUSA, nie „Nie kontaktować”, bez otwartej szansy i bez
  rekordu dzwonienia z ostatnich 183 dni (także „Nie zainteresowany — nigdy”). Jedna
  osoba na firmę, w kolejności ról.
- **Kolejność ról z wyników** (`role_order`): skuteczność spotkań wszystkich kampanii,
  wygładzona (30 rozmów po 2%), żeby rola bez historii nie wygrała przypadkiem.
- **Zapis od razu przez bramki importu** (`calling_import.apply_import`): klient
  NEXUSA, sprzeciw, rekord w kampanii, cudzy rekord, NIP już wczytany, brak telefonu.
  Pole „Skąd kontakt” to „Bot Listy · baza NEXUSA”, notatka „Bot Listy: rola · branża
  · miasto”. Podział między osoby proporcjonalnie do brakującej paczki.
- **Paczka:** każdej osobie do poziomu `per_caller` nowych rekordów w tej kampanii;
  przy pełnej paczce budowa nic nie dodaje.

## Dosypka i „Co działa” (L2)

- Poniedziałek od 7:00 (kalendarz firmy) w pętli `tasks/sales_signals.py`
  (`bot_lists.refill_due`, `refill_campaigns`), raz w tygodniu (`bot_built_at`),
  kampanie z briefem i `auto_refill`. **Zawsze**, także gdy osoba ma zaległe
  oddzwonienia (decyzja Artura). Na stagingu pętla stoi.
- „Co działa” (`GET /api/sales/bot-lists/campaigns/{id}`): rozmowy z wynikiem po roli
  i po „Skąd kontakt”, spotkania i skuteczność.

## API i ekran

- `GET /campaigns/{id}` („Sprzedaż: podgląd”), `PUT /campaigns/{id}/brief` i
  `POST /campaigns/{id}/build` („Sprzedaż: edycja”, limity 30 i 10 na minutę).
  Wyłączony `SALES_BOT_LISTS_ENABLED` (domyślnie włączony, bo bez bota i webhooka):
  zapis i budowa 409, odczyt `enabled: false`.
- Dzwonienie → Kampanie → „Bot Listy” przy kampanii (`calling/BotListPanel.tsx`):
  brief, „Zbuduj listę”, „Co działa”. Bot Listy jest też na ekranie Leady → Boty.

## L3–L4: rejestr.io, research i podobne firmy (rodzaj biegu `lists`)

- **Kiedy:** „Zbuduj listę” i poniedziałkowa dosypka najpierw biorą bazę, a gdy brief
  ma źródło `rejestr` albo `research` i paczka nie jest pełna, zlecają botowi brakujące
  firmy (`bot_lists.start_external`, najwyżej 50, jeden bieg na kampanię na 2 godziny).
  Tylko przy `SALES_BOT_TASKS_ENABLED` (jak inne zadania bota). Bot: Bot Listy, webhook
  `GROK_BOT_LISTS_WEBHOOK_URL/_KEY`, bez własnego wspólny (`cztery-boty-sprzedazy.md`).
- **Zlecenie** (`bot_tasks/lists.py`, `ListsRequest`, każde pole z uzasadnieniem
  w module): numer kampanii (dla NEXUSA), PKD, województwa, wielkość, wyzwalacze,
  stanowiska, liczba firm, NIP-y firm dzwonionych w ostatnich 6 miesiącach (do
  pominięcia) i, przy „podobnych firmach” (L4, `lookalike`), do 10 firm z umówionym
  spotkaniem w tej kampanii (nazwa, NIP, domena, branża, miasto). Bez danych osób.
  **NIP i KRS firm mogą iść do bota** (decyzja Artura 13.11.2026; `signals.webhook_body`
  dokłada je też w `firms` innych rodzajów).
- **Raport** (`ListsReport`, `extra="forbid"`, do 50 firm): firma, NIP (zła suma = sam
  numer odpada), KRS, domena, strona, miasto, PKD, liczba osób, telefon i e-mail firmy
  **tylko z własnym źródłem** (bez źródła odpadają), osoba tylko z linkiem do
  opublikowanego źródła (zarząd w KRS, strona firmy), wyzwalacz z adresem i datą,
  `source` (`rejestr`/`research`) i `source_url`.
- **Zapis od razu** (`ingest_firms`): wiersze listy przez te same bramki importu,
  „Skąd kontakt” „Bot Listy · rejestr.io” albo „Bot Listy · research”, notatka z PKD,
  miastem, wielkością i wyzwalaczem. Osoba spoza ról briefu (np. prezes przy roli
  Manager) nie trafia do rekordu, zostaje telefon firmy. Podział do paczki osób jak w L1.
- **rejestr.io:** dostęp w rutynie ustawia Artur, na swoje ryzyko (decyzja z 13.11.2026).
  W NEXUSIE, kodzie, poleceniu i dokumentacji nie ma haseł ani instrukcji logowania.
  Regulamin rejestr.io (3.11.2026) dopuszcza automatyzację przez API, MCP i eksport
  (pkt 6.1); przy liczbach finansowych podpis „Źródło: rejestr.io” (pkt 7.2).
- **Ekran:** w briefie „Skąd firmy” (Baza NEXUSA, rejestr.io, Research); przy źródłach
  zewnętrznych pola PKD, województwa, wyzwalacze i „podobne firmy”. Miasta siedziby
  (`cities`) filtrują bazę, województwa (`regions`) idą do bota.

Testy: `backend/tests/test_sales_bot_lists_unit.py`, `test_sales_bot_lists_api.py`,
`frontend/src/components/sales/__tests__/sales-bot-lists.test.tsx`, a dla zmiany NIP-u
`test_sales_signals_unit.py` (`test_webhook_body_carries_company_ids_but_no_people`).
