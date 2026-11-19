# Makiety modułu Kontrakty (19.11.2026) — tylko gałąź makiety, nie do scalenia

Prośba Artura: każdy ekran modułu Kontrakty w co najmniej dwóch wariantach,
bo dziś „nie wiadomo, co się dzieje na każdym z ekranów”. Makiety to prawdziwy
kod na tej gałęzi, renderowany w powłoce NEXUSA (pasek boczny, górny pasek),
z danymi pobieranymi na żywo ze stagingu (`localhost:8100`). Akcje nic nie
zapisują: przyciski mają `type="button"` i nie wołają API zapisu.

## Dwa kierunki

- **A — „Najpierw to, co wymaga działania”.** Każdy ekran zaczyna się od tego,
  co trzeba zrobić albo co się zmienia (kończy się, zaległa rozmowa, brak
  stawki), potem fakty. Mniej zakładek (10 → 7), zakładki z licznikami, jedna
  akcja główna w danym miejscu. Strona kontraktu: zwarty nagłówek, pas
  „Co się dzieje”, zakładki: Przegląd · Pieniądze · Dokumenty · Aneksy ·
  Opieka i rozmowy · Start i sprzęt · Historia.
- **B — „Karta umowy zawsze na widoku”.** Fakty (strony, okres, stawki,
  kontakt) w stałej karcie po lewej, praca w zakładkach po prawej. Gęściej,
  rejestrowo — dla osób, które wiedzą, czego szukają (Finanse, admin).
  Zakładki: Aktywność (notatki + zdarzenia) · Dokumenty · Aneksy · Opieka ·
  Wejście · Sprzęt · Faktury.

## Zasady wyglądu (wspólne dla A i B)

- Kolory wyłącznie z tokenów: `bg-card`, `bg-muted`, `text-foreground`,
  `text-muted-foreground`, `border-border`, `text-primary`, `bg-primary`,
  `text-success`/`bg-success`, `text-warning`, `text-info`, `text-destructive`.
  Żadnych `text-gray-*`, `bg-indigo-*`, `#hex`.
- Spokojne tabele: `lib/calm-table.ts` (`CALM_HEAD`, `CALM_ROW`, `CALM_AMOUNT`,
  `CALM_UNIT`, `CALM_SUBLINE`, `CALM_EMPTY`). Jedna cienka linia między
  wierszami, bez zebry, kwoty `tabular-nums`, jednostka raz w nagłówku kolumny.
  Wiersz 44–50 px, najwyżej dwie linie w komórce.
- Status w wierszu: `ds/StatusDot` (kropka + etykieta), nie plakietka.
- Przyciski: `components/ui/button` — `primary` tylko jeden na widok,
  `outline`/`ghost` dla reszty, `quiet` dla rzadkich i niebezpiecznych
  („Usuń”, „Zakończ współpracę…”, „Przepnij”). Żadnych kolorowych
  (zielony/fioletowy/czerwony) przycisków obok siebie.
- Żadnych natywnych `<select>` — menu z `components/ui/dropdown-menu`
  albo przycisk z ikoną `ChevronDown`.
- Daty `dd.mm.rrrr` (`shared/format.ts` → `fmtDate`), terminy po ludzku
  („za 11 dni”, „zaległe 49 dni”). Kwoty `fmtMoney`/`fmtRate`.
- Imion i nazwisk nie ucinamy; nazwę klienta i rekrutacji można uciąć
  z `title` na pełną nazwę.
- Teksty po polsku, bez angielskich etykiet pól („doc type”, „size bytes”)
  i bez surowego JSON-a. Zamiast adresu e-mail autora — imię i nazwisko
  (`personFromEmail`).
- Pusty stan mówi jednym zdaniem, czy to normalne i co zrobić; bez kursywy.
- Ekran docelowy 1280 × 720 (pasek boczny przypięty, treść ok. 990 px
  szerokości): główna treść zaczyna się w górnych 60% okna.

## Gdzie co jest

- Trasy: `/contracts/makieta-lista`, `/contracts/[id]/makieta?w=a|b&tab=…`,
  `/contracts/new/makieta`, `/contracts/analytics/makieta`,
  `/contracts/b2b-generator/makieta`, `/contracts/makieta-zamowienia`.
  Parametr `w=a|b` wybiera wariant.
- Dane: `shared/data.ts` (hooki `useMk…`, klucze zapytań z prefiksem `mk-`).
- Szkielety strony kontraktu: `shell/ShellA.tsx`, `shell/ShellB.tsx`.
- Zakładki: `tabs/<Nazwa>A.tsx` / `tabs/<Nazwa>B.tsx`, rejestr w `tabs/registry.tsx`.
