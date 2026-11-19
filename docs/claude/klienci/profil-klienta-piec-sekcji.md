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
