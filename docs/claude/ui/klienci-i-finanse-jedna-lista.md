# Klienci i Finanse: jedna lista, wszystko pod klientem, Księga w Finansach (18.11.2026)
<!-- indeks: Klienci bez trybów, kolumny „Umowa ramowa” i „Wymaga uwagi”, profil klienta w 8 grupach (`client-tab-groups.ts`), „Umowy klientów” tylko u osoby bez Klientów (`MENU_SHADOWED_BY`), `FinanceAreaNav` dla `/finance` i `/accounting`, `ds/SectionNav` -->

Decyzje Artura z 18.11.2026 po makietach na stagingu („dlaczego umowy klientów
są osobno, a raporty jako osobna zakładka, a nie pod klientem”; „jak to jeszcze
uprościć”). Makiety przed/po: prywatny artefakt z 18.11.2026 (link w pamięci
sesji, nie w repo — ma nazwiska i kwoty). Zasada: menu prowadzi do listy, lista
do rekordu, a rekord ma wszystko. Przekroje przez wielu klientów nie są
osobnymi zakładkami modułu.

## Klienci: jedna lista

- **Od 19.11.2026 lista ma jeden wiersz na klienta i stan współpracy liczony
  z faktów** („Współpracujemy / Bez bieżącej pracy / Archiwum”), a dawna lista
  zakresów w zakładkach portfela to „Porządki portfela” —
  `klienci/lista-klientow-stan-z-faktow.md`. Opis kolumn niżej dotyczy
  „Porządków portfela”.
- `/clients` nie ma trybów. Dawne „Raporty dla klientów” (`?view=reports`)
  i „Kluczowe relacje” (`?view=contacts`, `/my-relationships`) otwierają listę.
- Kolumna **„Umowa ramowa”**: koniec (`do …` albo „bezterminowa”) i drobnym
  drukiem `od …`. Zastąpiła „Start umowy” i „Koniec umowy”.
- Kolumna **„Wymaga uwagi”** (`components/clients/ClientAttention.tsx`, czyste
  `buildClientAttention` i `contractAttention`): otwarty raport miesiąca
  z kalendarza (po terminie, dziś, do przygotowania, bez terminu), kluczowa
  relacja bez osobistego kontaktu ponad 30 dni albo bez zapisu (ta sama skala
  co kropka „Ostatni kontakt”, `touchpointTone`) i umowa ramowa, która wygasła
  albo kończy się w 90 dni. Każdy znacznik prowadzi do zakładki klienta.
  Pusta komórka znaczy, że nic nie czeka. Dane z istniejących tras:
  `/api/client-reports/calendar` i `/api/my-relationships`.
- Nowa rzecz o kliencie to podzakładka w jego profilu. Gdy trzeba ją widzieć
  przez wszystkich klientów naraz, dokładasz znacznik do „Wymaga uwagi” (albo
  kafelek pulpitu), a nie tryb modułu Klienci.

## Profil klienta: osiem grup

> **Od 19.11.2026 nieaktualne — pięć sekcji:** `klienci/profil-klienta-piec-sekcji.md`.
> Opis niżej zostaje jako historia decyzji z 18.11.2026.

- Grupy i podzakładki (`lib/client-tab-groups.ts`, test pilnuje, że każdy klucz
  `?tab=` ma dokładnie jedną grupę): Przegląd · Konsultanci (konsultanci,
  zamówienia, importy MD — od 18.11.2026, `klienci/zakladka-konsultanci-u-klienta.md`)
  · Umowy (umowy i aneksy, stawki i cennik, raporty dla klienta) ·
  Rozliczenia (faktury i rozliczenie, analityka) · Współpraca (zasady, wejście
  u klienta, Delivery Lead) · Ludzie (kontakty i relacje, ludzie i technologie)
  · Rekrutacje (projekty, materiały dla rekruterów, konflikty) · Sprzedaż.
  Bez „Więcej”.
- Klucze `?tab=` się nie zmieniły (linki z powiadomień). Nowe: `materialy`
  i `konflikty` (dawniej karty w prawej kolumnie Profilu).
- „Stawki i cennik” (`stawki-ramowe`) widzi każdy z podglądem dokumentów umów
  klienta: cennik i „kategorie i dopłaty” przeszły tu spod listy umów, tabela
  stawek ramowych (F2) dochodzi, gdy klient ma cennik umowy ramowej.
- **Przegląd**: lista konsultantów jak dotąd, a w prawej kolumnie karty
  (`ClientOverviewCards`): umowa ramowa, raporty dla klienta, rozliczenie
  poprzedniego miesiąca (przy module faktur) i kluczowe osoby (decyzyjne
  i kluczowe relacje z kontaktów klienta). Karty używają tych samych kluczy
  zapytań co zakładki, więc przejście do zakładki niczego nie pobiera drugi raz.

## „Umowy klientów”

- `/client-contracts` zostaje dla osoby z samym uprawnieniem „Umowy klientów:
  lista i pliki” (która nie wchodzi do Klientów). Pozycja menu i skrót w palecie
  stoją tylko u niej: `MENU_SHADOWED_BY` w `lib/nav-registry.ts` chowa je, gdy
  widać „Klientów”. Pozostali mają umowy pod klientem (Umowy › Umowy i aneksy).
- Lista ma podsumowanie nad tabelą i filtr „Obowiązujące / Kończą się w 90 dni /
  Wszystkie” (domyślnie obowiązujące: aktywne i czekające na podpis).

## Finanse: Finanse i Księga w jednym module

- Jedna nawigacja `components/finance/FinanceAreaNav.tsx` dla `/finance?view=`
  i `/accounting/*`, w grupach: Przegląd (Miesiąc księgi) · Przychody
  (rozliczenia klientów, faktury do klientów) · Zamówienia (zmiany, PDF-y,
  import MD, rozjazdy stawek) · Koszty (faktury kosztowe, wydatki ze zgodą,
  księgowanie faktur, przelewy, kontrahenci, lista płac) · Księga (źródła,
  dokumenty, wyciągi bankowe, rozrachunki, automaty, VAT, środki trwałe,
  do Symfonii) · Raporty (wyniki miesięczne, obroty i salda, sprawozdania,
  archiwum wyników, archiwum eBI24) · Ustawienia (plan kont, reguły dekretu,
  ustawienia księgi). Adresy się nie zmieniły.
- Widoczność pozycji to te same przełączniki i uprawnienia co dotąd („Moduł
  Finanse”, `orders_work`, moduły faktur, rozliczeń, Zgód, eBI24 i księgi,
  Płace). Back office widzi jedną grupę: Zamówienia.
- Menu ma jedną pozycję „Finanse” (wpis „Księgowość” ma `inSidebar: false`),
  a na `/accounting/*` świeci „Finanse” (`isNavItemActive`).
- Samo `/finance` (bez `?view=`) przy otwartej Księdze prowadzi na Przegląd
  (`/accounting`); dlatego każdy widok Finansów ma adres z `?view=`.
- „Plan kont” jest jeden (Ustawienia → Plan kont, `/accounting/chart`); zakładka
  Finansów z regułami dekretu nazywa się „Reguły dekretu”. Dwie paczki do
  Symfonii (faktury kosztowe E2 w „Księgowaniu faktur”, dokumenty księgi K3b
  w „Do Symfonii”) zostały osobno — scalenie po rozmowie z księgową.
- Nowy widok Finansów albo Księgi = pozycja w `FinanceAreaNav` (i trasa
  w `ACCOUNTING_TABS` dla księgi), nie nowy pasek zakładek.

## Wspólne

- `components/ds/SectionNav.tsx`: grupy z podkreśleniem, pod aktywną grupą
  przełącznik podzakładek (grupa z jedną pozycją go nie ma), licznik grupy =
  suma pozycji. Kotwica nowości na pozycji (`tourId`) idzie z komentarzem
  `// data-tour="…"` w tej samej linii, bo strażnik kotwic szuka ich dosłownie.
- Kotwice: `finance.modes` (`data-help`, przewodnik i Start Finansów),
  `finance.sections`, `finance.rate-divergences`, `client.sections`,
  `clients.attention` (`data-tour`, nowości w rejestrze).
- Usunięte: `ReportsCalendarPanel` i `KeyRelationshipsPanel`; słownik siły
  relacji jest w `components/clients/relationship-strength.ts`. Kalendarz
  miesiąca albo „Moje relacje” wracają, jeśli ktoś ich potrzebuje, jako
  kafelek pulpitu, nie tryb Klientów.
