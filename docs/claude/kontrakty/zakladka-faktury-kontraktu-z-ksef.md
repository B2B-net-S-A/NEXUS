# Faktury kontraktu = faktury konsultanta z KSeF (19.11.2026)

Od przebudowy strony kontraktu (#3639, 7 zakładek) faktury są sekcją zakładki
„Pieniądze” (`?tab=money`; dawny adres `?tab=invoices` prowadzi tutaj).
Do 19.11.2026 zakładka „Faktury” czytała ręczny rejestr `invoices` (`/api/invoices`,
Phase 9 C1, #35) z przyciskiem „Dodaj fakturę”. Na kopii produkcji z 19.11
tabela miała 0 wierszy od powstania (17.04.2026), więc zakładka zawsze
pokazywała „Brak faktur”, a prawdziwe faktury konsultantów z KSeF leżały
w `client_contractor_invoices` (Rozliczenia E4) i były widoczne tylko
w Finanse → Rozliczenia, miesiąc po miesiącu. Decyzje Artura 19.11.2026:

- **Jedno źródło:** `GET /api/contracts/{id}/contractor-invoices`
  (`api/contract_contractor_invoices.py`) — faktury i korekty konsultanta
  z KSeF ze wszystkich miesięcy kontraktu, najnowszy miesiąc pierwszy,
  bez odrzuconych podpowiedzi NIP-u (`contractor_invoices.for_contract`).
  Zakładka (`components/ContractInvoicesTab.tsx`) jest tylko do odczytu:
  fakturę wystawia konsultant w KSeF, NEXUS ją pobiera. Miesiąc prowadzi
  do karty osoby w Rozliczeniach (`/finance?view=settlements&stClient=…
  &stMonth=…&stContract=…`), gdzie zostają kontrole (kwota z RCP, łańcuch
  korekt, biała lista) i termin płatności — zależą od reguł miesiąca.
- **Kto widzi:** jak Rozliczenia — sekcja Finanse i „Moduł Finanse”
  (admin, Finanse, osoba z nadanym modułem). Delivery Lead i Back office
  nie (wzorzec `tests/data/authz_golden/contract_contractor_invoices.json`
  ma te same litery co `GET /api/finance/settlements/contract/{contract_id}`).
  Wyłączony moduł rozliczeń = 404 z komunikatem modułu, admin widzi zawsze.
- **Bez ręcznego „Dodaj fakturę”** w kontrakcie. Nie przywracaj formularza
  ani odczytu z `invoices` w tej zakładce: dwa źródła faktur dla jednego
  kontraktu rozjechałyby się przy pierwszej korekcie.
- Tabela `invoices` i jej trasy (`/api/invoices`, API v1 `/api/v1/invoices`,
  kafle DSO i „faktury po terminie” pulpitu v2) zostały na razie bez zmian;
  ich wygaszenie to osobne zadanie, a `DROP` wymaga zgody Artura.
