# Generator CV — domyślnie ścieżka sprzed przebudowy (`legacy_v7`, 10.09.2026)

Między 09.09 a 10.09 generator przebudowano (#1444 i poprawki #1476/#1478/#1479):
osobne wywołanie AI wyciągające „fakty źródłowe”, redakcja z samego JSON-a
faktów (model nie widzi surowego CV), nowy krótki angielski prompt v10 zamiast
szczegółowego polskiego v7, przepisywanie długich punktów przez AI, pogrubianie
technologii w każdym trybie i końcowa kontrola AI. Zespół zgłosił, że CV
„generują się inaczej”, więc **domyślnie działa przepływ z 2bc6b14f**.

- **Przełącznik:** `CV_GENERATION_PIPELINE` — brak/`legacy` = stary przepływ,
  `v10` = przebudowany. Kod v10 zostaje nietknięty i wybieralny (analiza „co
  poszło nie tak” i ewentualny powrót bez deployu).
- **Kod:** `services/cv_generator_b2b/legacy_v7/` — zamrożone kopie z 2bc6b14f
  (prompt, odczyt PDF/DOCX, sekcja Championa, reguły w prompcie i polityka
  prezentacji, pomocniki lat/normalizacji). Wejścia: `prepare_source_facts`
  i `_run_generation_pipeline` w `standalone_service` (import leniwy —
  `legacy_v7.pipeline` importuje `standalone_service`).
- **Świadomie NIE cofnięte (poprawki błędów):** `apply_date_format`/
  `reformat_dates` (stary regex psuł `15.03.2020`), renderer DOCX (marginesy
  papieru firmowego #1449, filtr „Jest”), streaming/deadline w `provider.py`
  (przywrócenie starego pliku wywala start backendu). Zostaje też cała nowa
  infrastruktura: zadania trwałe, wersje, zatwierdzanie, zgoda RODO, dostęp.
- **Niezależna kontrola AI treści CV — `CV_FINAL_REVIEW_ENABLED`, domyślnie ON
  (0327, decyzja Artura 18.09.2026).** Gotowe CV recenzuje DRUGI model —
  `AIFeatureKey.cv_factual_verification` = **GPT Luna**, fallback Sonnet 5 —
  a nie ten, który je napisał: badanie z 16.09 zmierzyło, że sędzia LLM
  faworyzuje własne wyjście, więc model oceniający własną pracę jest
  systematycznie za łagodny. **Recenzja jest DORADCZA i nigdy nie rzuca**
  (`final_review.run_final_review`): niepotwierdzone twierdzenia jadą jako
  ostrzeżenia `BRAK POKRYCIA (kontrola AI): …`, raport ląduje w
  `render_payload["factual_verification"]` (prywatny — `public_view` to
  allowlista), a plakietka „Kontrola AI: OK / N uwag / niedostępna" stoi
  w wierszu listy CV. Model per env `CV_FACTUAL_VERIFICATION_MODEL`, budżet
  całej recenzji `CV_FINAL_REVIEW_TIMEOUT` (120 s, dzielony między paczki po
  40 twierdzeń). Wyłączenie flagi zdejmuje wydatek i wszystkie uwagi.
  **Nie zamieniaj tego w bramkę** — od blokowania jest osobne
  `CV_SOURCE_EVIDENCE_ENFORCED`; powód w sekcji „AI w generatorze to dodatek,
  nigdy bramka”.
- **Zatwierdzanie przy `CV_SOURCE_EVIDENCE_ENFORCED` wyłączonym (domyślnie):**
  edytowane CV przechodzi kontrolę DORADCZĄ (gdy `CV_FINAL_REVIEW_ENABLED`):
  zatwierdzenie zawsze przechodzi, a wynik ląduje w
  `branded_render_metadata["content_review"]` — `status="reviewed"` z
  `findings.count`, gdy recenzent czegoś nie potwierdził, `"verified"` przy
  czystym wyniku, `"unverified"` + `method_detail`, gdy recenzja się nie
  wykonała (nigdy fałszywe „verified”). Brak źródeł nie odmawia zatwierdzenia,
  tylko degraduje do `advisory_source_unavailable`. Rekruter dostaje trwały
  baner z liczbą uwag. Przy OBU flagach wyłączonych zostaje dotychczasowe
  `evidence_enforcement_off` bez żadnego wywołania modelu. Kontrole prywatności
  i struktury klienta działają w każdym wariancie. **`CV_SOURCE_EVIDENCE_ENFORCED`
  włączaj wyłącznie razem z `CV_GENERATION_PIPELINE=v10`** — to twarda bramka,
  a jej fałszywe alarmy zatrzymują pracę zespołu (10.09).
- **Raport „verified" z generacji zwalnia z drugiej recenzji** przy
  zatwierdzaniu NIEZMIENIONEGO CV (`cv_approval_provenance`,
  `unchanged_generation`) — świadome: ten sam recenzent i ta sama treść, więc
  druga płatna kontrola niczego by nie dodała.
- **Zachowane zachowania sprzed przebudowy (wiedz, zanim „naprawisz”):** pełny
  słownik klienta (także wpisy sprzed #1445) trafia do promptu i podmienia
  tekst we wszystkich polach; długie punkty są skracane z „…”; w trybie
  `polished`/`basic` nie ma pogrubień (tylko `tailored` pogrubia MUST/NICE
  Championa); brak branży w blind = „IT”; nagłówek lat zaokrągla sumę
  przedziałów; strony PDF będące samym obrazem są pomijane zamiast blokować.
  Ustawienia „wyróżnień” w regułach CV (0284) są w tym trybie nieaktywne.
- **Testy:** `conftest` przypina `v10` + ścisłe dowody dla dotychczasowych
  testów; domyślne zachowanie produkcyjne pilnuje
  `tests/test_cv_generator_legacy_v7.py`.
- **Generować CV może każdy (decyzja Artura, 10.09.2026).** #1448 dołożył
  wymóg członkostwa w zespole rekrutacji do `/generate`, `/generate-upload`
  i zrzutu zgody — cofnięty. Zostaje bramka roli (`CandidateWriteAccess`)
  i poprawność „etap musi należeć do kandydata” (404). Picker rekrutacji
  w generatorze (`/candidates/{id}/recruitments`) nie jest zawężany — to on
  decyduje, pod którą rekrutacją da się wygenerować CV.
  Istniejące CV (`_load_generated_document`): **autor zawsze**; cudzy dokument
  związany z rekrutacją wymaga odczytu tej rekrutacji (`ensure_job_read_access`
  — obejmuje Finanse, więc Finanse może też zatwierdzić/udostępnić cudze CV,
  jak przed 09.09); usunięcie nadal autor albo admin. Lista `/generated` to
  zakres odczytu **lub** własne CV. Ręczne podpięcie CV do etapu w pipeline
  (`candidate_stage_cv.py`, „Użyj”, wybór z profilu) robi od 23.09.2026 każda
  rola wewnętrzna z zapisem kandydata (`ensure_job_membership` przepuszcza
  role wewnętrzne); automatyczne podpięcie po generacji z procesem (v3) działa
  tylko do etapu bez szkicu.
- **CV sprzed #1444 da się zatwierdzić.** Wiersze bez `docx_content` i
  `docx_sha256` (każde CV sprzed 10.09, 09:04) dostają DOCX renderowany raz
  z `render_payload` przy zatwierdzeniu, zapisany na wierszu
  (`docx_rendered_at_approval`). Stan częściowy (plik bez skrótu, skrót bez
  pliku, rozjazd) to nadal 409 integralności.
- **Zadania z kolejki przeżywają deploy.** `job_snapshot.py` przyjmuje snapshot
  bez pola, które ma wartość domyślną w dataclassie (np. `champion_profile`
  z #1477); nieznane pola i brak pól wymaganych dalej są odrzucane.
- **CV nie znikają same — automatyczna retencja WYŁĄCZONA (decyzja Artura
  23.09.2026: trzymamy wszystko, także bez zgody RODO).**
  `CV_JOB_INPUT_RETENTION_ENABLED` domyślnie `false` i obejmuje oba automaty
  poniżej: sprzątanie wejść generatora i CV próbnych reguł klienta. CV znika
  wyłącznie ręcznie (usunięcie dokumentu) — usunięcie kandydata CV nie kasuje
  (decyzja 26.09.2026). Nie włączaj z
  powrotem bez decyzji właściciela. Opis mechanizmu (stan przy `true`):
  `retire_unneeded_job_inputs` w pętli `cv_source_cleanup` (co 15 min, paczki
  `FOR UPDATE SKIP LOCKED`) bierze zadania zakończone porażką/przerwane bez
  gotowego dokumentu i zakończone podglądy reguł CV: klucz w magazynie zmienia
  na `purged/<id>`, a stary idzie do rejestru kasowań (to on kasuje plik,
  z ponowieniami). **Nie rusza** zadań w kolejce i w toku ani wejść pod gotowym
  dokumentem (przegląd zatwierdzenia i mapa wersji je czytają; ponowny render
  idzie z `render_payload`). Wyłącznik `CV_JOB_INPUT_RETENTION_ENABLED`, okres
  `CV_JOB_INPUT_RETENTION_DAYS`. Do 11.09 wgrane CV i notatki z nieudanych
  generacji leżały bez końca.
- **Limit 14 000 znaków dotyczy WYŁĄCZNIE miejsc, w których tekst czyta AI:**
  parser Championa (sprawdzany przed naliczeniem kwoty AI) i sekcja Championa
  w płatnym prompcie generatora CV (`cap_champion_prompt_section`, obie ścieżki —
  legacy i v10 — cięcie na granicy linii/słowa z ostrzeżeniem „Profil Championa
  przycięty…”). Odczyt tabel formularza Word v4 i zapisany profil nie są
  przycinane, a preflight uploadu podaje prawdziwy powód odmowy zamiast „nie
  można odczytać pliku DOCX”.
- **`CV_B2B_MAX_RETRIES` domyślnie 3** — łączny budżet 300 s dalej zatrzymuje
  nowe próby i backoffy po terminie. Jawna wartość w Coolify wygrywa.

### Zasada: AI w generatorze to dodatek, nigdy bramka (po 10–11.09.2026)

Trzy awarie w dwa dni miały jeden wspólny mechanizm: w ścieżkę, która działała
deterministycznie, wstawiono wywołanie modelu jako **warunek** wykonania
(#1444 — kontrola źródeł; #1477 — podgląd AI Championa w Kroku 2 generatora
i ponownie serwerowo w `generate-upload` dla trybu `tailored`). Model odpowiada
nierównomiernie, więc każda taka bramka to losowe „generator nie działa”.

- **Wgrany DOCX Championa jest przypinany PRZED podglądem AI** (#1490).
  Nieudany `/api/champion/preview` daje notkę informacyjną
  (`championPreviewNotice`, osobny stan od `championError`), a generacja czyta
  plik sama, deterministycznie (`parse_champion_from_docx_bytes`).
  W `generate-upload` 422/503 z `read_preview` = „brak zrecenzowanego profilu”,
  nie błąd. Regresja: `CVGeneratorStandaloneV2.test.tsx` („the AI champion
  preview is an aid, not a gate”).
- **Dokładając wywołanie AI do generatora, zaprojektuj jego awarię:** wynik
  modelu może wzbogacić dokument, podgląd albo audyt — ale ścieżka bez tego
  wyniku musi nadal oddać CV. Jeśli musi blokować (RODO, pieniądze), stoi za
  flagą domyślnie OFF (`CV_SOURCE_EVIDENCE_ENFORCED`, `CHAMPION_INTAKE_GATE_ENABLED`).
