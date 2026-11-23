# „Klient coś zmienił”: zmiana od klienta w Profilu Championa jednym oknem (23.11.2026)
<!-- indeks: POST …/champion-profile/client-change[/apply], services/champion_client_change.py, ClientChangeDialog, ?client_change=1, Jarvis propose_client_change, skutki dla osób w procesie, dzwonek „dopytaj” -->

Zgłoszenie DL-a 23.11.2026 („edytuj (AI)”: klient nagle wymaga Pythona, a zmiana
w wymaganiach, opisie i pytaniach to kilka osobnych szuflad). Decyzja Artura po
makietach (https://claude.ai/artifact/8LzfUqcUmrivAN2RRz6V8F): wariant A
(okno z listą zmian) + Jarvis jako drugie wejście, skutki dla osób w procesie
od pierwszej wersji. Dowód: od 18.11 14 wersji profilu w 10 rekrutacjach,
442079 zapisana 4 razy w 25 min, 789239 — DL ręcznie +3/−3 pytania.

- **Wejścia**: przycisk „Klient coś zmienił” przy zakładkach Profilu, menu „⋯ →
  Klient coś zmienił…” i karta Jarvisa „Pokaż i popraw”. Wszystkie prowadzą do
  `?client_change=1`; Jarvis zostawia treść w `sessionStorage`
  (`stashClientChangeText`), okno czyta ją raz i od razu prosi o propozycję.
  Widzi je ten, kto może edytować Profil (`ensure_champion_job_editor`).
- **Propozycja nic nie zapisuje** (`POST …/client-change`). Model z rejestru
  (`champion_draft`, prompt `CHAMPION_CLIENT_CHANGE`) oddaje operacje na blokach
  z cytatem z treści. Wynik modelu to dane z zewnątrz: `clean_changes` sprawdza
  każdą operację przeciw obecnemu profilowi (wiersz do usunięcia musi istnieć,
  pytanie po `question_id`, pola tekstowe tylko z `TEXT_FIELDS`, limity długości,
  najwyżej 20 zmian). Awaria modelu = 200 ze `status: failed`; DL ma zawsze „Edytuj”.
- **Krytycznych okno nie ustawia** — poziom to „musi mieć” albo „mile widziane”.
  Krytyczne DL wybiera świadomie w edytorze wierszy (próg 20 osób, bramka).
  Zdanie wpisane jako wiersz przenosi do rozmowy zwykły zapis (`separate_talk_items`).
- **Zapis to jeden zwykły zapis profilu** (`…/client-change/apply` →
  `_save_champion_profile` z `expected_profile_hash`): wersja w „Zmiany”, karta
  „Co się zmieniło” i dzwonki Championa jak zawsze. Zmiany odesłane przez front
  (także poprawione) przechodzą `clean_changes` jeszcze raz. Zdanie dla
  rekruterów (napisane przez AI, do zmiany) trafia do wersji od razu, więc okno
  „Na co klient kładzie nacisk?” się nie otwiera. Profil zmieniony w międzyczasie
  = 409 i powrót do treści.
- **Skutki** (`process_gaps`): dla nowego albo podniesionego wymagania „musi mieć”
  liczba osób w otwartych procesach bez tego słowa w CV (treść CV albo
  umiejętności — przybliżenie „Szukaj w CV”), w podziale przed screeningiem /
  po screeningu / u klienta. „W bazie” liczy front tym samym licznikiem co
  edytor wierszy. Dzwonek „dopytaj” (domyślnie zaznaczony) idzie do osób
  prowadzących kandydatów po screeningu i u klienta (bez osoby — do rekrutera
  rekrutacji), jeden na osobę, autor zmiany go nie dostaje.
- Inwentarz: `champ.client-change`. Testy: `tests/test_champion_client_change.py`,
  `tests/test_jarvis_client_change.py`, `ClientChangeDialog.test.tsx`,
  `champion-client-change.test.ts`, `jarvis-client-change.test.tsx`.
