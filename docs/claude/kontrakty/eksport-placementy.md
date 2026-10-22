# Eksport „Placementy” w Kontraktach · układ arkusza Delivery, DL i rekruter jak w Płacach, data podpisu = oznaczenie w NEXUSIE

Decyzja Artura 23.10.2026 po analizie arkusza „Tablica Statusowa” prowadzonego
ręcznie przez Delivery (makiety, kanwa prywatna:
https://claude.ai/artifact/PXBy1Se1pzVpPGnSaKv7Yr). NEXUS miał już wszystkie
dane placementu, ale w czterech miejscach (kontrakt, rekrutacja, Generator,
Płace), więc arkusz był dalej przepisywany ręcznie. Zamiast nowego ekranu jest
czwarta pozycja menu „Eksport” na liście Kontraktów. Historia sprzed NEXUSA
(2021–2025) zostaje w arkuszu jako archiwum i nie jest importowana.

Kod: `backend/app/services/contract_placements_export.py`, trasa
`GET /api/contracts/export/placements?start_from&start_to` (`api/contracts.py`),
front `components/v2/modals/PlacementsExportDialog.tsx`, `lib/placements-export.ts`.

- **Kto pobiera:** ta sama bramka co `/export` (`FinanceReadUser`: admin,
  Finanse i każdy z uprawnieniem „Moduł Finanse”; Rada nie). Wzorzec dostępu
  w `tests/data/authz_golden/contracts.json` jest kopią wiersza `/export` —
  inna bramka to świadoma zmiana dostępu do kwot.
- **Premie jak w Płacach, nie jak stawki:** bramka trasy przepuszcza „Moduł
  Finanse” bez uprawnienia „Płace”, a premie innych osób widzą tylko Płace
  (admin, Finanse domyślnie), sama osoba i przełożony (decyzja D2,
  `ludzie/urlopy-czas-place-wejscie-odejscie.md`). Eksport filtruje premie
  przez `PayrollViewer.sees_person` — nie czytaj `hr_bonuses` w eksporcie bez
  tego filtra (przegląd 23.10.2026 złapał przeciek przed merge'em).
- **Wiersz = kontrakt ze startem w okresie** i statusem aktywny, kończący się
  albo zakończony (jak premie z placementów). Okres, nie filtry listy: arkusz
  liczy placementy po starcie. „Powrót po przerwie” jest w pliku z uwagą —
  w premiach nie jest nowym placementem, ale Delivery ma go widzieć.
- **Kolumny w kolejności arkusza:** Konsultant, Klient, DL, Stanowisko,
  Stawka kosztowa, Stawka przychodowa, Marża, Marża mies., Data podpisania,
  Start day, Data akceptacji, Rekruter, Premia, Uwagi. Daty to daty arkusza
  (`DD.MM.YYYY`), nie napisy. Nie zmieniaj kolejności — to kontrakt z osobą,
  która porównuje plik ze swoim arkuszem.
- **DL i rekruter z reguły premii** (`placement_bonuses.load_context` /
  `PlacementContext.people`), nie z własnej logiki: plik i Płace muszą wskazać
  te same osoby. Rekruter = pierwszy weryfikujący; gdy zweryfikował sam DL,
  kolumna pokazuje DL-a, a uwaga „Zweryfikował DL — bez premii rekrutera”.
  Różnica z arkuszem Delivery (inny DL Nordei, „domknęła X”) to sygnał do
  poprawy rekrutacji albo reguły premii, nie do obejścia w eksporcie.
- **Stawki i marża z dnia startu, w zł/h** (`contract_margin`, jak premia):
  dzienna ÷ 8, miesięczna ÷ godziny rozliczeniowe; marża mies. = marża/h ×
  168 h. Brak stawki albo kursu = puste komórki i uwaga, nigdy zgadnięta
  liczba. Przyszły krok harmonogramu („55 → 60 po 6 mies.”) idzie do uwag.
- **Data akceptacji:** ostatnia data z okna „Klient zaakceptował”
  (`client_accepted_on`); bez niej dzień pierwszego ruchu karty na
  „Akceptację” z uwagą „Data akceptacji z ruchu karty” (przed 16.10.2026 okna
  nie było — ruch karty bywa 1–5 dni po akceptacji).
- **Data podpisania = dzień oznaczenia podpisu w NEXUSIE**
  (`b2b_generated_contracts.signed_at`, zapisywane jako „teraz”), nie dzień
  podpisu na papierze. Na kopii produkcji z 22.10.2026 była zwykle 1–5 dni
  późniejsza niż w arkuszu Delivery. Umowa spoza Generatora = pusta komórka
  i uwaga. Prawdziwa data podpisu wymaga pola przy „Oznacz jako podpisaną”.
- **Premia:** premie automatu Płac do kontraktu (`source=contract_placement`,
  bez anulowanych, tylko widoczne dla pobierającego): „rekruter Jan Bąk 1500 zł; DL Ewa Kowal 772,80 zł
  (propozycja)”.
- **Sprawdzenie na danych:** październik 2026 na kopii produkcji — 37 kontraktów,
  wszystkie 33 placementy z arkusza są w pliku (4 dodatkowe: kontrakt bez
  rekrutacji, akceptacje z ruchu karty). Porównanie wiersz po wierszu robi się
  skryptem dopasowującym po imieniu i nazwisku; nazwisk nie wpisuj do repo
  (publiczne).
