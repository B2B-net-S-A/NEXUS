# Lista osób za liczbą lejka i kafelek „Wyniki zespołu”
<!-- indeks: klik w liczbę lejka Zespół/Firma → „Kto się liczy · Cały zespół”, pary bez zasługi, kafelek HoR z okresem, nazwiska od 12.10 -->

Prośba Artura 23.10.2026: po kliknięciu Weryfikacji, Rekomendacji, Akceptacji
albo Placementów w Insights widać, kim są te osoby; Head of Recruitment chce
kafelek na pulpicie z dowolnym okresem i listą pod liczbą. Decyzje D1–D3
z 25.10.2026, makiety: https://claude.ai/artifact/4yk43hHpCNbD1RDKYwwFuV.

- **Jedna lista, nie trzecia.** Wiersze daje lista „Kto się liczy”
  (`/api/dashboard/v2/recruitment-activity/details`, `scope=team`,
  `window=range`) — ta sama co przy osobie w tabeli Ludzie i w licznikach celów
  (`ui/licznik-celow-w-gornym-pasku.md`). Nowej trasy nie ma.
- **Lejek Zespół i Firma:** liczby w wierszu „W okresie” są przyciskami;
  `?kto=<etap>&osoba=zespol` w adresie, więc „Wstecz” zamyka listę. Lista ma
  zakładki pięciu etapów lejka i dni okresu z paska.
- **Lejek liczy pary, lista zasługę.** Lejek: pierwsze wejście pary na etap,
  bez atrybucji. Lista: zasługa jak cele i wyścigi (`VERIFIER_ANCHORED_CTE`).
  Zwykle to ta sama liczba, ale nie zawsze (staging 25.10.2026: rekomendacje
  447 + 1 bez zasługi = 448 jak lejek; weryfikacje 506 + 1 = 507 przy 506
  w lejku). Dlatego pod zakładkami stoi „Do tego N … bez osoby z zasługą ·
  Pokaż”, a gdy suma i tak różni się od klikniętej liczby — zdanie z obiema
  liczbami (`teamListReconcile`). Nie ukrywaj tej linijki „bo zwykle się
  zgadza”: liczba na liście inna niż kliknięta bez słowa wyjaśnienia czyta się
  jak błąd.
- **Kto widzi nazwiska (D2, bez zmian):** role z `_TEAM_DETAIL_ROLES`
  (admin, Head of Recruitment, Delivery Lead, Finanse, TCM). W widoku Firma
  przyciski mają admin i Finanse; Rada nadzorcza widzi liczby bez nazwisk, jak
  w mailu „Nowy placement”. Rekruter widzi swoją listę w „Mój miesiąc”.
- **Przed 12.10.2026 nazwisk nie ma (D1).** Wpisy DynaReportera liczą się do
  wyniku, ale nie mają kandydatów; lista pisze „X z DynaReportera” i nie
  dokleja par z importu Traffita — tamte liczby się nie zgadzają (wrzesień:
  38 placementów w liczniku, 36 par z importu; 1–11.10: 5 wobec 14).
- **Kafelek „Wyniki zespołu” (`team_results`, D3):** okres na kafelku (ten
  i poprzedni tydzień, ten i poprzedni miesiąc, kwartał, od–do), cztery liczby
  i zwarta lista pod klikniętą. W układzie roli HoR zastępuje „Lejek zespołu ·
  7 dni”. Okres pamięta przeglądarka per kafelek (`nexus:team-results:<id>`) —
  zapis do układu szedłby całym PUT-em z wersją. Akceptacje okresu sprzed
  12.10.2026 to „—” z dopiskiem „liczone od 12.10”, nie 0.
