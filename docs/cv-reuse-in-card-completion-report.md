# „Użyj innego CV” w karcie „CV do klienta” — raport

Gałąź `claude/cv-file-upload-option-d1d2d1`, 12.10.2026. Bez migracji bazy.

## Skąd zmiana

Zgłoszenie rekrutera: „Potrzebna opcja tutaj: wgraj plik CV. Mam już gotowe CV, a generator zrobił mi od nowa
i musiałbym znowu 10 CV poprawiać. Dobrze by było móc skorzystać ze starej i ją ewentualnie edytować.”

Karta „CV do klienta” w panelu osoby dawała tylko „Wygeneruj ponownie”. Wybór gotowego CV istniał od 09.10.2026,
ale wyłącznie w podglądzie screeningu, gubił ręczne poprawki (kopia z innej rekrutacji renderowała wynik generatora
od nowa) i odmawiał u klienta z wymogiem zrzutu zgody RODO (422).

Pomiar na produkcji 12.10.2026 (tylko odczyt, same liczby):

| Co policzono | Wynik |
|---|---|
| auto-CV z ostatnich 14 dni | 22 |
| …z tego dla osób, które miały już jakieś gotowe CV | 16 |
| ……plik Word „B2B” w profilu | 11 |
| ……CV z generatora z innej rekrutacji | 5 |
| ……CV etapu w innej rekrutacji | 4 |
| …u klienta z wymogiem zgody RODO | 3 (2 miały gotowe CV) |
| przepięte pary (wejście `reassign`) | 33 |
| …rekrutacja źródłowa ma CV | 4 |
| …bez CV w źródle, z plikiem Word „B2B” w profilu | 26 |

Trzy wiersze „miały już gotowe CV” nakładają się na siebie.

## Decyzje Artura (12.10.2026)

- Całość w jednym PR-ze: wybór w karcie, wgranie pliku, zgoda dla kopii, przeniesienie CV przy przepięciu.
- Zrzut zgody jedzie z kopią CV, gdy rekrutacja źródłowa i docelowa mają tego samego klienta.
- Automat auto-CV zostaje bez zmian: generuje jak dotąd, a karta proponuje podmianę jednym kliknięciem.

Makiety: https://claude.ai/artifact/XAsoxVnsx7hKYQrdiMxW5C

## Co się zmieniło

### Ekran

- Karta „CV do klienta”: pasek „Ta osoba ma już gotowe CV” z „Użyj tego CV” — gdy CV jeszcze nie ma albo leży
  auto-CV, którego nikt nie przejrzał. Podpowiada CV etapu z innej rekrutacji, potem plik Word, potem generację
  spoza tej rekrutacji.
- Przycisk „Użyj innego CV” otwiera okno: „Z innych rekrutacji” (wersja po poprawkach rekrutera, z podglądem),
  „Z generatora”, „Pliki Word z profilu” i „Plik z dysku” (.docx do 10 MB, wysyłka dopiero po „Użyj tego pliku”).
- Wybrane CV jest szkicem tej rekrutacji w zwykłym edytorze. Zastąpienie istniejącego szkicu wymaga potwierdzenia.
- Plakietka pochodzenia: „z rekrutacji …”, „z pliku Word”, „przeniesione z … — sprawdź przed wysyłką”.
- Klient z wymogiem zgody: opcje nie są już wyszarzone. Kopia powstaje, „Pobierz DOCX” czeka na zrzut, a karta ma
  przycisk dołączenia zgody do CV etapu.
- Karta jest też w sekcji CV osób z „Nowych” i „Screeningu” (bez sekcji wysyłki). CV wybrane wcześniej nie jest
  nadpisywane przez automat po „Zweryfikowany” — reguła `pair_cv_exists` istniała już wcześniej.
- Po przepięciu komunikat mówi, u ilu osób przeniesiono CV z rekrutacji źródłowej.
- Lista w screeningu dostała tę samą grupę „Z innych rekrutacji”.

### Backend

- `services/stage_cv_copy.py` (nowy): lista gotowych CV etapu z innych rekrutacji, kopia CV etapu, podmiana tytułu
  w nagłówku (`retitle_copied_html` na `cv_qc.EditableCv`), przeniesienie przy przepięciu.
- `api/candidate_stage_cv.py`: `GET …/cv/branded/sources`, `POST …/select-stage-cv`, `POST …/upload`,
  `POST …/consent`; `GET …/cv/branded` dla etapu bez wiersza CV zwraca stan pusty zamiast 404; odpowiedź niesie
  `origin`, `consent_required`, `consent_attached`, `consent_missing`.
- `services/candidate_stage_cv_service.detached_copy_settings`: koniec odmowy 422 dla klienta z wymogiem zgody;
  wymóg jest zamrażany na kopii, a blokada pobrania (`cv_consent_gate`) czyta go bez zmian w bramce.
- `services/cv_consent_attach.py`: `stage_binding_context` (jeden kod kontekstu pokwitowania dla wystawienia
  i weryfikacji) i `attach_to_stage_copy`; ponowne zatwierdzenie niezmienionej wersji bez AI ma jedno ciało
  z dotychczasową ścieżką generatora.
- `api/proposals_bulk.add_candidates_to_job`: po migawce oryginału kopia CV z rekrutacji źródłowej (savepoint,
  nigdy nie rzuca); odpowiedzi niosą `cv_carried`.

### Reguły kopii

- Metadane kopii powstają z listy dozwolonych kluczy. Skrót treści generatora i migawka reguł klienta źródłowego
  nie są przenoszone.
- Zrzut zgody jest przenoszony wyłącznie w obrębie tego samego klienta.
- Nagłówek dostaje tytuł rekrutacji docelowej tylko w treści z generatora; nagłówek pliku Word zostaje.
- CV blind: zakaz danych osoby i nazwa pliku „…Kandydat” jadą z kopią.

## Odstępstwa od makiet

- Plik wgrany z dysku nie trafia do plików kandydata. W teczce mógłby stać się „aktualnym CV” osoby, źródłem dla
  generatora i auto-CV, a powtórne wgranie przemianowałoby istniejący plik. Zostaje nazwa i skrót treści w śladzie.
- W pasku podpowiedzi nie ma osobnego „Podglądu” — podglądy są w oknie wyboru.
- Wąski dok na Tablicy bez zmian (jest źródłem przewodnika Jarvisa `jobs.person`).
- Przepięcie przenosi CV tylko na ścieżkach przez `add_candidates_to_job` (panel podobnych rekrutacji, „Do
  przejrzenia”, przypisanie z listy, automat); ruch świeżej pary przez `/pipeline/move`, shortlistę i wtyczkę
  LinkedIn — nie.

## Przeglądy przed PR-em

Dwa niezależne przeglądy (kod, bezpieczeństwo) na `git diff origin/main...HEAD`; oba wskazały po jednym problemie
blokującym, oba poprawione przed otwarciem PR-a:

- **Kopia przy przepięciu nie sprawdzała odczytu rekrutacji źródłowej**, choć ręczny wybór to robi. Dziś każda rola
  wewnętrzna czyta każdą rekrutację, więc wycieku nie było, ale hak byłby drogą dookoła bramki przy każdym jej
  zaostrzeniu. `carry_on_reassign` woła teraz `ensure_job_read_access`; odmowa i brak osoby działającej to „nie
  przenoś” (`test_cv_is_carried_only_by_someone_who_may_read_the_source_recruitment`).
- **Karta twierdziła „nagłówek ma tytuł tej rekrutacji” także dla CV wczytanego z pliku Word**, gdzie nagłówka celowo
  nie zmieniamy (bywa w nim numer zapytania innego klienta). Zdanie zależy teraz od źródła treści: „Nagłówek pochodzi
  z pliku Word — sprawdź go przed wysyłką.”

Bez zastrzeżeń blokujących: autoryzacja nowych tras, pokwitowanie zgody (powtórne użycie między etapami, osobami
i użytkownikami odrzucane), sanitizacja HTML, wgrywanie pliku, CV blind, logi, blokady wierszy i kolejność zapisu.

## Weryfikacja

| Co | Jak | Wynik |
|---|---|---|
| Nagłówek kopii, kontekst pokwitowania | `pytest tests/test_stage_cv_copy_retitle.py tests/test_cv_consent_binding.py` (lokalnie, bez bazy) | zielone |
| Zakres rekrutacji, wzorzec uprawnień, indeks reguł | `test_job_scope_contract.py`, `test_authz_guard_matrix.py`, `test_claude_md_index.py` (lokalnie) | zielone |
| Lint backendu | `ruff check app/`, `ruff format --check app/` | zielone |
| Testy z bazą | pełny bieg CI na gałęzi (pierwszy commit): 3 czerwone — dwa błędy świata testowego w `test_stage_cv_copy.py` (rekrutacja bez klienta) i test odczytu Finansów spięty z dawnym helperem; poprawione | powtórka na PR-ze i w kolejce merge'ów |
| Front | `vitest` dla dotkniętych katalogów (55 plików, 920 testów), `npm run type-check`, `eslint` zmienionych plików | zielone |
| Ekran | harness `/preview/cv-generator?state=card` przy 1280 × 720: pięć stanów karty, okno „Użyj innego CV”, podgląd CV z innej rekrutacji; harness nie wysłał żadnego zapytania do API | obejrzane |

Niepotwierdzone w chwili otwarcia PR-a:

- karta w „Nowych”/„Screeningu” w prawdziwym panelu osoby — jest test komponentu (`CvHandoffWorkbench.test.tsx`),
  ale żaden harness nie montuje tego panelu;
- zapis na żywej rekrutacji (wybór CV, wgranie pliku, dołączenie zgody) — potwierdzają go testy CI; na produkcji
  po wdrożeniu sprawdzamy tylko odczyty.
