# Bot Listy: listy do dzwonienia z briefu kampanii — decyzje Artura 13.11.2026
<!-- indeks: Bot Listy, brief kampanii bot_brief (0691), Zbuduj listę, dosypka w poniedziałek 7:00 zawsze do pełnej paczki, Co działa po roli i źródle, rola Manager/Lead przed zarządem, kolejność ról z wyników, bramki importu listy, baza NEXUSA jako pierwsze źródło, rejestr.io w Grok Bocie (L3), NIP i KRS do bota, plan Biznes, podobne firmy (L4), SALES_BOT_LISTS_ENABLED, /api/sales/bot-lists -->

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

- **Brief** w `sales_call_campaigns.bot_brief` (0691, lustro w `entrypoint.sh`,
  `sales_schema.BOT_LISTS_DDL`), model `bot_lists.Brief` (`extra="forbid"`): role,
  słowa branży, miasta, wielkości (`1-49`…`1000+`), PKD i województwa (dla L3),
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

## Dalej (L3–L4, osobne PR-y)

- **L3 rejestr.io w Grok Bocie:** rodzaj biegu z segmentem (PKD, województwa,
  wielkość, wyzwalacze); bot odsyła firmy z NIP-em, KRS, telefonem i e-mailem firmy
  oraz zarządem z linkiem. Do bota mogą iść NIP i KRS firm (decyzja Artura 13.11.2026;
  zmienia „tylko nazwy i domeny” z `sygnaly-grok-bot.md`), nadal bez danych osób.
  Dostęp do rejestr.io w rutynie ustawia Artur (na swoje ryzyko); w NEXUSIE, kodzie
  i dokumentacji nie ma haseł ani instrukcji logowania. Przy liczbach finansowych
  podpis „Źródło: rejestr.io” (regulamin pkt 7.2).
- **L4 podobne firmy:** segment z firm, z którymi było spotkanie.

Testy: `backend/tests/test_sales_bot_lists_unit.py`, `test_sales_bot_lists_api.py`,
`frontend/src/components/sales/__tests__/sales-bot-lists.test.tsx`.
