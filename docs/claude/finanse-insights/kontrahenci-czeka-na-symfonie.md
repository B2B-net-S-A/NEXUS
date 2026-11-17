# Kontrahenci „Czeka na Symfonię”: lista, plik dla księgowej i powrót ID (E0b, 17.11.2026)

Symfonia FK zostaje księgą urzędową, eBI24 znika (decyzja Artura z 17.11.2026).
Dziś nowych kontrahentów zakłada w Symfonii aplikacja „EBI24 Księgowość 2.0” na
komputerze księgowej, łącząc się wprost z bazą SQL Symfonii. Po wyłączeniu eBI24 tego
nie będzie, a NEXUS **nie pisze do bazy Symfonii** (decyzja Artura z 17.11.2026):
daje plik, księgowa zakłada kontrahentów u siebie i odsyła ID.

## Kto jest na liście

`GET /api/finance/counterparties/pending` (`services/finance_ledger/symfonia_partners.py`),
zakładka Finanse → Kontrahenci → „Czeka na Symfonię”. Jeden wiersz na numer:

- **kartoteka** — wiersz `finance_counterparties` bez `symfonia_partner_id`
  (np. dostawca z formularza zakupu zagranicznego),
- **faktura sprzedaży** — nabywca `client_sales_invoices` (NIP albo VAT UE), którego
  numeru nie ma w kartotece; adres z karty klienta (`clients.address`, jedno pole),
- **faktura kosztowa** — sprzedawca z kolejki kosztów bez kontrahenta (nie
  odrzucony); NEXUS zna tylko nazwę i numer, adresu nie.
- Faktury osób zespołu widzą tylko Płace i admin (D2) — ta sama bramka
  `costs._payroll_scope` co w kolejce kosztów, na liście i w pliku.
- Numer sprawdzamy jak w imporcie (`identifiers.normalize`): zły NIP, brak numeru,
  nazwy albo kraju = wiersz „do poprawy”, widoczny na liście, **nie trafia do pliku**.
  Brak adresu to tylko ostrzeżenie.
- Pusta kartoteka (zero ID Symfonii) = ostrzeżenie na ekranie: najpierw import
  „Partnerzy → Pobierz” z eBI24, bo bez niego na liście są wszyscy, także ci,
  którzy w Symfonii już są (na stagingu 17.11: 208 nabywców, kartoteka pusta).

## Plik

`GET /pending/file` — CSV roboczy, UTF-8 z BOM, średniki, CRLF, nazwa
`kontrahenci-do-symfonii-RRRR-MM-DD.csv`. Kolumny: Nazwa, NIP / VAT UE, Typ numeru,
Kraj, Ulica, Kod pocztowy, Miasto, **ID Symfonii (puste — wpisuje księgowa)**,
prefiksy kont odbiorcy i dostawcy, źródło w NEXUSIE.

- **To nie jest format importu Symfonii.** Próbki księgowej (szablon 4 faktur,
  model księgowy XML) nie zawierają formatu kartoteki, a ona sama nie wie, jakim
  szablonem eBI24 synchronizuje kontrahentów. Format docelowy dopiszemy po jej
  odpowiedzi (pytanie w opisie PR-a E0b); do tego czasu plik jest listą roboczą.
- Nagłówki są aliasami importu E0 (`counterparty_import.ALIASES`) — test
  `test_ta_sama_kartka_z_id_wraca_przez_import_e0` pilnuje, żeby zmiana nagłówka
  nie zerwała powrotu.
- Nazwa, ulica i miasto zaczynające się od `=`, `+`, `-`, `@` dostają spację
  z przodu (Excel nie wykona formuły; import ją zdejmuje).

## Powrót ID (import E0)

Księgowa odsyła ten sam plik z „ID Symfonii” przyciskiem „Wgraj plik z ID Symfonii”
(ten sam `POST /import`, podgląd i „Zapisz”):

- **Konta z ID**: gdy plik ma ID Symfonii, a ani plik, ani kartoteka nie mają kont,
  import dopisuje `201-2-ID` / `200-2-ID` (Polska) albo `203-2-ID` / `202-2-ID`
  (zagranica; kraj z kolumny, kartoteki albo prefiksu VAT UE). Dowód: eksport
  partnerów z eBI24 — 2326 z 2326 ma dokładnie te konta, a model księgowy
  Symfonii ma na trzecim poziomie kont 200/202 słownik „Kontrahenci”. Dekret
  kosztu czyta `cost_account`, więc bez tego kontrahent z samym ID zostawałby
  „bez konta rozrachunkowego”. ID niebędące liczbą — kont nie zgadujemy.
- **Nowy wiersz bez ID i bez kont nie zakłada kontrahenta** (`waiting` w wyniku,
  „N dalej czeka” w podglądzie). Bez tego odesłana w połowie kartka założyłaby
  w kartotece kontrahentów, których w Symfonii nie ma.
- Reszta reguł importu E0 bez zmian (`ksiegowosc-koszty-i-kontrahenci.md`).
