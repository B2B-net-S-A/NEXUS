# Księgowość w Finansach: Koszty i Kontrahenci (E0, E1, 0696, 13.11.2026)

Firma wymienia eBI24 (obieg faktur) na NEXUS. Ten etap to kartoteka
kontrahentów z kontami Symfonii (E0) i jedna kolejka faktur kosztowych ze
statusami księgowymi (E1). Makiety M1, M2 (bez dekretu) i M7:
https://claude.ai/artifact/6fcZ8LYRRevuX5rJNAZ9W3. Dekret i eksport do
Symfonii to E2, przelewy E3, wystawianie faktur E4 — nie dopisuj ich tu
„przy okazji”.

## Moduł „Księgowość”

- Przełącznik `app_settings['finance_accounting']` (`services/finance_ledger/settings.py`),
  domyślnie wyłączony, włącza admin (`PUT /api/finance/costs/module` albo przycisk
  na zakładce „Koszty”, który admin widzi przy wyłączonym module). Wyłączony moduł
  = 404 dla Finansów, admin widzi zawsze; wyłączony program „Ludzi w NEXUSIE”
  zamyka moduł dla wszystkich (faktury przychodzą z pętli KSeF tego programu).
- Trasy `/api/finance/costs` i `/api/finance/counterparties` (`api/finance_ledger.py`):
  sekcja Finanse, `FinanceModuleUser`, wyłącznik programu. Wzorzec bramek:
  `tests/data/authz_golden/finance_ledger.json`.
- **Moduł „Zgody” zostaje ukryty** (decyzja z 21.10.2026,
  `ludzie/zgody-wydatki-i-premie-poza-umowa.md`). Włączona „Księgowość” sprawia,
  że pobieranie z KSeF zapisuje faktury dostawców jako dokumenty wydatków także
  przy wyłączonych „Zgodach”, ale wtedy **bez dopasowania do zgód i stałych
  kosztów** (`cost_invoices.store(match=False)`): dokument zostaje `unmatched`
  z pustym `match_reason`. Przy włączonych „Zgodach” zachowanie jak dotąd.

## Kolejka kosztów (E1)

- Trzy źródła zostają, jakie są: faktury osób zespołu (`payroll_invoices`, Płace),
  faktury kontraktorów klientów (`client_contractor_invoices`, rozliczenia klientów)
  i dokumenty wydatków (`approval_documents`). Kolejka dokłada wpis
  `finance_cost_entries` z kluczem źródła (`source_type` + `source_id`, unikalne).
  Danych faktury nie kopiujemy: numer, sprzedawcę i kwoty czytamy ze źródła przy
  każdym odczycie (`costs._sources`, `UNION ALL`). Zapisujemy tylko to, co się nie
  zmienia (NIP sprzedawcy, chwila wpływu, czy z KSeF) i warstwę księgową.
- **Wpis powstaje** przy zapisie faktury w pobieraniu z KSeF (`sync._ledger_entry`
  po zapisie u Płac, kontraktora i dokumentu wydatku), na końcu każdego przebiegu
  (`_ledger_catch_up` — dołapuje też PDF-y wgrane ręcznie) i przy starcie
  (`DATA_DDL` w `finance_ledger_schema.py`, ten sam SQL co backfill migracji).
  Awaria wpisu nie cofa zapisu faktury. Wstawiamy tylko faktury bez wpisu
  (`WHERE NOT EXISTS`, żeby cogodzinny przebieg nie zjadał wartości sekwencji
  `SERIAL` na każdym wierszu źródeł); `ON CONFLICT DO NOTHING` zostaje jako
  zabezpieczenie przed wyścigiem. Istniejący wpis się nie zmienia.
- Wpisy powstają **niezależnie od przełącznika** — po włączeniu modułu kolejka ma
  pełną historię. Żeby nie zalać Finansów starymi fakturami, ekran ma filtr
  „Miesiąc wpływu”; backfill nie udaje „Zaksięgowanych” (to robi E2).
- **Etapy** jak w eBI24: `received` (Z KSeF do przyjęcia: Przyjmij / Odrzuć z
  powodem) → `new` (Do opisu) → `verified` → `ready` (Gotowe do księgowania) →
  `booked` (Zaksięgowane, ustawia E2). Odrzucić można w poczekalni i w „Do opisu”;
  „Cofnij” idzie o jeden krok, z „Odrzuconych” wraca do poczekalni (KSeF) albo do
  „Do opisu” (PDF). Dokument spoza KSeF zaczyna od „Do opisu” — poczekalnia jest
  tylko na KSeF. Zaksięgowanej nie ruszamy (etap, flagi, kategoria, termin).
- **Nikt nie zmienia etapu ani opisu własnej faktury** (faktura osoby zespołu
  z jego kontem) — 403, także zbiorczo (reszta zaznaczonych przechodzi, odmowy
  wracają w `refused`). Wszystkie odmówione = 4xx z powodem pierwszej.
- Flagi zastępują etykiety procesowe eBI24: MPP, NIE MPP (wykluczają się — CHECK
  i serwis), Wstrzymać płatność, Zapłata na konto US, Duplikat. Kategoria:
  Kontraktorzy, Zespół, Biuro, Benefity, Proforma, Inne (z KSeF: osoba zespołu =
  Zespół, kontraktor = Kontraktorzy, dokument wydatku = Biuro; Finanse zmieniają).
- Historia (`finance_cost_entry_events`): każda zmiana etapu, flag, kategorii,
  terminu i notatki z osobą i chwilą; powód odrzucenia w `detail`.
- **„Kogo dotyczy”** pokazuje to, co źródło już ustaliło, nic nie liczy od nowa:
  osoba i rozliczenie miesiąca z Płac, kontrakt i miesiąc kontraktora, zgoda na
  wydatek. Termin płatności: z rozliczenia osoby (`payroll_settlements.due_on`)
  albo wpisany ręcznie; metadane KSeF nie niosą terminu (XML kosztów nie
  pobieramy — budżet pobrań zostaje dla Płac).
- **Faktury osób zespołu widzą tylko Płace i admin** (D2,
  `ludzie/urlopy-czas-place-wejscie-odejscie.md`; ta sama bramka `is_payroll` co
  lista faktur w `api/hr_ksef.py`). Konto z samym „Modułem Finanse” nie widzi ich
  w kolejce ani w licznikach, karta i PATCH dają 404, akcja zbiorcza zwraca je
  w `refused` jako 404 (`costs._payroll_scope`). Kategoria tych faktur to
  „Zespół” (decyzja Artura z 13.11.2026).
- Start kolejki: bez daty startu — stare faktury odsiewa filtr „Miesiąc wpływu”
  (decyzja Artura z 13.11.2026).

## Kartoteka kontrahentów (E0)

- `finance_counterparties`: identyfikator (NIP, PESEL, VAT UE, inny) po
  normalizacji, unikalny razem z typem; wiersz bez identyfikatora musi mieć ID
  partnera Symfonii (też unikalne). NIP i PESEL z sumą kontrolną; „PL” + NIP
  i VAT UE z prefiksem PL to ten sam NIP (`finance_ledger/identifiers.py`).
- **Rola nie jest zapisana**, liczy się przy odczycie: klient (numer prowadzi do
  klienta przez `client_invoicing.clients.nip_registry`), osoba zespołu
  (`employee_billing_details`), kontraktor (kontrakt aktywny albo zakończony do
  92 dni — `contractor_invoices.load_index`), inaczej dostawca.
- **Import** pliku z eBI24 („Partnerzy → Pobierz”, XLSX albo CSV;
  `counterparty_import.py`): nagłówki po aliasach (bez wielkości liter, polskich
  znaków i spacji; konta i Symfonia także w środku nagłówka, wygrywa najdłuższy
  alias), wiersz nagłówka w pierwszych 10 wierszach. Najpierw podgląd (nowe,
  zmienione, bez zmian, błędy z numerem wiersza), „Zapisz” to ten sam przebieg
  z zapisem. Pusta komórka niczego nie kasuje (ręczna poprawka konta zostaje
  po ponownym imporcie pliku bez tej kolumny). Duplikat identyfikatora albo ID
  Symfonii w pliku to błąd drugiego wiersza; ID Symfonii u innego kontrahenta —
  błąd wiersza. Zły e-mail jest pomijany bez błędu.
- Po zapisie wpisy kolejki bez kontrahenta dostają go po NIP-ie sprzedawcy
  (`LINK_COUNTERPARTIES`); to samo robi przebieg KSeF i start.
- Ręcznie: ID Symfonii, konto kosztowe, konto przychodowe, e-mail
  (`PATCH /api/finance/counterparties/{id}`). Nowych kontrahentów ręcznie nie
  zakładamy (konto nadaje Symfonia, przychodzą importem).

## Ekrany

- Finanse → zakładki „Koszty” i „Kontrahenci” (przy otwartym module);
  karta faktury `/finance/costs/[id]`, okruszek „Koszty”
  (`/finance/costs` przekierowuje do zakładki).
- Podgląd jako inna osoba jest tylko do odczytu (bez zaznaczania i przycisków).
