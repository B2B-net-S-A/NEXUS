# Księga NEXUSA (K8): sprawozdania, JPK_KR_PD i estoński CIT — decyzje 16.11.2026

Plan K8 z makietami: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar (sekcja „K8 do
decyzji”). Moduł `reports` Księgowości (wyłączony = widzi tylko administrator).
Reguły K1 (`ksiega-nexusa-k1-fundament.md`) obowiązują dalej.

## Decyzje Artura z 16.11.2026 (nie pytać ponownie)

- **RZiS w wariancie porównawczym** (koszty rodzajowe, konta 4). Konta 5 i 490
  (rozliczenie kosztów na MPK, K2) wariant porównawczy pomija; JPK_KR_PD i tak
  wymaga znaczników obu wariantów (MF, pytanie 108) — dochodzą w K8c.
- **e-Sprawozdanie: plik XML z NEXUSA, podpis i wysyłka poza NEXUSEM.** NEXUS składa
  sprawozdanie w strukturze SFJINZ(2) i sprawdza je schematem MF; informację
  dodatkową wgrywa księgowa; podpisuje kierownik jednostki i osoba prowadząca
  księgi, składa członek zarządu w eKRS (Repozytorium Dokumentów Finansowych).
- **Estoński CIT: rejestr i kwoty w NEXUSIE oraz plik CIT-8E.** Znacznik „ukryty
  zysk / wydatek niezwiązany” przy fakturze kosztowej i PK, miesięczny rejestr
  z podatkiem 20% i terminem 20. dnia, kwoty roczne i XML CIT-8E(4) za 2026,
  CIT-8E(5) od 2027. Kwalifikację pozycji potwierdza doradca; NEXUS niczego nie
  podpisuje i nie wysyła.
- **Kolejność: K8a → K8c → K8b → K8d.** Schematy MF w repo jak przy JPK_V7M
  (XSD JPK_KR_PD(1) v1-1 pobrany 16.11.2026 do
  `backend/app/services/ledger/jpk_kr_schema/`; SFJINZ(2) pobiera K8b).
- Warunek zatrudnienia estońskiego CIT (4 osoby na UoP w „Ludziach” 15.11) idzie
  pytaniem do Płac i doradcy (notatka Artura); NEXUS dostaje kontrolkę w K8d.

## Fakty z przepisów (sprawdzone 16.11.2026)

- **JPK_KR_PD + JPK_ST_KR**: pierwszy rok 2026 (spółka składa JPK_V7M); termin do
  końca 7. miesiąca po roku (ustawa Dz.U. 2026 poz. 779, od 1.07.2026) — za 2026
  do 2.08.2027. Na ryczałcie bez znaczników podatkowych PD, węzeł RPD z zerami
  (MF, pytanie 114; KIS 23.04.2026, 0111-KDIB2-1.4010.86.2026.1.AJ).
- **e-Sprawozdanie**: SFJINZ(2) dla sprawozdań sporządzanych od 1.01.2026.
  Spółka akcyjna jest badana → bilans, RZiS, przepływy, zmiany w kapitale,
  informacja dodatkowa (art. 45 ust. 3). Sporządzenie 31.03, zatwierdzenie 30.06,
  złożenie 15 dni od zatwierdzenia.
- **CIT-8E**: CIT-8E(4) za 2026 do 31.03.2027; podatek od ukrytych zysków
  i wydatków niezwiązanych do 20. dnia następnego miesiąca; stawka 20% (spółka
  nie jest małym podatnikiem). Zmiany od 2027 (druk 3137, ukryte zyski z usług
  od podmiotów powiązanych, definicja wydatków niezwiązanych) — katalog pozycji
  K8d trzymaj w ustawieniach, nie w kodzie.

## K8a — pozycje kont, bilans i RZiS (`services/ledger/markers.py`, `statements.py`)

- **Pozycja konta to znacznik MF** ze słownika `TMapKontaPOZ` (jednostki
  pozostałe) z XSD w repo — kodów nie przepisuje się ręcznie, słownik i opisy
  czyta `markers.dictionary()`. Ten sam znacznik obsłuży sprawozdanie,
  e-Sprawozdanie (K8b) i JPK_KR_PD (K8c).
- `finance_accounts.report_line` (kolumna z K1, bez migracji) trzyma `KOD` albo
  `KOD_Wn/KOD_Ma` (para tylko dla kont bilansowych: saldo Wn analityki →
  pierwszy, saldo Ma → drugi). Zapis konta odrzuca wolny tekst i nieznany kod
  (422). Do sprawdzenia w K8c: czy MF przewiduje na drugi znacznik pole S_12_2.
- **Skąd znacznik**: wpis przy koncie → przy koncie nadrzędnym (`201-2-1042` →
  `201-2` → `201`) → reguła po numerze (`markers.RULES`) → brak. Reguły tylko dla
  numerów jednoznacznych (13x, 20x, 22x, 23x, 24x, 64x, 402, 409, 70x, 73x,
  750/751, 760/761, 801, 820, 860, 870). **400–405, 010–080 bez reguły**:
  numeracja zespołu 4 zależy od planu spółki (K6 księguje amortyzację na 401),
  a środki trwałe dzielą się na pozycje bilansu według grup — wskazuje księgowa.
- Konta 9 (pozabilansowe) poza sprawozdaniami. Konta 5 i 490 nie wchodzą do RZiS
  porównawczego, ale ich saldo różne od zera idzie do „Zysku netto” bilansu
  z ostrzeżeniem (koszt zaksięgowany wprost na 5 rozjechałby RZiS i bilans).
- **Bilans** na koniec miesiąca (BO + obroty od stycznia), rozrachunki według
  salda każdej analityki. „Zysk (strata) netto” w trakcie roku = konta wynikowe
  od stycznia + saldo konta z BPAVI (860). **RZiS** za wybrane miesiące.
- Konto z saldem albo obrotem bez znacznika, ze znacznikiem „INNE”, ze
  znacznikiem tylko wariantu kalkulacyjnego albo **konto wynikowe z saldem w BO**
  (BO z niezamkniętego roku) = problem: sprawozdanie niekompletne (plik K8b nie
  powstanie).
- Końcówki `_A/_U/_O` (odpisy, umorzenie, odchylenia) łączą się z pozycją
  nadrzędną tylko w aktywach — `RPJ_RKM_O` to podatek „Odroczony”, osobna
  pozycja RZiS.
- **Płace (D2)**: kwoty pozycji to sumy całej księgi (jak sumy kont w obrotach
  i saldach); rozbicie pozycji na konta i lista problemów schodzą najniżej do
  konta syntetycznego (pierwszy segment numeru), bo analityka rozrachunków
  z pracownikami to często jedna osoba.
- Trasy `/api/accounting/reports/{statements,accounts,markers}` — sekcja
  Finanse, „Moduł Finanse”, przełączniki `ledger` i `reports`
  (`tests/data/authz_golden/ledger_reports.json`). Pozycję zmienia się
  `PATCH /chart/{id}`. Ekran: Księgowość → Sprawozdania (`/accounting/reports`;
  okruszek „Sprawozdania”, bo globalnie `reports` to „Raporty”).
- Od K8a wszystkie moduły Księgowości są w `BUILT`; testy „moduł bez ekranów =
  409” udają etap bez ekranów przez `monkeypatch` na `BUILT`.

## Dalej

- **K8c** JPK_KR_PD(1) + JPK_ST_KR (K6): ZOiS ze znacznikami, dziennik, zapisy
  kont, kontrahenci, RPD z zerami; w trybie roku „symfonia” porównanie z plikiem
  z Symfonii. Znaczniki wariantu kalkulacyjnego dla kont 4/5 (S_12_2?) —
  sprawdzić w broszurze MF przed kodem.
- **K8b** zamknięcie roku (konta wynikowe → 860, BO następnego roku), przepływy
  (metoda pośrednia), zmiany w kapitale z podziałem na zysk sprzed i z okresu
  ryczałtu (znaczniki `BPAII_ES_*`, `BPAV_ES_*`), SFJINZ(2). Od biegłego:
  ujęcie podatku na ryczałcie (J) i podatek odroczony.
- **K8d** estoński CIT jak w decyzji wyżej; zależy od faktur kosztowych w NEXUSIE (E1).
