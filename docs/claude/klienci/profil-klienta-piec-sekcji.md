# Profil klienta: pięć sekcji, nagłówek ze stanem i Przegląd od „Wymaga uwagi” (19.11.2026)
<!-- indeks: `lib/client-tab-groups.ts` (5 grup), `ClientStateChip`, `ClientFrameworkChip`, `ClientHeaderStats` (Nasi ludzie, Otwarte rekrutacje, Marża / mc, Wymaga uwagi), `useClientOverviewAttention`, `ProfileTab` = Przegląd -->

Decyzja Artura z 19.11.2026 (makiety „Klienci: nowe ekrany”, warianty A ekranów
„Nagłówek i sekcje” oraz „Przegląd”). Zastępuje „osiem grup” z
`ui/klienci-i-finanse-jedna-lista.md`. Pytanie Artura: zakładki „nie są
klarowne” — „Współpraca” była zbiorem zasad rekrutacji, startu konsultanta
i Delivery Leada, „Ludzie” mieszali się z „Konsultantami”, zasady rekrutacji
nie stały w „Rekrutacjach”, a Przegląd miał pustą połowę ekranu i sprawy
rozsiane po pięciu kartach.

## Sekcje

- Przegląd · **Nasi ludzie** (Konsultanci, Zamówienia, Start u klienta,
  Delivery Lead) · **Rekrutacje** (Projekty, Zasady rekrutacji, Materiały dla
  rekruterów, Konflikty) · **Ludzie klienta** (Kontakty, Działy i technologie,
  Sprzedaż) · **Umowa i pieniądze** (Umowy i aneksy, Stawki i cennik, Raporty
  dla klienta, Faktury i rozliczenie, Analityka, Importy MD).
- Klucze `?tab=` bez zmian (linki z powiadomień). Nowe nazwy podzakładek:
  „Zasady rekrutacji” (dawniej „Zasady współpracy”), „Start u klienta”
  („Wejście u klienta”), „Kontakty” („Kontakty i relacje”), „Działy
  i technologie” („Ludzie i technologie”).
- Przy nazwie grupy cicha liczba (`SectionNavGroup.meta`): ilu naszych ludzi,
  ile otwartych rekrutacji, ile kontaktów. To nie plakietka „do zrobienia”.
- Kotwice nowości grup zostały: `client.sections.people` na „Ludziach klienta”,
  `client.sections.contracts` na „Umowie i pieniądzach”.
- Tekst checklisty „Koniec współpracy” w sprawach back office mówi dalej
  „pakiet »Wejście u klienta«”: kroki back office dopasowują go dosłownie
  (`back_office/steps.py`), a otwarte sprawy w bazie mają stare brzmienie.
  Zmiana wymaga migracji danych — świadomie poza zakresem.

## Nagłówek

- Zamiast „Statusu klienta” stan współpracy (`ClientStateChip`): ta sama reguła
  co lista „Klienci” (`klienci/lista-klientow-stan-z-faktow.md`).
- „DL: …” to przycisk do „Nasi ludzie › Delivery Lead”. Umowa ramowa
  (`ClientFrameworkChip`, tylko przy podglądzie dokumentów umów): do kiedy,
  ostrzeżenie od 90 dni, klik do „Umów i aneksów”.
- Liczby (`ClientHeaderStats`): Nasi ludzie (+ kto zaczyna w dymku), Otwarte
  rekrutacje (`summary.open_jobs`, tylko opublikowane — jak kolumna listy;
  „Aktywne projekty” w Projektach liczą też szkice), Marża / mc (reguły
  „Brak stawek”, „Brak kursu”, „(niepełna)” bez zmian), Wymaga uwagi (tylko > 0).

## Przegląd

- Kolejność: „Wymaga uwagi · N” → cztery liczby (Nasi ludzie, Otwarte
  rekrutacje, Rozliczenie poprzedniego miesiąca, Umowa ramowa) → Najnowsze
  rekrutacje i Ludzie klienta → Raporty, sprzęt, statystyki i notatki.
- „Wymaga uwagi” (`components/client-profile/overview-attention.ts`) składa
  wyłącznie istniejące reguły: umowa ramowa wygasła albo kończy się w 90 dni
  (bez innej obowiązującej), znaczniki konsultantów z serwera (bez kontynuacji,
  brak bieżącego zamówienia, wypowiedzenie), kontrakty bez stawki, otwarte
  raporty z katalogu, decydenci i kluczowe relacje bez kontaktu ponad 30 dni.
  Więcej niż dwa raporty albo osoby zbijają się w jedną pozycję.
- **Bez „po terminie” z rozliczenia** — ani w „Wymaga uwagi”, ani na karcie
  rozliczenia. 19.11.2026 żadna z 2 741 faktur „po terminie” nie miała
  zapisanej zapłaty. Wraca, gdy NEXUS zacznie zapisywać zapłaty.
- Wszystkie karty używają kluczy zakładek (`client-profile`,
  `framework-contracts`, `client-reports`, `client-contacts`, faktury) —
  przejście do zakładki niczego nie pobiera drugi raz.
- Testy: `app/clients/[id]/__tests__/ClientConsultantsTab.test.tsx` (Przegląd
  i nagłówek), `lib/__tests__/client-tab-groups.test.ts`,
  `components/client-profile/SummaryBar.test.tsx`.

## Ekrany sekcji (etap 3a, 19.11.2026)

- **Nasi ludzie › Konsultanci**: jeden rząd filtrów (role `tab`): Pracują teraz,
  Wymaga uwagi, „Kończy się DD.MM” (dzień z ≥ 5 końcami zamówień w 120 dniach,
  `orderWave`), Zaczynają, Szkice, Zakończeni. Przełącznik „Lista / Oś czasu”
  (`ConsultantsTimeline`: okres bieżącego zamówienia na 8 miesiącach, pomarańczowy
  = bez kontynuacji, przerywany = bez daty końca). Kategoria kompetencji w dymku
  przy nazwisku (`ConsultantIdentity compact`), wiersz ma dwie linie.
- **Rekrutacje › Projekty**: aktywne w grupach „Bez przypisanego rekrutera”,
  „W toku”, „Szkice” (`groupActiveProjects`). Rekruter = przypisania zespołu
  (`workingRecruiters`), jak kolumna „Rekruter” — NIE pole właściciela z profilu
  (19.11.2026 u PKO BP: 34 kontra 16 „bez rekrutera”). „Zamknij z powodem…”
  w menu „…” wiersza — świadomy wyjątek od „rzadkie akcje na wierzchu, ale
  ciche” (makieta zatwierdzona 19.11.2026). Ściąga `ClientRecruitingSheet`
  (zasady z karty klienta, aktywne konflikty) obok tabeli od 1536 px, niżej pod nią.
- **Ludzie klienta › Kontakty**: grupy według wagi (`lib/client-contacts-weight.ts`):
  decydenci i kluczowe relacje, kierownicy i dyrektorzy (po stanowisku),
  pozostali — zwinięci, gdy jest ich ponad 10 i coś stoi nad nimi. Przy frazie
  płaska lista. Nad tabelą: ile kontaktów ma zapisaną rozmowę. „Usuń” zostaje
  cichym przyciskiem (spokojne tabele, 02.10.2026).
- **Rekrutacje › Zasady rekrutacji**: nad pełną kartą klienta „Najważniejsze
  zasady” — ustawione liczby (blokada, SLA, limit CV) i pierwsze linie zasad
  procesu bez znaczników (`playbookCheatLines`, ten sam skrót co ściąga przy
  Projektach). Karta (`ClientPlaybookCard`) bez zmian — używa jej też Champion.
- **Ludzie klienta › Sprzedaż**: trzy liczby nad listą szans (otwarte, wygrane
  w 12 miesięcy, przegrane; suma tylko w jednej walucie, `salesFigures`).
- **Umowa i pieniądze › Umowa**: jedna strona (`ContractPage` w `page.tsx`)
  — umowy i aneksy, „Stawki i cennik”, raporty dla klienta — dla osób
  z podglądem dokumentów umów. `?tab=stawki-ramowe` i `?tab=raporty` otwierają
  ją przewiniętą do swojej części, w pasku świeci „Umowa”; podzakładek stawek
  i raportów wtedy nie ma. Bez podglądu umów zostają same „Raporty dla
  klienta”. Kotwica nowości `client.sections.framework-rates` stoi na nagłówku
  „Stawki i cennik”.
- Poza etapem 3 (osobny krok): Rozliczenie miesiąca jako kroki RCP → faktura → KSeF → zapłata
  (czeka na naprawę „po terminie” — zapłaty nie są zapisywane) i „Start
  u klienta: N z 5 ustalone” (sposób rozliczania godzin jest w innej trasie
  niż pakiet klienta).
