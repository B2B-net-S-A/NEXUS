# Decyzje wyglądu Nowego CV

<!-- indeks: decyzje W1–W33 i W36 układu `services/cv_new_layout/`, `tests/test_cv_new_layout_decisions.py`: logo i stopka, nagłówek T2, języki od B1, miasto, wyróżnik i wieniec tylko u góry, wyróżnik z propozycji AI tylko po przyjęciu, „Dlaczego” z liniami, pismo od 11 pt, odstęp 5,5 mm, oś po kolei S1, „Wcześniej”, Umiejętności z kreskami, Edukacja z ikonami, rok ukończenia, 3 certyfikaty, MUST pierwszy, tabele od str. 2, RODO na końcu, Poppins i Source Sans 3, Word wariant B -->

Zmiana którejkolwiek decyzji to zmiana tego pliku i jej testu w jednym PR-ze, za zgodą Artura.

Tu stoją decyzje Artura o wyglądzie układu „Nowe CV” (PDF i Word z
`backend/app/services/cv_new_layout/`), które obecny kod realizuje. Każdej pilnuje
test renderera w `backend/tests/test_cv_new_layout_decisions.py` — docstring testu
zaczyna się od identyfikatora decyzji, a test sprawdza wynik renderu (HTML strony,
SVG osi, raport dopasowania, PDF, Word), nie stałe w kodzie. Plik powstał, bo
decyzje wracały po kilku dniach przy okazji innych zmian; ostatni przykład to
wieniec w Edukacji (decyzja 25.11.2026, #3988).

Identyfikatory W1… to numery w tym pliku, nie nazwy wariantów z makiet (tam „W1”
to linie między zdaniami, „W8” — rysunek wieńca). Tło i reszta zasad (treść, trasy,
flagi): `nowe-cv-drugi-uklad-obok-klasycznego.md`. Testy W14–W16 i W33 potrzebują
WeasyPrint; bez bibliotek natywnych lokalnie są pomijane, jak `test_cv_new_layout_pdf.py`.

Źródła: „docs” = `nowe-cv-drugi-uklad-obok-klasycznego.md` (sekcja w nawiasie),
„makieta” = rundy makiet z 19–22.11.2026 w notatkach sesji
(`cv-layout-six-variants-mockups-2026-11-19`, `nowe-cv-runda-37-2026-11-25`).

## Nagłówek, stopka, kroje

- **W1** — Nagłówek strony to samo logo, bez hasła, maila i adresu strony; stopka to
  wyśrodkowane dane spółki. 20.11.2026, makieta (rundy 21 i 25), #3714.
  Test: `test_w01_header_is_the_logo_and_footer_the_company_data`.
- **W32** — Kroje: Poppins (tytuł, etykiety, nagłówki) i Source Sans 3 (tekst strony 1),
  z plików w repo. 20.11.2026, makieta (runda 16, zestaw P3), #3714.
  Test: `test_w32_poppins_and_source_sans_3_only`.

## Strona 1: tytuł, pastylki, wyróżnik

- **W2** — Nagłówek T2: stanowisko duże i czerwone (19 pt), pod nim cienka linia
  i imię z nazwiskiem (12 pt); bez myślnika i bez napisu „Kandydat na stanowisko”.
  CV Blind: samo stanowisko. 23.11.2026 i 25.11.2026, docs („Strona 1 po
  warsztatach”, „Strona 1, runda 37”), #3792, #3965.
  Test: `test_w02_title_is_the_position_with_the_name_under_a_thin_line`.
- **W3** — Języki w pastylkach obok tytułu, tylko od B1: A1, A2, „podstawowy” i „basic”
  znikają, opis bez poziomu („komunikatywny”) zostaje; „ojczysty lub dwujęzyczny”
  i „native” to „ojczysty”, „C1/C2” zostaje w całości. 20.11.2026 (makieta, rundy
  12, 25, 27) i 23.11.2026, docs („Strona 1 po warsztatach”), #3792.
  Test: `test_w03_language_pills_only_from_b1`.
- **W4** — Miasto kandydata w pastylce z pinezką obok języków: „, PL” obcięte, inny kraj
  zostaje kodem; bez miasta albo w CV Blind — bez pastylki. 23.11.2026, docs
  („Strona 1 po warsztatach”), #3792. Test: `test_w04_city_pill_with_pin`.
- **W5** — Wyróżnik stoi między nazwiskiem a „Dlaczego nasz kandydat”: wieniec ze
  znakiem, etykieta i jedno zdanie, bez ramki i tła. 25.11.2026, docs („Strona 1,
  runda 37”), #3965.
  Test: `test_w05_highlight_under_the_name_without_frame_or_background`.
- **W6** — Wyróżnik automatyczny to praca u klienta rekrutacji: etykieta „Doświadczenie
  w {klient} · rok–rok”, zdanie z dat i stanowiska bez dopowiadania, w wieńcu nazwa
  klienta do 8 znaków, inaczej staż; nigdy „Zna klienta od środka”. CV Blind i tryb
  „off” — bez wyróżnika, „custom” — słowa rekrutera. 25.11.2026, docs („Strona 1,
  runda 37”), #3965. Test: `test_w06_automatic_highlight_is_work_at_the_client`.
- **W36** — Wyróżnik ma trzy źródła: praca u klienta automatycznie, propozycja AI tylko
  po przyjęciu przez rekrutera, albo wpis rekrutera. Propozycja AI (nagroda, wyróżnienie,
  certyfikat z MUST, każda z cytatem z CV sprawdzonym kodem) sama nie trafia na stronę 1:
  render bierze wyłącznie `page1_extras.highlight`, tryb „ai” zapisuje „Przyjmij”
  rekrutera, a przyjęta wygrywa z automatem tak jak wpis rekrutera. 26.11.2026 (Artur:
  „wyróżnik może też być to, co AI zaproponuje, lub rekruter sam wpisze i zdecyduje”),
  docs („Wyróżnik z propozycji AI”).
  Test: `test_w36_ai_highlight_only_after_the_recruiter_accepts_it`.
- **W7** — Wieniec tylko u góry: na stronie jest najwyżej jeden, wyłącznie przy
  wyróżniku; bez wyróżnika strona nie ma wieńca, Edukacja nigdy, a stary wpis
  `page1_extras.wreath` nie zmienia renderu. 25.11.2026 („Tylko u góry, Edukacja
  zawsze z ikonami”), docs („Strona 1, runda 37”), #3988.
  Test: `test_w07_wreath_only_next_to_the_highlight`.

## Strona 1: „Dlaczego nasz kandydat”

- **W8** — Najwyżej trzy zdania, bez punktorów, oddzielone cienkimi liniami poziomymi.
  23.11.2026, docs („Strona 1 po warsztatach”), #3792.
  Test: `test_w08_why_has_three_sentences_without_bullets_between_thin_rules`.
- **W9** — Liczby i fakty w zdaniach tylko pogrubione: bez większego kroju i bez
  czerwieni. 20.11.2026, makieta (rundy 13, 14 i 18).
  Test: `test_w09_numbers_in_why_are_only_bold`.
- **W10** — Zdania rosną razem z pismem strony 1. 25.11.2026, docs („Strona 1, runda
  37”, wypełnienie kartki), #3965. Test: `test_w10_why_grows_with_the_page_font`.

## Strona 1: kolejność, etykiety, wypełnienie kartki

- **W11** — Kolejność: tytuł z językami i miastem, wyróżnik, Dlaczego, Przebieg kariery,
  Umiejętności, Edukacja. 20.11.2026 (makieta, runda 5) i 25.11.2026 (wyróżnik),
  #3965. Test: `test_w11_page1_order`.
- **W12** — Nagłówek sekcji to biały napis na czerwonej etykiecie i czerwona linia do
  prawej krawędzi („miały być z paskiem”). 20.11.2026, makieta (runda 25).
  Test: `test_w12_section_labels_are_red_tags_with_a_rule_to_the_edge`.
- **W13** — Stały odstęp 5,5 mm nad każdą sekcją, także gdy wolne miejsce rozsuwa
  sekcje („nie może się zlewać”). 25.11.2026, docs („Strona 1, runda 37”), #3965.
  Test: `test_w13_fixed_gap_above_every_section`.
- **W14** — Pismo strony 1 od 11 pt w dół: mało treści dostaje 11 pt, nie dziury;
  10–11 pt to wypełnianie kartki, a nie skrócenie w komunikacie dla rekrutera.
  25.11.2026, docs („Strona 1, runda 37”), #3965.
  Test: `test_w14_page1_font_goes_down_from_11_pt`.
- **W15** — Wolne miejsce strony 1: około połowy w środek sekcji (odstępy zdań, wierszy,
  osi), reszta równo między sekcje. 20.11.2026 (makieta, runda 23: równe rozłożenie)
  i 25.11.2026, docs („Strona 1, runda 37”), #3965.
  Test: `test_w15_free_space_half_inside_sections_rest_between_them`.
- **W16** — Strona 1 zawsze na jednej kartce A4: najpierw mniejsze pismo (do 9 pt),
  dopiero potem krótsze listy umiejętności z „+N” i pełną listą na str. 2.
  20.11.2026 (makieta, reguła długiego CV; „zawsze mniejsze pismo” odrzucone)
  i 22.11.2026, docs („Zasady”), #3714.
  Test: `test_w16_page1_always_fits_font_first_then_shorter_lists`.

## Strona 1: przebieg kariery

- **W17** — Oś po kolei, nie w skali czasu: każdy pracodawca ma miejsce na pełną nazwę,
  roczna praca nie jest kreską obok dziewięcioletniej, odcinki wypełniają całą
  szerokość bez przerw. 25.11.2026 (wariant S1), docs („Strona 1, runda 37”), #3965.
  Test: `test_w17_career_axis_in_order_not_in_time_scale`.
- **W18** — Nad odcinkiem pełna nazwa firmy (bez formy prawnej i branży dopisanej
  w edytorze, nigdy „…”), pod nim rok rozpoczęcia i stanowisko; bieżąca praca
  czerwona, na końcu „dziś”. 21.11.2026 (makieta, runda 31) i 25.11.2026, docs
  („Strona 1, runda 37”), #3965.
  Test: `test_w18_full_company_above_start_year_and_position_below`.
- **W19** — Kolejne krótkie zlecenia (krótsze niż 9 mies.) jednym odcinkiem „A · B · C”,
  pod nim „3 krótkie projekty”. 25.11.2026, docs („Strona 1, runda 37”), #3965.
  Test: `test_w19_consecutive_short_jobs_share_one_segment`.
- **W20** — Najwyżej 7 odcinków; najstarsi w jednym jasnym odcinku „Wcześniej ·
  N stanowisk”, pod nim „m.in.” dwie najdłuższe firmy. Okno 10 i 12 lat odrzucone:
  gdy pracodawcy się mieszczą, oś zaczyna się od pierwszej pracy. 20.11.2026
  (makieta, runda 18) i 25.11.2026, docs („Strona 1, runda 37”), #3965.
  Testy: `test_w20_at_most_seven_segments_oldest_as_earlier`,
  `test_w20_no_ten_or_twelve_year_window`.
- **W21** — Na osi tylko główna ścieżka: stanowisko w całości w innym to projekt
  równoległy (opis od str. 2); kolejne stanowiska w tej samej firmie to jeden
  odcinek, także po przerwie. 20.11.2026 (makieta, rundy 20 i 30), #3974.
  Test: `test_w21_only_the_main_path_and_one_segment_per_employer`.
- **W22** — CV bez bieżącej pracy: oś kończy się rokiem ostatniej pracy, bez „dziś”.
  20.11.2026, makieta (runda 29, wariant KV1).
  Test: `test_w22_without_current_job_the_axis_ends_with_the_last_year`.

## Strona 1: umiejętności

- **W23** — Umiejętności jako indeks: kategoria po lewej, pozycje rozdzielone pionowymi
  kreskami; pozycje z rekrutacji pogrubione w swojej kategorii, bez osobnego wiersza
  „Kluczowe dla tej rekrutacji”. 20.11.2026, makieta (rundy 12, 13 i 24).
  Test: `test_w23_skills_index_with_bars_and_bold_keys_in_place`.
- **W24** — Nadmiar pozycji kategorii jako „+N” z dopiskiem, pełna lista umiejętności
  na str. 2. 20.11.2026 (makieta, runda 12), docs („Zasady”).
  Test: `test_w24_overflow_as_plus_n_with_the_full_list_on_page2`.

## Strona 1: edukacja

- **W25** — Edukacja zawsze w dwóch kolumnach z ikonami (biret przy „Wykształceniu”,
  odznaka przy „Certyfikatach i szkoleniach”): kierunek, stopień · rok, uczelnia;
  certyfikat, wystawca · rok — z wyróżnikiem i bez niego. 25.11.2026 (wariant ED),
  docs („Strona 1, runda 37”), #3988.
  Test: `test_w25_education_always_two_columns_with_icons`.
- **W26** — Przy szkole tylko rok ukończenia, bez dat studiów od–do. 20.11.2026
  (makieta, runda 17) i 25.11.2026 (stopień · rok), #3965.
  Test: `test_w26_school_shows_the_graduation_year_only`.
- **W27** — Na stronie 1 najwyższe ukończone wykształcenie (przerwane studia się nie
  liczą); pozostałe szkoły w pełnej tabeli na końcu CV, na stronie 1 dopisek
  „+ N szkoły — pełna lista na końcu CV”. 20.11.2026, makieta (reguła długiego CV).
  Test: `test_w27_highest_finished_school_on_page1_the_rest_at_the_end`.
- **W28** — Najwyżej 3 certyfikaty na stronie 1, reszta w pełnej liście na końcu CV;
  liczba w „Certyfikaty i szkolenia · N” to wszystkie. 20.11.2026 (makieta, runda 29)
  i 23.11.2026, docs („Strona 1 po warsztatach”).
  Test: `test_w28_at_most_three_certificates_on_page1`.
- **W29** — Na stronę 1 idą certyfikaty najważniejsze dla roli, nie najnowsze;
  certyfikat z wymagań MUST klienta stoi pierwszy, kurs ani umiejętność się nie
  liczą. 20.11.2026 (makieta, runda 29), 23.11.2026 i 25.11.2026, docs („Strona 1
  po warsztatach”), #3988.
  Test: `test_w29_most_relevant_certificates_and_client_must_first`.

## Od strony 2 i Word

- **W30** — Od strony 2 każde stanowisko jako tabela-formularz (Okres, Nazwa firmy,
  Stanowisko, Zakres zadań, Technologie); puste pola znikają, tabela nie dzieli się
  między strony. 20.11.2026, makieta (runda 3, wersja „R1 v2”), #3714.
  Test: `test_w30_roles_from_page2_are_form_tables_without_empty_rows`.
- **W31** — Zrzut zgody i klauzula RODO na samym końcu CV, zrzut przed klauzulą.
  22.11.2026, `zrzut-zgody-rodo-na-koncu-cv-wymog-pko-bp.md`, #3714.
  Test: `test_w31_consent_and_rodo_close_the_cv`.
- **W33** — Word „Nowego CV” (wariant B): strona 1 to obraz strony 1 PDF, od strony 2
  tekst i tabele Worda, Poppins osadzony w pliku. 25.11.2026, docs („Word Nowego
  CV”), #3991. Test: `test_w33_word_page1_is_the_pdf_image_then_editable_tables`.

## Zastąpione — nie przywracać

Te warianty Artur wybrał wcześniej, a potem zastąpił decyzjami wyżej:

- oś w skali lat, okno 10 lub 12 lat, flagi i paski z „//” (A1, A4, Q1 z 20–23.11)
  i przerwy „przerwa” na pasku (20.11) — zastąpione osią po kolei (W17–W20, 25.11);
- wieniec przy dyplomie (20.11) i wybór wieńca w Edukacji (E4, 23.11) — zastąpione
  W7 i W25 (25.11);
- pismo strony 1 do 10 pt (20.11) — zastąpione W14 (25.11);
- stopień czerwoną etykietą nad kierunkiem (EH1) i certyfikat bez wystawcy na
  stronie 1 (CE1, 20.11) — zastąpione Edukacją z ikonami (W25, 25.11);
- Word zawsze klasyczny (22.11) — zastąpione W33 (25.11), klasyczny Word zostaje jako
  „Word (klasyczne)”.
