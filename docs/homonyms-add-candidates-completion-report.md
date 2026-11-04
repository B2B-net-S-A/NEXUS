# Imiennicy w oknie „Dodaj kandydatów do pipeline” — raport

Gałąź `claude/candidate-phone-number-display-ea34ef`, 13.10.2026. Reguły:
`docs/claude/rekrutacja-tablica/imiennicy-w-oknie-dodawania.md`. Makiety i decyzje D1–D6:
https://claude.ai/artifact/UidzDHHjGHMDuutb4zB21L (Artur: „tak na D1–D6, wdrażaj”).

## Skąd ta zmiana

Rekruter: przy dodawaniu kandydata po nazwisku nie da się odróżnić kilku osób o tym samym imieniu
i nazwisku — prośba o telefon w wierszu. Pomiar na produkcji 13.10.2026 (tylko odczyt, same liczby):

| Co | Liczba |
|---|---|
| Kandydaci z imiennikiem w bazie | 9 527 z 65 783 (14,5%), 3 901 grup |
| — z telefonem / z e-mailem | 91% / 89% |
| — bez telefonu i bez e-maila | 609 |
| Grupy, w których każdy ma inny numer | 2 810 |
| Grupy z tym samym numerem na dwóch rekordach | 700 |

Do tego przegląd kodu pokazał, że okno chowa każdego z kartą w tej rekrutacji — także odrzuconego —
więc przy imienniku właściwa osoba mogła zniknąć z wyników i rekruter dodawał drugą.

## Co się zmieniło

### Serwer (`POST /api/search/candidates`, tylko z `exclude_in_job_id`)

- `in_job_matches` — przy frazie dosłownej (imię i nazwisko, telefon, e-mail) i dostępie do rekrutacji:
  do 5 osób z tą samą frazą i filtrami, które mają kartę w tej rekrutacji, z etykietą karty; przy karcie
  zamkniętej cel ruchu „Przywróć” (`proposals_bulk.in_job_cards`, ta sama reguła co `closed_card_skip`).
- `last_recruitment` na każdym wierszu — ostatni ruch karty w innej rekrutacji, w zakresie rekrutacji
  widocznych dla pytającego, jedno zapytanie na stronę.
- `services/candidate_job_cards.py` — wspólne zapytanie „bieżąca karta osoby” (`latest_cards`);
  `proposals_bulk._closed_cards` korzysta z niego bez zmiany zachowania.

### Okno (`AddCandidatesQuickModal`)

- D1: druga linia — telefon, e-mail, miasto („brak telefonu”, „brak e-maila”); „Profil” w nowej karcie
  poza przyciskiem wiersza.
- D2: pasek „N osób o imieniu i nazwisku …”, gdy są imiennicy (wyniki + osoby w rekrutacji).
- D3: pole „Imię i nazwisko, telefon albo e-mail…”, linia „Szukam po numerze telefonu” / „po adresie
  e-mail”, podświetlony pasujący numer.
- D4: sekcja „Już w tej rekrutacji (N)”: karta w toku z etapem, zamknięta z „Przywróć do „Nowych””
  (ruch karty, nie drugie dodanie).
- D5: trzecia linia w jednym wierszu — „ostatnio MM.RRRR: etap · rekrutacja” albo „jeszcze w żadnej
  rekrutacji, dodany MM.RRRR”.
- D6: „Ten sam telefon co N. wiersz” / „…co osoba już w tej rekrutacji” (porównanie po 9 cyfrach, jak
  wyszukiwanie po telefonie); admin i Head of Recruitment mają „Scal…” (`CandidateMergeDialog`).
- Harness `/preview/add-candidates` (dane fikcyjne), wpisy w `recruitment-feature-inventory.json`.

## Weryfikacja

- Backend: `ruff check`/`format` czyste; testy etykiet `test_proposals_bulk.py -k label` lokalnie zielone;
  nowy `tests/test_search_candidates_in_job_matches.py` (5 testów z bazą) — w CI.
- Frontend: `tsc --noEmit` czysty; vitest: 27 testów okna i reguł imienników, razem z harnessami,
  middleware, inwentarzem i `AddToRecruitmentDialog` — 756 zielonych.
- Przeklikane w harnessie 1280 × 720 (jasny i ciemny motyw): wiersze z trzema liniami, pasek
  imienników, sekcja „Już w tej rekrutacji” z „Przywróć”, szukanie po numerze, „Scal…” otwiera okno
  scalania nad oknem dodawania, Escape zamyka tylko scalanie. W 1280 × 720 widać trzy osoby
  i początek sekcji bez przewijania (wcześniej ok. sześć jednolinijkowych wierszy).

## Poza zakresem / niepotwierdzone

- Ile imienników ma wypełnione miasto i tytuł z LinkedIna — drugie zapytanie na produkcji zablokowało
  narzędzie uprawnień.
- Grupa 290 rekordów o jednym imieniu i nazwisku — najpewniej zastępcze imię z importu, niesprawdzone.
- Przeklikanie na zalogowanej produkcji — po wdrożeniu, jeśli dostępna będzie zalogowana przeglądarka.
