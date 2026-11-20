# „Nowy kontrakt” w wariancie B i Analityka z oknem 90 dni (20.11.2026)
<!-- indeks: karta „Podsumowanie” (`lib/new-contract-summary.ts`), „Zaawansowane”, podpowiedź stawek z rekrutacji bez wpisu, Analityka: okno 90 dni z listy kontraktów tylko w PLN (`lib/contract-analytics.ts`), tabela Klienci · Konsultanci, Rola × klient zwinięta -->

Decyzja Artura z 19.11.2026 po makietach modułu Kontrakty (etap 3a wdrożenia):
„Nowy kontrakt” w wariancie B, „Analityka” w wariancie A z tabelą z wariantu B.

## Nowy kontrakt (`app/contracts/new/page.tsx`)

- Po lewej trzy sekcje (Strony umowy, Okres, Stawki) i zwinięte „Zaawansowane”
  (waluty, jednostka, godziny, stawka ramowa, zmiany stawki konsultanta, zużycie
  zamówienia, status przy utworzeniu) ze skrótem zawartości w nagłówku. Po prawej
  przyklejona karta „Podsumowanie” z jedynym przyciskiem głównym, który mówi, co
  powstanie („Utwórz szkic”, „Utwórz jako aktywny”…).
- Reguły karty: `lib/new-contract-summary.ts` (testy obok). Marża tylko przy tej
  samej walucie obu stawek, miesiąc = stawka × godziny rozliczeniowe albo ryczałt,
  stawka konsultanta w dniu startu jak `Contract._resolve_scheduled_rate`. Kwoty
  w karcie widzi tylko ten, kto widzi pola stawek (`canManageCandidateFinance`).
- „Konsultant dostaje” to pierwszy etap harmonogramu; kolejne etapy i daty
  pierwszego są w „Zaawansowanych”. Błąd pola stamtąd (status, waluty, etapy)
  rozwija sekcję — komunikat nie może stać pod zwiniętym nagłówkiem.
- Podpowiedź stawek z rekrutacji (D7, `GET /api/clients/{id}/recruitment-rates`)
  stoi pod polem tylko przy wybranej rekrutacji (bez niej API oddaje najnowszą
  parę u klienta, która bywa sprzed lat), nic nie wpisuje się samo, różnica nie
  blokuje zapisu. „Użyj”
  jest tylko przy stawce konsultanta w tej samej jednostce i walucie; stawka
  klienta to sama informacja, bo przychód w kontrakcie przed zamówieniem gasi
  Finansom dzwonek „bez zamówienia” (`stawki-z-rekrutacji-w-zamowieniu-i-umowie.md`).
- Pola, walidacja, mapowanie 409 na pola, zapis `POST /api/contracts`,
  `router.replace` po zapisie i bramka `contracts_orders_edit` — bez zmian.

## Analityka kontraktów (`app/contracts/analytics/page.tsx`)

- Układ: cztery liczby → „Najbliższe 3 miesiące” → linia prognozy marży → tabela
  „Kto ile przynosi” (Klienci · Konsultanci, sortowanie nagłówkiem) → zwinięte
  „Więcej zestawień” (Rola × klient, lokalizacja, powody zakończeń). Macierz
  zostaje, bo z ekranu nic nie znika bez śladu; dane pobierają się po rozwinięciu.
- Sumy firmy, także wiersz „Razem” tabeli, tylko z `margin-totals`
  (`analityka-kontraktow-utylizacja-i-kafle-sum.md`). Awaria i brak kursu FX to
  „—” ze zdaniem, nigdy zero.
- Okno 90 dni: `GET /api/contracts?status=active&status=ending` z
  `expiring_in_days=90` (kończą się) albo `start_from` jutro … `start_to` +90 dni
  (startują), do 100 pozycji — więcej ekran mówi wprost. Marża z bieżących stawek
  z listy (`windowMonthlyMargin` w `lib/contract-analytics.ts`) i **tylko w PLN**:
  kontrakt w innej walucie liczymy osobno („poza sumą”), bo front nie ma kursu
  NBP. Brak stawek albo kwoty ukryte = „marża nieznana”, nie zero.
- Lista kontraktów stoi za „Klienci, kontrakty i zamówienia: podgląd”: bez niego
  okno mówi to zdaniem, a tabela traci tylko kolumny 90 dni.
- Zapytania ruszają dopiero za bramką „Wyniki firmy”. Nowość tego ekranu ma
  `section: "finance"` jak middleware — test sekcji w `backend/tests/test_novelties.py`
  zna ten wyjątek obok Generatora umów.
