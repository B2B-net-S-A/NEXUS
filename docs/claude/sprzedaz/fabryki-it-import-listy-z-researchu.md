# Fabryki IT: import listy osób z researchu do map decyzyjnych — decyzje Artura 10.11.2026
<!-- indeks: Leady → „Lista z researchu”, plik CSV/XLSX jako dane niezaufane, przegląd przed zapisem, karty tej samej marki i wybór karty, klient NEXUSA bez osoby i konta, osoba bez dubla, konto i karta zakładane przy akceptacji, źródło i data przy osobie, poziom decyzji z nazwy stanowiska, bez tekstów RODO, bez biegu dat przy imporcie -->

Lista z researchu (82 osoby w 56 firmach, kierownicy AI i danych w centrach IT) była
stroną poza NEXUSEM i na mapy trzeba było ją przepisywać przez „Dodaj osobę”.
Rekomendacja B1 z makiet: https://claude.ai/artifact/PEfTGijHaxrPDZS2mkxKty. To drugi
PR pakietu „Centra IT” po liście kont i kolejce (`fabryki-it-lista-kont-i-kolejka.md`);
scalanie kart firm (B6) i status z Outlooka (B4) są osobno.

Kod: `backend/app/services/sales/research_file.py` (odczyt pliku, bez bazy),
`services/sales/research_import.py` (przegląd i zapis), trasy
`backend/app/api/sales_research_import.py` (`/api/sales/it-factories/research-import`),
front `frontend/src/components/sales/research-import/`, klient API
`lib/api/sales-research-import.ts`. Bez migracji.

## Skąd lista i kto ją wgrywa

- **Plik wgrywa człowiek z „Sprzedaż: edycja”** (Leady → „Lista z researchu”). NEXUS
  niczego nie pobiera ze strony researchu i nie wysyła osób do bota: do bota dalej idą
  tylko nazwy i domeny firm (`sygnaly-grok-bot.md`). Konto z samym podglądem nie ma
  wejścia, a obie trasy odmawiają mu 403.
- **Decyzja o skali:** wszystkie osoby z listy trafiają na mapy ze statusem „bez
  kontaktu”. Import niczego nie wysyła i nie dzwoni; kolejka do pierwszego kontaktu
  działa jak przed importem.
- **Plik nie jest przechowywany i nie ma tabeli wgranych list.** Przegląd odsyła
  wiersze, akceptacja przyjmuje je z powrotem i sprawdza od nowa. Ślad zostaje przy
  osobie (źródło, data) i w historii szansy. Ponowne wgranie tej samej listy pokazuje
  dodane osoby jako „Już na mapie”, więc przegląd można dokończyć innego dnia.

## Plik to dane niezaufane

- CSV albo `.xlsx`, do 2 MB, 500 wierszy z danymi i 40 kolumn; arkusz sprawdzany przed
  rozpakowaniem (rozmiar po rozpakowaniu, liczba plików w archiwum). Znaki sterujące
  i niewidoczne znaczniki kierunku tekstu są wycinane, komórka przycinana do limitu
  pola mapy, linki tylko http(s).
- **Limit liczy wiersze z danymi, nie linie arkusza.** `iter_rows(max_row=…)` ucinał
  po cichu dane leżące pod pustymi wierszami, więc arkusz czyta się do końca, a osobny
  sufit 20 000 linii (z pustymi) kończy się jawną odmową. Zepsuty XML arkusza i bomba
  encji wychodzą dopiero przy czytaniu wierszy: to też odmowa 422, nie błąd 500.
- **Błąd w wierszu nie wywraca pliku.** Wiersz bez firmy albo osoby idzie na listę
  pominiętych z numerem wiersza i powodem. Zły adres, telefon albo link odpada
  z ostrzeżeniem przy wierszu, a osoba zostaje.
- Kolumny rozpoznaje się po nagłówku bez ogonków i wielkości liter (`_HEADERS`).
  Wymagane: firma i osoba (jedna kolumna albo imię i nazwisko osobno).
- **Akceptacja sprawdza wiersz drugi raz:** pola przechodzą przez model mapy
  (`DecisionPersonCreate`), a każdy wiersz ma własny punkt zapisu. Wiersz, którego
  mapa nie przyjmie, dostaje wynik `error`, pozostałe się zapisują. Log ma numer
  wiersza i typ błędu, bez nazw (repo i logi są publiczne).

## Dopasowanie firmy

- **Karty tej samej marki, nie tylko dokładna nazwa.** Jedna firma ma w kartotece po
  kilka kart („Żuraw”, „Żuraw Group”, „Żuraw Polska”), więc przegląd szuka kart, których
  nazwa kanoniczna zaczyna się od marki (`company_aliases.brand_of`, ta sama reguła co
  „Inne nazwy z CV”). Jedno zapytanie na całą listę.
- **Cel wybiera się sam tylko w jednym przypadku:** jest dokładnie jedna karta o nazwie
  z pliku i żadna inna karta marki nie ma konta w lejku. W pozostałych kartę wskazuje
  człowiek, raz na firmę. Nową kartę można założyć tylko, gdy żadna nie nosi nazwy
  z pliku. Import nie scala kart: to osobny krok z biegiem na sucho (B6).
- **Stan firmy w wierszu:** konto w lejku (etap, osoby na mapie i po kontakcie liczone
  przez `factories.map_counts`), karta bez konta, kilka kart do wyboru, brak karty,
  klient NEXUSA, „Nie kontaktować”, nasza firma. Konto zamknięte dalej jest kontem
  firmy (drugie nie powstaje); konto w archiwum nie, akceptacja zakłada nowe.
- **„Znamy teraz” to ten sam skan co na liście kont** (`known_counts.count_known_people`),
  jeden na całą listę, najwyżej 150 kart, na końcu żądania. Przekroczony limit czasu
  zostawia przegląd bez liczników i z komunikatem. Firma bez karty nie ma licznika.
  Same liczby, bez nazwisk kandydatów.

## Akceptacja

- **Osoba trafia na mapę ze statusem `not_contacted`** i z kluczami pochodzenia we
  wpisie: `source` („research”), `source_label` (pole „Skąd lista”, obowiązkowe),
  `source_added_at` (dzień w kalendarzu firmy), `source_confidence`, `source_url`.
  Poprawka z okna osoby zachowuje te klucze, bo `PATCH` dokleja tylko pola formularza.
- **Historia szansy** dostaje wiersz `decision_map` jak przy „Dodaj osobę”, ze źródłem
  w opisie. Nowe konto ma też wiersz założenia (`record_created`).
- **Firma bez konta dostaje konto w lejku** na etapie „Mapa decyzyjna w trakcie”
  (bez niego: pierwszy otwarty etap), a firma bez karty także kartę z domeną z pliku.
  Opiekunem jest osoba wybrana w polu „Opiekun nowych kont” (domyślnie wgrywający),
  aktywne konto z „Sprzedaż: edycja”.
- **Osoba się nie dubluje:** ten sam e-mail albo to samo imię i nazwisko na mapie tej
  firmy (bez ogonków, kolejność wyrazów bez znaczenia) daje wynik „już na mapie”.
  Zapis trzyma blokadę wiersza szansy jak `add_decision_person`.
- **Jedna akceptacja naraz** (`pg_advisory_xact_lock` na początku `accept`). Dwa wiersze
  tej samej nowej firmy kliknięte jeden po drugim to dwa żądania; bez kolejki żadne nie
  widziało jeszcze karty ani konta i każde zakładało własne (`sales_companies`
  i `sales_opportunities` nie mają tu unikalnego indeksu). Ekran dodatkowo wstrzymuje
  pozostałe wiersze firmy, dopóki pierwszy się zapisuje.
- **Klient NEXUSA nie dostaje osoby ani konta.** Wiersz pokazuje klienta i Delivery
  Leada (`client_gate.match_companies`: nazwa z pliku, powiązanie karty, nazwa karty).
  Serwer sprawdza to przy każdym zapisie, nie tylko w przeglądzie. Karty klienta nie da
  się wskazać przy wyborze. Firma „Nie kontaktować” i nasza spółka też odpadają, także
  gdy żądanie wskazuje ich kartę wprost pod inną nazwą firmy.
- **„Dodaj pewne do map”** bierze wiersze oznaczone w pliku jako pewne, z ustalonym
  celem, po potwierdzeniu z liczbą osób, kont i kart. „Do weryfikacji” i firmy
  czekające na wybór karty zostają na liście do akceptacji pojedynczo.
- **Import nie odpala biegu dat zatrudnienia** (D3), choć zakłada konto: zbiorcza
  akceptacja tworzy kilkadziesiąt kont naraz, a każdy bieg to model AI dla nawet 1000
  osób w procesie web. Przycisk „Uzupełnij daty” na karcie firmy zostaje.

## Poziom decyzji (decyzja Artura z 10.11.2026)

- **Poziom bierze się z nazwy stanowiska** (`research_file.level_from_title`): Chief,
  skróty zarządu (CTO, CDO…), VP, prezes i członek zarządu to poziom 1; Head, Director,
  Dyrektor to poziom 2; reszta poziom 3. Kolumna „Poziom” w pliku ma pierwszeństwo,
  a człowiek zmienia poziom w wierszu przeglądu.
- **Kolejka się nie zmienia:** dyrektorzy z listy wchodzą do głównej części, kierownicy
  pod „Niższe poziomy”. Nie dokładaj osobnej sekcji „z researchu” ani nie przesuwaj
  progu kolejki: poziomy mają znaczyć to samo dla osób z importu i z Atlasa.

## Źródło przy osobie, bez tekstów RODO

- Okno osoby, kolejka i rozwinięty wpis na karcie szansy pokazują jedną linię:
  źródło, „na mapie od” i „do weryfikacji” (`decision-map-labels.sourceLine`). Wpis
  z Atlasa albo dodany ręcznie nie ma źródła i nic nie pokazuje.
- **Bez tekstu informacji z art. 14 RODO i bez przycisku jej kopiowania.** Artur
  10.11.2026: w elementach handlowych RODO pomijamy i zakładamy, że zgody są. Nie
  dokładaj klauzul, pytań o ich treść ani nowych ostrzeżeń prawnych na tych ekranach.

Testy: `backend/tests/test_sales_research_file.py`,
`backend/tests/test_sales_research_import.py`,
`frontend/src/components/sales/__tests__/sales-research-import.test.tsx`, wzorzec
`tests/data/authz_golden/sales_research_import.json`. Ścieżka na stagingu (konto
z edycją i konto z samym podglądem): https://claude.ai/artifact/ESnGhRRNJrJXvZ8sETFuwW.
