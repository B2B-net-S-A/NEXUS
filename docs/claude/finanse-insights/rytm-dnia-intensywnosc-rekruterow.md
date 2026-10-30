# Rytm dnia i intensywność pracy rekruterów (Insights → „Rytm dnia”)
<!-- indeks: tylko HoR i admin, punkty pracy za akcję, poziomy godziny, intensywność 0–100, urlop i dni przed kontem poza wskaźnikiem, podpowiedź intensywność × CV do klienta, reguły w app_settings, ochrona przed nabijaniem, rozkład dnia po kliknięciu, bez czasu pracy i minimum 8 h (30.10), porównanie z zespołem, przerwy, Wzorce, Trend -->

Decyzje Artura z 28–30.10.2026 (makiety w prywatnych artefaktach
`S7Hx8KFo1FLfv255MgQHKg` i — dla zmian z 30.10 — `EvTdh71Em61RPojCjKfeUw`). Zakładka pokazuje, kiedy i jak intensywnie
rekruterzy pracują w NEXUSIE, godzina po godzinie, i zestawia to z wynikami:
dużo pracy i słabe wyniki = trzeba pomóc z jakością, mało pracy i słabe
wyniki = trzeba pracować więcej.

- **Kto widzi:** na razie tylko Head of Recruitment i admin (29.10.2026; dzień
  wcześniej padło „widzi cały zespół” — zmienione). Lustro ról:
  `VIEWER_ROLES` w `services/work_rhythm.py` i `RHYTHM_ROLES`
  w `InsightsView.tsx`. Ci sami zmieniają reguły („Zmień reguły”).
- **Kogo pokazujemy:** każdy aktywny z rolą rekrutera, także Delivery Lead
  z dopisanym rekruterem (29.10.2026; dzień wcześniej „bez DL-i” — zmienione).
  Sam TCM bez roli rekrutera, HoR i admin nie są wierszami. Bez formy współpracy. Konto, w imieniu którego działa
  integracja (`oauth_clients.acting_user_id`), nie jest człowiekiem — pomijamy.
- **Od 12.10.2026** (start pracy w NEXUSIE, `RHYTHM_START`); okno to 10 dni
  roboczych, najwyżej 31 dni.
- **Punkty pracy za akcję** (wagi w ustawieniach): screening 5, rozmowa u
  klienta / feedback / prep 3, wygenerowane CV 3, notatka, dodany kandydat,
  finalizacja CV 2, próba kontaktu („nie odbiera”) 1, ruch karty, mail, QC CV,
  inny zapis 1, podgląd CV 0,5.
  Zero: autozapis edycji CV, odpowiedzi formularza (dublują screening), Jarvis,
  notatki systemowe (`system`, `card_note_import`, `qc_confirmation`,
  `teams_prep`), wpisy automatów (`_SKIPPED_ACTIONS`). Ten sam rodzaj zapisu
  u ≥ 5 osób w tej samej minucie to import (staging 20.10.2026 20:24: 66
  rozmów u klienta i 66 feedbacków naraz) — nie liczy się.
- **Ochrona przed nabijaniem** (29.10.2026, `classify_events`; limity
  w ustawieniach, 0 = bez limitu). Na kopii stagingu 12–22.10 zdejmuje 25%
  punktów zespołu, wskaźnik spada o 0–14; pięć sposobów nabijania (8 podglądów
  na godzinę, ten sam formularz w kółko, „nie odbiera” bez dzwonienia, karty
  tam i z powrotem, masowe dodanie) spada z > 60/100 do < 10:
  CV z automatu (`origin = 'auto'`) 0 pkt — ruch karty, który je uruchomił, już
  się liczy (62% CV na kopii); screening tego samego kandydata raz dziennie;
  inny zapis tej samej rzeczy raz na godzinę (autozapis karty rekomendacji,
  poprawki CV z AI); podglądy: ten sam dokument raz na godzinę, najwyżej 4
  w godzinie; ≥ 10 takich samych zapisów jednej osoby w minutę = jedna akcja;
  powrót karty na etap, na którym już była tego dnia, 0 pkt; najwyżej 10 prób
  kontaktu dziennie. Godzina z samych drobnych akcji przy < 2 kandydatach nie
  jest godziną pracy (screening, krok u klienta i CV wystarczą same).
  Odpadłe akcje zostają w rozkładzie dnia z powodem.
- **Rozkład dnia:** kliknięcie osoby (Dzień) albo daty (2 tygodnie) →
  `GET /api/insights/work-rhythm/day` — każda akcja z godziną, kandydatem,
  punktami albo powodem, dla którego nic nie dała. Import wielu osób naraz
  rozpoznajemy po całym zespole, więc zdarzenia dnia pobieramy dla wszystkich.
- **Bez czasu pracy i bez minimum 8 h** (decyzja Artura 30.10.2026, cofa
  „czas pracy” i minimum 8 h z 29.10). Akcje w NEXUSIE nie mierzą obecności:
  telefon, rozmowa czy LinkedIn wyglądają jak cisza, więc „czas pracy” z odcinków
  między akcjami wychodził zakłamany (osoba pracująca 08:31–16:27 miała 2 h 43).
  Nie wracaj do liczenia godzin, minimum ani bramki intensywności z godzin.
  Zamiast tego: **aktywne godziny** (kropki wobec normy `norm_active_hours`,
  domyślnie 8 — to norma do wzoru intensywności, nie minimum) i **przerwy**
  (`day_gaps`): pełna godzina bez akcji i bez prepa między pierwszą a ostatnią
  aktywną godziną. Przerwa jest widoczna na heatmapie i niczego nie odejmuje.
  Stare pola `min_work_hours` i `break_minutes` w zapisanych regułach są
  ignorowane.
- **Porównanie z zespołem** (Dzień): wiersze od najwyższej intensywności,
  kreska mediany zespołu na pasku i różnica „vs zespół”. Mediana
  (`team_day_index`) liczy tylko osoby, które tego dnia pracowały w NEXUSIE.
- **Wzorce** (typowy dzień): średnie punkty w każdej godzinie z pełnych dni
  okna — bez urlopu, dnia przed kontem i dzisiejszego dnia, od 3 dni
  (`person_pattern`). Rozkręca się = mediana pierwszej aktywnej godziny,
  szczyt, % punktów 8–12 wobec 8–18 (≥ 40% poranny, ≤ 20% popołudniowy),
  regularność startu (odchylenie). Pierwszy wiersz to mediana zespołu.
- **Trend** (zastąpił widok „Intensywność”; stary adres `widok=intensywnosc`
  prowadzi do Trendu): średnia intensywność 5 ostatnich zakończonych dni
  roboczych okna wobec 5 wcześniejszych (`trend_periods`, `person_trend`);
  ±5 to szum. Zostały tu kolumny wyników i podpowiedź dla lidera.
- **Poziom godziny** z progów `hour_levels` (domyślnie 4 / 11 / 25 pkt =
  kwartyle zespołu od 12.10). **Godzina intensywna** = ≥ 4 pkt albo prep ustawiony
  z NEXUSA (`prep_meetings`) ≥ 30 min w tej godzinie, liczona 8:00–18:00. Inne
  wpisy M365 się nie liczą (29.10.2026): od 12.10 to ok. 12,5 tys. cyklicznych
  „Spotkań” bez uczestników, czyli blokad kalendarza.
- **Intensywność dnia (0–100)** = ½ × godziny intensywne / `norm_active_hours` (8) + ½ × punkty dnia /
  120, każda część najwyżej 1. Okres = średnia z dni pracy. Dzień urlopu
  (`person_workdays.absence_by_user`) i dni przed założeniem konta nie liczą
  się wcale; pół dnia urlopu obniża obie normy o połowę. L4 nie ma
  w kartotece — dzień zwolnienia wygląda jak dzień bez pracy.
- **Podpowiedź dla lidera** (bez godzin, 30.10.2026): intensywność ≥ 60
  i CV do klienta ≥ 80% mediany zespołu → wzór; intensywnie i mało CV →
  „pomóż z jakością”; mało akcji, a wynik dobry → „wynik przy niskiej
  intensywności” (zapytaj, co działa poza NEXUSEM); mało akcji i słaby wynik
  → „za mało pracy”. Wykres: intensywność × wyniki. Sygnał
  prowadzi do rozmowy, nigdy wprost do sankcji. CV do klienta z migawki
  `credited` (`credited_bind` zawężone do etapu i okna), nie z własnego CTE.
- **Reguły** trzyma `app_settings['work_rhythm_rules']`; brak wpisu =
  `DEFAULT_RULES`, brakujące pole = wartość domyślna. Zakresy i rosnące progi
  pilnuje `WorkRhythmRulesIn` (422 z komunikatem po polsku). Cache odpowiedzi
  ma w kluczu skrót reguł, więc zmiana działa od razu.
- **Nie widać:** rozmów z telefonu (CloudTalk wyłączony) i pracy na LinkedIn
  poza wtyczką. Wpis rozmowy do wskaźnika Artur odrzucił 28.10.2026.
