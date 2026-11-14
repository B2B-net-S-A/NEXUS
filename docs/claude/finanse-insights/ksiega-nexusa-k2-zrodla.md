# Księga NEXUSA K2 (14.11.2026): faktury kosztowe i sprzedaży jako dokumenty księgi

Etap K2 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar).
Fundament (lata, okresy, bufor, dziennik, storno, blokady) opisuje
`ksiega-nexusa-k1-fundament.md`. Do przełączenia księgą urzędową jest Symfonia:
NEXUS księguje równolegle, więc dokument ze źródła musi dać się porównać
z Symfonią miesiąc do miesiąca.

## Źródła (`services/ledger/sources.py`, zakładka „Źródła”)

- **Koszty → FVZ.** Dekret liczy E2 (`finance_cost_entries.decree`); K2 go nie
  przelicza, tylko przepisuje pozycje. Do księgi idą faktury „Gotowe do
  księgowania” i „Zaksięgowane”. Okres = miesiąc **wpływu** (`received_at`
  w czasie firmy), jak paczka E2 do Symfonii. Problemy dekretu E2
  (`posting.issues_for`) blokują dokument tak jak paczkę.
- **Sprzedaż → FVS.** Każda faktura z KSeF, gdzie spółka jest sprzedawcą
  (`client_sales_invoices`: z eBI24 i z NEXUSA). Wn rozrachunek z odbiorcą
  (brutto), Ma przychód (netto), Ma VAT należny. Okres = miesiąc **sprzedaży**
  (P_6, inaczej wystawienia); korekta — miesiąc wystawienia korekty.
- **Waluta**: kurs NBP z ostatniego dnia roboczego przed dniem sprzedaży
  (`posting.rate_day`, tylko kurs z dokładnie tego dnia, bez szukania wstecz).
  Faktura wystawiona w NEXUSIE bierze kurs zapisany przy wystawieniu (E4),
  korekta — kurs faktury pierwotnej. Brutto i VAT po kursie, netto jako
  różnica (jak E2). Rozrachunek ma kwotę w walucie (`amount_cur`).
- **Kwota ujemna** (korekta in minus) zamienia strony, kwoty zostają dodatnie —
  jak w dekrecie E2. Faktura zaliczkowa (ZAL) i jej korekta (KOR_ZAL) czekają
  na regułę zaliczek (K3) — korekta zaliczki jako FVS zmniejszyłaby przychód,
  którego w księdze nie było.
- **Konto rozrachunkowe odbiorcy**: „konto przychodowe” kontrahenta z kartoteki
  E1 (import z eBI24 — odpowiednik „konta kosztowego”, którego E2 używa jako
  konta rozrachunkowego dostawcy), inaczej konto z Ustawień + `-` + ID Symfonii
  kontrahenta. Nabywcy szukamy po NIP-ie albo VAT UE (`identifiers.normalize`).
  Nabywca spoza kartoteki = problem: kontrahentów nie zakładamy z faktur,
  przychodzą importem z eBI24 (zasada E1).
- **Konta faktur sprzedaży** (`app_settings['ledger'].sales`: rozrachunki,
  przychód, VAT należny) ustawia administrator (`PUT /config/sales`); każde musi
  być w planie kont. Bez konta przychodu sprzedaż czeka z problemem.

## Księgowanie miesiąca

- „Zaksięguj miesiąc” (`POST /sources/sync`, „Moduł Finanse”) robi szkice
  w buforze; zatwierdza lista „Księgowi” (K1). Jest **idempotentne**: dokument
  ma źródło (`source_type` `finance_cost_entry` / `client_sales_invoice` +
  `source_id`) i odcisk danych (`meta.fingerprint`). Nowe źródło = nowy szkic,
  zmienione = szkic przebudowany, wycofane albo z problemem = szkic usunięty.
- **Zatwierdzonego zapisu NEXUS sam nie odwraca**: zmienione albo wycofane źródło
  z zapisem w dzienniku wraca jako problem „zrób storno zapisu nr N”; po stornie
  następne księgowanie zrobi nowy dokument (unikat źródła pomija odwrócone).
- Podgląd (`GET /sources`) liczy to samo co zapis, łącznie z kontrolą planu kont
  (`engine.check`) — nie obiecuje dokumentu, którego nie da się zapisać.
- Zamknięty okres albo brak roku = 409 na całe księgowanie.
- **Faktury osób zespołu** (`payroll_invoice`) to dokumenty płacowe (D2): osoba
  bez Płac ich nie księguje, nie widzi w licznikach i jej księgowanie ich nie
  usuwa; karta mówi tylko, że księguje je osoba z Płacami.

## Rozliczenie kosztów na „5” (`services/ledger/allocation.py`)

- Dekretu E2 (zespół 4, koszty rodzajowe) nie zmieniamy. Co miesiąc jedno PK
  ze źródłem `cost_allocation` / `RRRR-MM`: Wn konta „5” z MPK w pozycji,
  Ma konto rozliczenia kosztów (490). Ta sama maszyna co faktury: odcisk,
  przebudowa szkicu, zatwierdzone PK zmienionego miesiąca = problem do storna.
- **Z czego — zapisy miesiąca, jak w dzienniku**: zatwierdzone FVZ okresu ze
  źródłem w kolejce kosztów (także te odwrócone później) i zatwierdzone storna
  takich FVZ zaksięgowane w tym okresie, z MPK faktury pierwotnej. Storno
  w kwietniu odejmuje koszt w kwietniu, a zamknięty marzec zostaje zgodny —
  wcześniejsza zasada „bez odwróconych” psuła zamknięty miesiąc przy każdej
  korekcie (przegląd poprawności 14.11.2026). Kwota = Wn − Ma pozycji na kontach
  rodzaju „koszt”; rodzaj bierzemy z planu po prefiksie numeru, bez reguł
  księgowalności — analityka założona pod kontem albo wyłączenie konta nie
  gubią zaksięgowanych kosztów. FVZ w buforze nie wchodzą (karta pokazuje ich
  liczbę).
- Miesiąc, w którym koszty zeszły do zera, a PK jest zatwierdzone, daje problem
  „zrób storno zapisu nr N” (tak samo każde źródło bez kwot z zapisem).
- **MPK**: faktura kontraktora → klient kontraktu (`K<id>`); faktura osoby
  zespołu → pion z kartoteki (`FO` / `BO`); dokument akceptacji → klient
  wniosku, inaczej pion wnioskującego; reszta → koszty ogólne (`OG`) — biuro
  do czasu klucza podziału od Finansów (lista działów na „5” to bloker z planu).
- **D2**: koszty z faktur osób zespołu idą osobnym PK (`RRRR-MM-payroll`,
  wrażliwość `payroll`) na **jednym koncie kosztów zespołu** dla wszystkich
  pionów, z pionem tylko w MPK pozycji. Obroty i salda pokazują sumy kont
  każdemu z „Modułem Finanse”, a suma pionu bywa kwotą jednej osoby — osobne
  konta FO/BO w PK płacowym by ją ujawniły.
- Konta (rozliczenie, klienci, Front office, Back office, koszty ogólne,
  koszty zespołu) ustawia administrator (`PUT /config/allocation`); bez nich PK
  czeka z problemem.
- Dalej w K2: rozrachunki i bilans otwarcia — kolejne PR-y.
