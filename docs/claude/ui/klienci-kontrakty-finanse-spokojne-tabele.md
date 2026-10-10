# Klienci, Kontrakty, Finanse — spokojne tabele (02.10.2026)

Odświeżenie wyglądu trzech modułów bez zmiany funkcji, API i reguł (makiety:
https://claude.ai/artifact/C5VtWkkeGkgA5TsTZmv9EC). Decyzje Artura 02.10.2026:
rzadkie i niebezpieczne akcje zostają na wierzchu, ale ciche; podgląd PDF stoi
obok planu w skrzynce zamówień; sekcje spod „rozwiń” są rozwiniętymi kartami;
wiersz tabeli ma 46–50 px i najwyżej dwie linie w komórce.

- **Wspólne klocki:** `Button variant="quiet"` (szary, czerwony dopiero po
  najechaniu albo fokusie — „Usuń”, „Zakończ współpracę…”, „Przenieś”),
  `ds/StatusDot` (kropka + etykieta zamiast plakietki statusu w wierszu),
  `ds/InlineStats` (liczby w nagłówku zamiast rzędu kafli), stałe
  `lib/calm-table.ts`, `client-profile/orders/RateTrio` (koszt · przychód ·
  marża w panelach). `components/ui/table.tsx` bez zmian — wygląd idzie przez
  `className`.
- **Tabela:** jedna cienka linia między wierszami, bez zebry i pionowych kresek,
  kwoty `tabular-nums` bez czcionki maszynowej, jednostka raz w nagłówku kolumny
  (w komórce tylko, gdy wiersz ma inną niż kolumna). Kolory statusów i marży
  wyłącznie z tokenów `success/warning/info/destructive`.
- **Zamówienia klienta:** nagłówek kolumn raz na sekcję (MD / Kosztowe /
  Okresowe), zamówienie to pas z numerem, pod nim osoby; nagłówek w każdym
  zamówieniu zostaje jako `sr-only` (czytniki ekranu, wspólny `colgroup`).
- **Motyw „Wyraźny” nie ramkuje komórek:** reguła `[data-soft] .bg-card`
  w `globals.css` pomija `td`/`th`. Przyklejona pierwsza kolumna ma `bg-card`
  tylko po to, żeby zakryć kolumny pod sobą — z ramką karty wyglądała jak
  pudełko w wierszu.
- **Finanse → Wyniki:** kolejność kolumn ma jedno źródło (`COLUMNS`
  w `FinanceResultsTable.tsx`) dla nagłówka i wiersza — Klient stoi zaraz po
  Kandydacie; pilnuje `FinanceResultsTable.test.tsx`.
- **Nic nie zniknęło:** inwentarz `lib/orders-contracts-feature-inventory.json`
  i kotwice `data-help` bez zmian. Harnessy nowych widoków:
  `/preview/clients-list`, `/preview/client-profile-tabs`,
  `/preview/finance-results`.
- Poza zakresem (osobne tematy): jeden formater kwot i jeden słownik statusów
  dla trzech modułów, kolumna „Delivery Lead” na liście klientów (wymaga API).
