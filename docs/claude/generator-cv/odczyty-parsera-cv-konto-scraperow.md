# Odczyty parsera CV: 86% robi konto scraperów i są potrzebne

Pomiar 22.11.2026 (produkcja, `ai_operations` z `feature = 'cv_parser'`, 30 dni
od 24.10). Zrobiony przed decyzją Artura o trybie wsadowym parsera, bo pomiar
z 16.11 pokazał jedno konto z prawie wszystkimi odczytami.

- To konto integracji klienta OAuth „Scrapery pracuj.pl + JJIT”
  (`oauth_clients.acting_user_id`): rola TCM, bez hasła, nigdy nie zalogowane.
  Nie człowiek, nie nocny przegląd bazy, nie auto-match, nie backfill, nie Traffit.
  Ma 5647 z 6569 odczytów (86%), drugi jest `system` (570), ludzie po kilkadziesiąt.
- Dwie trasy, obie z mapy `services/oauth_route_scopes.py`:
  - `POST /api/candidates/from-cv` (`create_candidate_from_cv`), odczyt
    w `_read_cv_for_new_candidate` → nowy kandydat. 2588 odczytów (46%).
  - `POST /api/candidates/{id}/cv` (`upload_cv`), odczyt w tle
    w `_enrich_candidate_from_document_task` → nowa wersja CV w istniejącym
    profilu. Reszta.
- Powtórki tego samego pliku są już ucięte. Do 02.11 każde wgranie szło do modelu
  (24.10–02.11: 2329 odczytów ≈ 978 nowych + 1348 wgrań). Od 03.11
  `profile_holds_read_of_file` pomija plik, którego odczyt profil już ma:
  03–22.11 4336 wgrań do istniejących profili dało ok. 1708 odczytów, 2628 poszło
  bez modelu. Doba 21–22.11 z logów `http_outcome`: 229 wgrań, 162 bez modelu
  (praca w tle < 2 s), 66 z odczytem; `from-cv` 73 żądania, 2 × 409.
- Co zostało, to nowe pliki. 03–22.11 konto dodało 1615 nowych wierszy CV do
  istniejących profili, 1606 z nich ma wcześniejsze CV o innych bajtach. Ten sam
  rozmiar pliku co poprzednie CV (możliwy ten sam dokument wygenerowany ponownie)
  ma 96 (6%). 2924 osoby dostały od konta jedno CV, 242 dwa lub więcej, a wśród
  nich tylko 6 plików o powtórzonym rozmiarze.
- Odczyt bez efektu w profilu (409 po płatnym odczycie, błąd) to ok. 3%:
  3318 odczytów 03–22.11 minus 1610 nowych kandydatów minus 1615 nowych CV.
- Wniosek: ograniczanie konta scraperów nie obniży kosztu bez gubienia nowych
  kandydatów albo nowych wersji CV. Kod bez zmian. Koszt odczytów konta
  03–22.11 ok. 117 USD, czyli ok. 175 USD na 30 dni.
- Decyzja o trybie wsadowym zostaje dla Artura. Wsad mógłby objąć tylko drugą
  trasę, bo na nowym kandydacie odczyt jest potrzebny od razu do reguły telefon +
  imię i nazwisko (`from-cv`, krok 3b).
