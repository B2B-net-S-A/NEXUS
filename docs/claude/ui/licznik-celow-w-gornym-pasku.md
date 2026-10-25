# Licznik celów w górnym pasku (13.10.2026)
<!-- indeks: podpisane segmenty, panel po kliknięciu, „poniżej tempa”, cel DL z 30% hit ratio -->

Do 13.10.2026 licznik w górnym pasku pokazywał trzy pary „znak + wynik/cel”
bez nazw (`🎯 1/4 ↓ 0/5 → 3/15`), kolejność wyznaczał alfabet po id, a szczegóły
były w dymku na najechanie. Decyzje Artura 13.10.2026: cele mają mieć nazwy,
celu „Nowi kandydaci dziś” już nie ma, a celem Delivery Leada jest 30% hit
ratio. Makiety: https://claude.ai/artifact/SDmwSbF8c9wWoqnUtB3KLt, raport:
`docs/topbar-kpi-goals-completion-report.md`.

- **Co widać w pasku** (`components/v2/kpi/`): do trzech podpisanych segmentów.
  Rekruter: Weryfikacje (dziś), Rekomendacje (tydzień), Placementy (miesiąc).
  Head of Recruitment i TCM: te same trzy jako suma zespołu. Delivery Lead:
  Placementy do celu, Hit ratio, Zamknięte rekrutacje. Admin, Finanse i rola
  podglądu nie mają celów, więc licznika nie widzą. Osoba z własnymi celami
  i celami lidera ma w pasku własne, cele lidera w panelu.
- **Układ i teksty liczy jedna czysta funkcja** `buildKpiTopbarModel`
  (`kpi-topbar-model.ts`): kolejność segmentów jest stała (dzień, tydzień,
  miesiąc) i jest zarazem ważnością. Przycisk (`KpiTopbarButton`), panel
  (`KpiGoalsPanel`) i harness tylko rysują model — nowa reguła idzie do modelu
  i jego testu, nie do komponentu.
- **Znaczek tylko przy wyjątku:** kropka w kolorze ostrzeżenia = poniżej tempa,
  zielony znaczek = cel zrobiony, wyszarzona liczba = okres zamknięty. „W tempie”
  i „powyżej tempa” nie mają znaczka i wyglądają tak samo (do 13.10 jedna
  weryfikacja z czterech o 10:00 dostawała tarczę celu zrobionego). Bez emoji.
- **„Niepoliczony” i „celu jeszcze nie ma” to nie zero:** `current === null`
  pokazuje „niepoliczony” (w pasku „—”), a `state === null` albo `target <= 0`
  sam wynik i notatkę — nigdy „2/0”, „0%” ani pusty pasek postępu.
- **Panel otwiera kliknięcie** (Radix `Popover`, `role="dialog"`), nie najechanie
  ani sam fokus. W środku: grupy Dziś / Ten tydzień / Ten miesiąc, pasek
  z kreską tempa, zdanie o stanie, jedno zdanie „co się liczy” (`description_pl`
  z katalogu — pisz je dla człowieka, pokazuje je też edytor celów) i link do
  Insights. Nazwę przycisku dla czytnika ekranu buduje model ze wszystkich
  segmentów, także tych, które się nie zmieściły.
- **Pasek pokazuje tyle CAŁYCH segmentów, ile się mieści.** Przycisk zawija
  segmenty i ma wysokość jednego wiersza, więc nadmiarowy segment spada do
  ukrytego wiersza. Wyszukiwarka ma od 1280 px gwarantowane 220 px, przy
  1024–1279 px (menu jako szyna) 140 px — przy 220 px Head of Recruitment
  z rolą DL, Ligą DL i pigułką „Rozmowy” wypychał stronę w bok o 45 px przy
  1024 px (20.10.2026). Grupa akcji kurczy się przed okruszkami
  (`shell/topbar-layout.ts`). Zmierzone na
  harnessie 13.10.2026 (menu przypięte, z ikoną „Rozmowy”): rekruter przy
  1280 px widzi trzy segmenty na pulpicie, dwa na listach i jeden na ekranie
  rekrutacji; przy 1440 px dwa na ekranie rekrutacji; od 1536 px trzy wszędzie.
  Bez tego mechanizmu trzy segmenty zostawiały wyszukiwarce 109 px. Nie zastępuj tego progiem okna (`xl:`): okno nie wie, czy menu jest
  przypięte ani jak długie są okruszki. Kontener na `<header>` też odpada —
  panel dzwonka renderuje się w pasku bez portalu.
- **Sąsiedzi od 13.10.2026** (`liga-w-gornym-pasku.md`): przed licznikiem stoi
  przycisk Ligi Mistrzów, który się nie ściska (bez `data-topbar-shrinks`),
  a trzy przełączniki wyglądu (112 px) zastąpiło menu „Wygląd” (36 px).
  Liczby segmentów z akapitu wyżej są sprzed tej zmiany; po niej przy 1280 px
  Head of Recruitment i Delivery Lead widzą na pulpicie jeden segment zamiast
  dwóch, rekruter bez zmian, przy 1536 px bez zmian.
- **Mechanizm ma trzy warunki, każdy złapany pomiarem:** (1) w grupie akcji
  ściska się wyłącznie element z `data-topbar-shrinks` (licznik) — reszta dzieci
  dostaje `shrink-0` z klasy grupy; przycisk-ikona `w-9` bez `shrink-0` kurczył
  się z 36 do 22 px, więc nowa ikona w pasku nie potrzebuje własnej klasy;
  (2) segment ma `whitespace-nowrap` — z łamaniem tekstu najmniejsza szerokość
  przycisku była węższa niż segment i napis wystawał z ukrytego wiersza;
  (3) segmenty mają wysokość wiersza (`h-full`), a przycisk `content-start`.
  Pilnuje tego test e2e (`górny pasek — licznik celów`): wyszukiwarka ≥ 220 px,
  sąsiad 36 px, zero zawiniętych i wystających segmentów.
- **Forma zależy od okna tylko w dwóch miejscach:** poniżej 1024 px samo słowo
  „Cele”, do 1535 px skróty okresu („tydz.”, „mies.”) i krótszy podpis, od
  1536 px forma pełna z przedrostkiem „Zespół ·” w podpisie pierwszego
  segmentu (osobny segment „Zespół” zajmował w ciasnym pasku miejsce jedynego
  celu, który się mieścił). Wszystkie formy są w DOM
  naraz (jsdom nie liczy CSS) — testy sprawdzają tekst i klasy mechanizmu,
  układ sprawdza `e2e/responsive-preview.spec.ts` na `/preview/kpi-topbar`.
- **Pasek postępu** (`KpiProgressBar`) ma kolory z tokenów. Kreska tempa jest
  `span`-em obok toru: tryb Kids farbuje tęczą każdy `div` bezpośrednio
  w `[role="progressbar"]`.
- **„Poniżej tempa” dopiero, gdy brakuje całej sztuki**
  (`kpi_engine.derive_state`): `target × tempo − wynik ≥ 1` i wynik poniżej 80%
  oczekiwanego. Skutki: 0 z 4 o 9:01 i 10:00 jest „w tempie”, 1 z 4 o 13:15
  „poniżej”, a cel 1 (placement miesiąca) nie ma tempa wcale — jest „w tempie”,
  potem „zrobiony” albo „zamknięty”. Ta sama funkcja zasila cele zespołu
  (przy dużych sumach wynik jak dotąd) i przypomnienia coacha.
- **Cel Delivery Leada to jeden cel: 30% hit ratio.** Cel placementów =
  `ceil(rekrutacje zamknięte w kwartale × 30 / 100)` (10 zamkniętych = 3, 7 = 3,
  bo 2 z 7 to 28,6%); mnożenie przed dzieleniem. Oba wiersze mają jeden stan,
  liczony na liczbach całkowitych, bez tempa. Mianownik to te same rekrutacje
  zamknięte co w Lidze Mistrzów DL (`competitions.dl_portfolio_counts`);
  minimum 3 placementów zostaje warunkiem podium ligi i nie jest celem
  z licznika. Bez zamkniętych rekrutacji celu nie ma (`target 0`, `state null`,
  notatka).
- **Cel „Nowi kandydaci dziś” jest wycofany** (`kpi_catalog.WITHDRAWN_KPI_TITLES`).
  Wiersze tego celu zostały w `kpi_role_defaults` / `user_kpi_targets`, ale
  resolver (`kpi_targets`) nie pyta bazy o id spoza katalogu — bez tej zapory
  osierocony wiersz przywróciłby cel. Sama liczba „CV do bazy” zostaje jako
  statystyka (panel zespołu, mail tygodniowy, `/api/kpis/me/panel` dla roli
  z celami). Zamrożonych stałych migracji 0346 (`kpi_target_normalization.py`,
  `RETIRED_KPI_IDS`) nie ruszaj.
- **Nowe pola odpowiedzi są opcjonalne we froncie** (`short_title_pl`,
  `expected_count`, `expected`, `closed_requests`): karta otwarta przed
  wdrożeniem dostaje je z opóźnieniem, a model ma zapas z `title_pl`.
- Harness: `/preview/kpi-topbar` — repliki paska na całą szerokość okna (klasy
  z `topbar-layout.ts`, te same co w `TopbarV2`), stany dnia i panele trzech ról.

## Lista „Kto się liczy” za liczbami celów (17.10.2026)

Zgłoszenie Artura 17.10.2026: weryfikacje da się sprawdzić imiennie,
rekomendacji nie. Pomiar na produkcji (tydzień 12–17.10): 117 ze 137
rekomendacji (85%) kliknął ktoś inny niż osoba, której się liczą, a 137
rekomendacji to 121 osób. Decyzje D1–D7 przyjęte 17.10.2026, makiety:
https://claude.ai/artifact/X92X1KagSUsdb4EQ32F4Wv.

- **Jedna lista, nie druga.** Wiersze daje istniejąca trasa kafla
  „Aktywność rekrutacyjna” (`GET /api/dashboard/v2/recruitment-activity/details`,
  `services/recruitment_activity.py`) z tego samego `VERIFIER_ANCHORED_CTE` co
  licznik w pasku. Dla osoby i okresu celu `period_total` = liczba z paska —
  pilnuje tego `test_who_counts_list_equals_the_goal_counter`
  (`tests/test_kpi_canonical.py`). Nowej trasy do tej listy nie dokładaj.
- **Okna:** `day`, `week` (od poniedziałku wybranego dnia, jak cel tygodniowy),
  `month`, `range` (`date_from`–`date_to` włącznie, najwyżej 366 dni — okres
  z paska Insights). Placementy bez `day`.
- **Wiersz = para osoba × rekrutacja**, jak licznik (D3). Ta sama osoba
  w dwóch rekrutacjach to dwa wiersze ze znaczkiem „2 rekrutacje”, a
  podsumowanie mówi „23 rekomendacje · 21 osób”. Definicji celu to nie zmienia.
- **Kolumny:** osoba (profil), rekrutacja jak w nagłówku (`JobNameLabel`, link
  `/jobs/{id}?candidate={id}` otwiera panel tej osoby), godzina, kto kliknął
  etap (`moved_by` — wiersz etapu z chwilą z `credited`; przy „Zweryfikowany”
  po akceptacji to `approved_at`), „Liczy się” w zakresie zespołu i „Teraz”.
- **„Teraz” liczy serwer** z najnowszego wiersza etapu pary (`DETAIL_STATES`):
  zatrudnienie, odrzucenie przez klienta (`ended_by='client'` albo stary wiersz
  bez autora po wysyłce — ta sama reguła co `known_people_signal`), inne
  zakończenie, zamknięta rekrutacja, u klienta, czeka na klienta, przed
  wysyłką. Filtr `state` zawęża wiersze; liczniki stanów (`states`) liczą cały
  okres. Filtr „Klient odrzucił” to lista osób do ponownego kontaktu (D5).
- **Gdzie jest lista:** Insights → Mój miesiąc, panel „Kto się liczy do
  celów” (`MyWhoCountsPanel`, adres `?kto=…&okres=…&dzien=…`, kotwica
  `#kto-sie-liczy`); pod własnym celem w panelu z paska link „Zobacz, kto się
  liczy →” (tylko cele osoby z wynikiem > 0, cele zespołu i portfela bez linku);
  Insights → Zespół → Ludzie: liczby CV wysłane, rozmowy i placementy otwierają
  listę osoby w okresie z paska (`?kto=…&osoba=<id>`, „Wstecz” zamyka);
  kafel pulpitu — ten sam komponent `WhoCountsList`, z oknem „Tydzień”.
  Od 25.10.2026 także liczby lejka Zespół/Firma (`?kto=…&osoba=zespol`) i kafelek
  „Wyniki zespołu” → `finanse-insights/lista-za-liczba-lejka-i-wyniki-zespolu.md`.
- **Dostęp bez zmian (D5 z propozycji):** rekruter widzi swoją listę, role
  z `_TEAM_DETAIL_ROLES` każdą. Lider może otworzyć osobę spoza listy
  aktywnych rekruterów (`any_subject`) — tabela Zespół ma wiersze osób
  nieaktywnych i spoza ról KPI.
- **Konto bez wglądu w zespół** (np. „Automatyzacje”, 0446) bez osoby i bez
  `scope` dostaje 403, jak przy jawnym `scope=team` — do 17.10.2026 spadało do
  imiennej listy całego zespołu (przegląd bezpieczeństwa).
- **Podsumowanie mówi „pozostałe”, nie „przez kogoś innego”:** wiersz
  z importu nie ma autora ruchu (`moved_by` puste).
- **Zapytanie listy osoby idzie od początku okresu** (`myWhoCountsQuery`), a okres
  z dzisiejszym dniem nie ma `dzien` w adresie — jeden klucz pamięci zapytań
  dla wejścia z panelu celów i powrotu strzałką. Adres panel pisze od bieżącej
  ścieżki, bo ten sam widok stoi w harnessie `/preview/insights`.
- **„Bez osoby z zasługą” (D6):** kamienie z `credit_user IS NULL` mają wiersz
  w Zespół → Ludzie (`unattributed` w `/api/insights/team/people`, z
  `TeamTotals.unattributed_by_stage`) i zakres `scope=unattributed` listy.
  Bez niego suma osób nie zgadzała się z sumą firmy. Kamienie bez zasługi
  z etapów spoza tabeli (weryfikacje, QC, akceptacje) zostają w przypisie
  pod tabelą.
- Bez eksportu do Excela (D7) i bez przycisku „Otwórz w Kandydatach” (D5 B,
  następny krok, jeśli zespół zacznie z listy wracać do ludzi).
- Harness: `/preview/kpi-who-counts` (lista własna, lidera, zespołu, rama kafla 480 px).
- **„Sam przekazał” Delivery Leada (22.10.2026).** Fakty pod celami DL-a mają trzy
  wiersze: zweryfikowani, CV wysłane i zatrudnienia z tego miesiąca — procesy, które
  DL sam pierwszy przesunął na „Zweryfikowany” (ta sama atrybucja co „Moje KPI”,
  `kpi_panel.month_own_handoffs`, pole `own_handoffs` w `/api/kpis/me/goals`). To
  licznik, nie cel; przy samych zerach wiersze się nie pokazują. Kontekst: DL przesuwa
  bez blokad pól (`rekrutacja-tablica/dl-przesuwa-bez-blokad.md`).
