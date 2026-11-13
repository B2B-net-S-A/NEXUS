# Księga NEXUSA (K1, 0699, 13.11.2026): lata, okresy, dokumenty, dziennik, plan kont

Decyzje Artura z 13.11.2026: Symfonia FK, Symfonia Środki Trwałe i Enova 365
przechodzą do NEXUSA etapami K1–K9 (plan z makietami:
https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar). Każdy moduł wchodzi
wyłączony — kod gotowy, wyłączony moduł widzi tylko administrator. Do
przełączenia księgą urzędową jest Symfonia FK: NEXUS księguje równolegle,
a o dacie (1.01.2027 albo 1.01.2028) decyduje Artur z księgową po miesiącach
zgodnych z Symfonią. eBI24 (E0–E5) to osobny plan:
`ksiegowosc-koszty-i-kontrahenci.md` — nie dopisuj tu jego etapów.

## Moduły i dostęp

- Przełączniki w `app_settings['ledger']` (`services/ledger/settings.py`):
  `ledger`, `automations`, `bank`, `vat`, `assets`, `payroll`, `reports`.
  Włączyć da się tylko moduł z ekranami (`BUILT`), reszta = 409 z etapem.
  Wyłączony program „Ludzi w NEXUSIE” zamyka Księgowość dla wszystkich.
- Trasy `/api/accounting/*` (`api/ledger.py`): sekcja Finanse, „Moduł Finanse”
  (`FinanceModuleUser`), przełącznik `ledger` (wyłączony = 404, admin widzi).
  Wzorzec bramek: `tests/data/authz_golden/ledger.json`.
- **Zatwierdzanie bufora, storno, zamknięcie okresu i założenie roku** — lista
  „Księgowi” w ustawieniach (ustawia admin, tylko konta z „Modułem Finanse”)
  albo admin. **Tryb roku, ponowne otwarcie okresu, przełączniki, lista** —
  tylko admin. Bez nowego uprawnienia w katalogu dziewięciu (decyzja 13.11).
- **Dokumenty płacowe** (`sensitivity = 'payroll'`: listy płac, faktury osób
  zespołu) widzą w szczegółach tylko Płace i admin (D2): poza listą
  i licznikami, karta 404, zatwierdzenie 404, na karcie konta jeden wiersz
  zbiorczy na miesiąc. Sumy kont w obrotach je obejmują.

## Dokument i dziennik

- Rok obrotowy = rok kalendarzowy z 12 okresami (`ledger_years`,
  `ledger_periods`), tryb `symfonia` / `parallel` / `nexus`. Nowy rok startuje
  w trybie `symfonia`; tryb `nexus` (księga urzędowa) ustawia admin dopiero
  po miesiącach równoległych i aktualizacji polityki rachunkowości (art. 10).
- **Bufor** (`draft`): dokument z poprawnym dekretem — co najmniej dwie
  pozycje, Wn = Ma w groszach, konta z planu, aktywne, bez analityki pod spodem
  — w otwartym okresie. Można go poprawić i usunąć; ślad zostaje
  (`ledger_events`).
- **Zatwierdzenie** nadaje kolejną pozycję dziennika roku (`journal_no`,
  numeracja ciągła w roku pod blokadą wiersza roku, w kolejności daty operacji
  w zaznaczeniu). Zatwierdzony dokument jest trwały: serwis odmawia zmiany
  i usunięcia (409), a **wyzwalacz w bazie** (`ledger_guard_approved`) nie
  przepuści UPDATE ani DELETE dokumentu i jego pozycji. Jednorazowe sprzątanie
  (testy, `scripts/repairs`) ustawia `SET LOCAL nexus.ledger_purge = 'on'`.
- **Storno** zatwierdzonego: nowy dokument `ST` z tymi samymi kontami
  i stronami, kwoty z minusem (storno czerwone), od razu zatwierdzony
  w bieżącym otwartym okresie. Raz na dokument; storna się nie odwraca.
  Po stornie źródło (np. faktura) może dostać nowy dokument — unikat źródła
  pomija odwrócone.
- **Okres** zamyka się przy pustym buforze z tego miesiąca; zamknięty nie
  przyjmuje dokumentów ani zatwierdzeń. Ponownie otwiera admin z powodem.

## Plan kont

- Jedna tabela kont z E2 (`finance_accounts`), rozszerzona w 0699 o konto
  nadrzędne, typ (aktywne/pasywne/aktywno-pasywne/wynikowe/pozabilansowe),
  słownik analityki i pozycję sprawozdania; rodzaj `other` dla kont spoza
  dekretu faktur. Nie zakładaj drugiej tabeli kont.
- **Analityka słownikowa**: konto ze słownikiem (np. `201-2` → kontrahenci)
  przyjmuje `201-2-NNN` bez zakładania każdej analityki w planie; samego
  `201-2` nie księguje się. Konto z kontami pod sobą (`402` → `402-203`) też
  nie przyjmuje zapisów.
- Konta użytego w aktywnej regule dekretu E2 nie wyłącza się i nie zmienia mu
  się rodzaju (409).

## Raporty

- Obroty i salda tylko z zatwierdzonych: BO (dokumenty `BO`), obroty okresu,
  narastająco, saldo; poziom syntetyczny grupuje analitykę słownika pod jej
  kontem. Karta konta z saldem narastającym (najwyżej 2000 zapisów).

## Ekrany

- Księgowość (`/accounting`, pozycja menu przy otwartym module, flaga
  `accounting` z `/api/accounting/config`): Miesiąc, Dokumenty (formularz PK/BO
  z bilansem liczonym jak na serwerze, karta z dekretem i śladem), Obroty
  i salda z kartą konta, Plan kont, Ustawienia. Miesiąc w adresie
  (`?year=&month=`, History API).
- Kolejne etapy (K2 źródła, K3 automaty, K4 bank, K5 VAT, K6 ŚT, K7 płace,
  K8 sprawozdania) dopisują swoje zakładki w `ACCOUNTING_TABS`
  (`components/accounting/ledger-model.ts`) i klucz w `BUILT`.
