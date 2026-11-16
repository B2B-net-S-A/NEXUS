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
- **Kolejność: K8a → K8c → K8b → K8d.** K8c zrobione 16.11.2026 (sekcja
  niżej). Schematy MF w repo jak przy JPK_V7M (XSD JPK_KR_PD(1) v1-1 pobrany
  16.11.2026 do
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

## K8c — JPK_KR_PD(1) i JPK_ST_KR(1) za rok (`jpk_kr.py`, `jpk_st_kr.py`, `jpk_kr_compare.py`)

- **Decyzje Artura z 16.11.2026** (nie pytać ponownie): pobrać z crd.gov.pl
  importy XSD (StrukturyDanych, ElementarneTypyDanych, KodyKrajow v10-0E) i XSD
  JPK_ST_KR(1) v1-0 z gov.pl do `jpk_kr_schema/` (adresy importów przepisane na
  pliki obok, reszta bajt w bajt; kody urzędów v8-0E jak w JPK_V7M) — broszury
  MF tylko do czytania, nie do repo. **JPK_ST_KR budujemy już teraz**, choć
  rozporządzenie MF z 29.10.2026 (Dz.U. 2026 poz. 1444, od 3.11.2026, wg prasy)
  zwalnia z jego przesyłania za lata 2026–2028. NEXUS niczego nie wysyła.
- **Źródła zasad** (odczyt 16.11.2026): broszura JPK_KR_PD(1) z aktualizacją od
  1.07.2026 (`wersjaSchemy` = 1-1), broszura JPK_ST_KR(1) i „Pytania
  i odpowiedzi JPK_PD” na podatki.gov.pl — numery pytań niżej.
- **Znaczniki**: para K8a `KOD_Wn/KOD_Ma` = `S_12_1`/`S_12_2` (MF: najwyżej dwa
  znaczniki bilansu i RZiS, pyt. 23, 129). Oznacza się **oba warianty RZiS**
  (pyt. 108, 128): konta 4 — porównawcze, konta 5 — kalkulacyjne (`RKBI_*`,
  `RKD`, `RKE`), wpisuje je księgowa w „Pozycjach kont” (dla 5 reguły po numerze
  nie ma). 490 i pozabilansowe 9 bez wpisu = „INNE” (pyt. 61, 143). Konto
  nadrzędne = wspólny znacznik kont pod nim, inaczej „INNE” (pyt. 147).
  `S_12_3` (PD) nie ma — CIT estoński (pyt. 114).
- **ZOiS7**: konta z zapisem w roku (także samo BO) i każde konto nad nimi
  (pyt. 44, 141, 142); `S_3` = konto o poziom wyżej, syntetyczne = samo
  (pyt. 5, 13). Konto ostatecznego zapisu: saldo jednostronne. **Konto
  nadrzędne: sumy kont pod nim pole po polu, także salda Wn i Ma osobno**
  (rozrachunki: należność jednego kontrahenta nie znosi się ze zobowiązaniem
  drugiego) — wybór 16.11 bez wskazówki MF; porównanie z Symfonią pokaże, czy
  Symfonia liczy tak samo. Nazwa analityki słownika = kontrahent z kartoteki
  (konto kosztowe/przychodowe), inaczej „nazwa konta nadrzędnego · segment”.
- **Dziennik**: jeden dowód = jeden wpis (pyt. 95), `D_1` = numer pozycji
  dziennika NEXUSA (ciągły w roku, także BO i storna), `D_2` = „Dziennik Księga
  Główna” (pyt. 85), `D_5` = nazwa typu dokumentu, `D_8` = dzień zatwierdzenia
  (Warszawa), `D_9` = autor dokumentu (inaczej zatwierdzający, inaczej „NEXUS”),
  `D_11` = suma Wn dokumentu, `D_12` = numer KSeF z `meta.ksef_number`.
  `KontoZapis`: numer kolejny w pliku, Wn albo Ma, `Z_5`/`Z_8` + waluta dla
  pozycji walutowych. Storno czerwone = kwoty z minusem.
- **Kontrahent** tylko z numerem podatkowym (NIP, VAT UE, inny — PESEL nie;
  pyt. 111, 146): `T_1` = id kartoteki NEXUSA, `T_2` = kraj ISO także dla PL
  (EL → GR, XI/UK → GB; kod spoza słownika = bez `T_2`), `T_3` = numer jak na
  fakturze — VAT UE z prefiksem kraju (pyt. 104, aktualizacja 4.11.2026).
  Lista płac (LP) nie ma `D_3` — pracownik nie jest kontrahentem (pyt. 123).
- **Braki blokujące** (karta i 422 przy pobraniu): niezamknięte okresy roku,
  brak zatwierdzonych dokumentów, konto bez znacznika (bez Płac lista schodzi do
  konta syntetycznego dla kont z dokumentów płacowych — D2), rok nie na CIT
  estońskim — także **rok sprzed pierwszego roku ryczałtu** (przegląd K8c:
  szedł z `Znacznik_EST` i RPD z zerami; NEXUS nie liczy RPD ani znaczników
  PD), brak kodu urzędu (Płace →
  Parametry) albo adresu siedziby i pierwszego roku ryczałtu (ustawienia
  `app_settings['ledger'].jpk_kr`, zapisuje administrator: `PUT
  /reports/jpk-kr/settings`), rok po 2050 (`etd:TData`). Ostrzeżenia: księgą
  urzędową roku jest Symfonia; rok bez zamknięcia (przeksięgowanie wyniku
  przyjdzie z K8b).
- **Pobranie** (`GET /reports/jpk-kr/file?year=&kind=kr|st&correction=`): plik
  liczony od nowa i sprawdzany schematem MF przy każdym pobraniu, bez zapisu
  wersji (bez migracji). Korekta = cały plik od nowa z `CelZlozenia` 2
  (pyt. 139). JPK_KR_PD (dokumenty płacowe) pobiera osoba z Płacami albo
  administrator (403); JPK_ST_KR — każdy z modułem Sprawozdań.
- **JPK_ST_KR** z ewidencji K6, wariant CIT estońskiego (pyt. 137): `E_9_1` X,
  `E_10A` stawka podatkowa z K6, `E_10B` 0, `E_11` 0, `E_17` X, `E_19` 0; `E_12`
  i `E_20` = wartość i umorzenie podatkowe na koniec roku przed ryczałtem dla
  środków przyjętych wcześniej (stan z Symfonii późniejszy niż ten dzień = jego
  umorzenie), 0 dla przyjętych w czasie ryczałtu. Strona rachunkowa z planu
  bilansowego: `E_21` wartość na początek roku bez zmian z roku (pyt. 107),
  `E_24` ulepszenia z roku, `E_26` odpisy roku, `E_27` umorzenie z rokiem
  (pyt. 103), `E_25B` odpis jednorazowy roku. Środki na stanie w roku, bez
  zbytych wcześniej (pyt. 49, 113). `E_5` = numer OT, środek ze stanem
  z Symfonii = „stan z Symfonii ŚT” (ostrzeżenie); `E_2`/`E_3` = data przyjęcia
  (K6 nie trzyma daty nabycia); `E_6` = F przy OT z faktury, inaczej I; zbycie
  w roku: `E_28`–`E_30` (S sprzedaż, I likwidacja, numer LT/SP).
- **Porównanie z Symfonią** (`POST /reports/jpk-kr/compare?year=`, rok w trybie
  `symfonia` albo `parallel`, Płace albo admin): plik czytany bez sieci, encji
  i DTD, do 100 MB, rok z nagłówka = rok porównania; różnice ZOiS po `S_1`
  (kwoty `S_4`–`S_11`, znaczniki), konta tylko po jednej stronie, sumy `Ctrl`.
  Pliku nie zapisujemy.
- Ekran: Sprawozdania → „JPK_KR_PD za rok” (`JpkKrView.tsx`): braki, pobranie
  z korektą, JPK_ST_KR, porównanie, dane podatnika (administrator). Wzorzec
  bramek: `tests/data/authz_golden/ledger_reports.json`.
- **Staging 16.11.2026**: na kopii produkcji Księgowość jest pusta (0 lat,
  0 dokumentów, 12 kont planu) — prawdziwego pliku za 2026 jeszcze nie ma.
  Ścieżkę sprawdzono na kopii rokiem testowym przez usługi K1 (pobranie 200,
  plik i korekta przez XSD MF, porównanie z samym sobą = 0 różnic), potem
  usuniętym.
- Testy: `tests/test_ledger_jpk_kr_rules.py` (XSD obu plików, ZOiS, znaczniki,
  kontrahenci, braki, ustawienia, porównanie, ST na estońskim), test bramek
  i D2 w `test_ledger_db.py`, front `JpkKrView.test.tsx`.

## Dalej

- **K8b** zamknięcie roku (konta wynikowe → 860, BO następnego roku), przepływy
  (metoda pośrednia), zmiany w kapitale z podziałem na zysk sprzed i z okresu
  ryczałtu (znaczniki `BPAII_ES_*`, `BPAV_ES_*`), SFJINZ(2). Od biegłego:
  ujęcie podatku na ryczałcie (J) i podatek odroczony.
- **K8d** estoński CIT jak w decyzji wyżej; zależy od faktur kosztowych w NEXUSIE (E1).
