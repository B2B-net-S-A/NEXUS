# Cztery boty Sprzedaży zamiast jednej rutyny — decyzja Artura 13.11.2026
<!-- indeks: Bot Leady, Bot Research, Bot Dane firm, Bot Kontakty, rutyna Cognism, podział rodzajów na boty, KIND_BOT, bot_for, webhook per bot, GROK_BOT_LEADS_WEBHOOK, GROK_BOT_RESEARCH_WEBHOOK, GROK_BOT_COMPANY_WEBHOOK, GROK_BOT_CONTACTS_WEBHOOK, wspólny webhook jako zapas, pauza bota w app_settings sales_bots, ekran Leady → Boty, /api/sales/bots, teczka leada zamiast piątego bota -->

Artur 13.11.2026: zamiast jednej rutyny Groka z ośmioma rodzajami zadań są
cztery boty według pracy, każdy z własną rutyną i krótkim poleceniem. Raport
z makietami: https://claude.ai/artifact/2Hxqi6uLTSE4AYp1GPqtpV. Zapis wyników
bez potwierdzania: `sygnaly-grok-bot.md`, sekcja „Zapis od razu”.

## Kto co robi (`services/sales/bots.py`, `KIND_BOT`)

| Bot | Rodzaje biegów | Webhook |
|---|---|---|
| Bot Leady | `signals`, `winback`, `discovery` | `GROK_BOT_LEADS_WEBHOOK_URL/_KEY` |
| Bot Research | `briefing` (też tryby `call_hook`, `meeting_prep`), `question` | `GROK_BOT_RESEARCH_WEBHOOK_URL/_KEY` |
| Bot Dane firm | `enrich` | `GROK_BOT_COMPANY_WEBHOOK_URL/_KEY` |
| Bot Kontakty | `people` ze źródeł publicznych | `GROK_BOT_CONTACTS_WEBHOOK_URL/_KEY` |
| Rutyna Cognism | `people` z `request.source = "cognism"` | `GROK_BOT_PEOPLE_WEBHOOK_URL/_KEY` (jak dotąd) |

- Nowy rodzaj zadania = wpis w `KIND_BOT` (test `test_every_registered_kind_belongs_to_one_bot`
  pilnuje, żeby żaden rodzaj z rejestru nie został bez bota).
- **Bot bez własnej pary webhooka idzie na wspólny** (`GROK_BOT_WEBHOOK_URL/_KEY`),
  więc podział działa od wdrożenia, zanim powstaną nowe rutyny. Połowa pary to
  brak własnej. Cognism nigdy nie idzie na wspólny.
- `signals.configured(kind)` sprawdza webhook bota rodzaju; bez rodzaju: choć
  jeden bot poza Cognism ma webhook.
- „Bot do zbierania info o leadach” to **teczka leada** (nowy lead zamawia
  Dane firm, Kontakty i Research dla swojej firmy), nie piąty bot: osobna
  sesja i reguła w `sygnaly-grok-bot.md`, sekcja „Teczka leada”.

## Pauza i ekran Leady → Boty

- **Pauza** leży w `app_settings` pod kluczem `sales_bots` (`{"paused": [...]}`),
  bez migracji. Wstrzymany bot nie startuje nowych biegów: sprawdza to
  `signals.start_run` (jedno miejsce dla pętli, przycisków i skryptów), a trasy
  startu z kart odpowiadają 409 „<bot>: wstrzymany w Sprzedaż → Leady → Boty.”
  Raport biegu, który już trwa, NEXUS dalej przyjmuje.
- **Flagi środowiskowe zostają głównym włącznikiem** (`SALES_SIGNALS_ENABLED`,
  `SALES_BOT_TASKS_ENABLED`, `SALES_COGNISM_PEOPLE_ENABLED`), bo czyta je
  synchronicznie wiele miejsc (ekrany, pętla). Ekran pokazuje bota z wyłączoną
  flagą jako „Wyłączony”; włączenie flagi dalej idzie workflowem „Coolify set env”.
- `GET /api/sales/bots` („Sprzedaż: podgląd”): stan każdego bota (`webhook`
  own/shared/none, `enabled`, `paused`), biegi z 7 dni (wszystkie, z raportem,
  `failed` + `expired`), ostatni raport. `POST /api/sales/bots/{bot}/pause|resume`
  tylko administrator (403 dla reszty z „Sprzedaż: edycja”).
- Front: `components/sales/bots/BotsView.tsx`, strona `/sales/bots`, przełącznik
  „Leady | Boty” w zakładce Leady (bez ósmej zakładki Sprzedaży). Opisy pracy
  botów (`BOT_COPY`) zmieniasz razem z tą regułą.

## Rutyny w Grok Bocie

Polecenia czterech rutyn i kolejność zakładania: `docs/sales-grok-bot-setup.md`,
sekcja „Cztery rutyny (13.11.2026)”. Sekrety i zmienne tylko workflowem
„Coolify set env” z `value_from_secret`.

Testy: `backend/tests/test_sales_bots_unit.py`,
`frontend/src/components/sales/__tests__/sales-bots.test.tsx`.
