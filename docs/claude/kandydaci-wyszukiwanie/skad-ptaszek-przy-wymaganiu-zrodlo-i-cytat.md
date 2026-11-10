# Skąd „✓” przy wymaganiu — źródło przy chipie, cytat po kliknięciu (10.11.2026)
<!-- indeks: `services/requirement_evidence.py`, `POST /api/search/candidates/requirement-evidence`, `RequirementEvidenceChips`, „angular · profil”, „Pokaż w CV”, wariant B -->

Zgłoszenie Delivery Leada z 09.11.2026: NEXUS polecił do rekrutacji Java +
Angular osobę, w której CV Angulara nie ma. „✓ angular” wziął się z profilu
(pole technologii, lista umiejętności) i z notatki z rozmowy („ostatnio
Angular, ale nie jestem mega mocny na frontendzie”), ale ekran pokazywał
takie samo „✓” jak przy technologii z CV. Decyzja Artura 10.11.2026 po
makietach na stagingu: wariant B + klik. **Ocena dopasowania się nie
zmienia** (procent, „musi mieć X/Y”, bramka) — zmienia się to, co DL widzi.

## Reguły

- **Gdzie:** podgląd osoby w oknie „Kandydaci do dodania” (`PersonPreview`,
  sekcja „Dopasowanie do tej rekrutacji”), chipy z `matching_must` odpowiedzi
  `/candidates/scores`. Chipy w wierszach listy i panel propozycji bez zmian.
- **Przy każdym „✓”** dopisek źródeł w stałej kolejności „CV, profil,
  notatka”. Bez CV dopisek jest żółty i pogrubiony. „bez wzmianki” = ocena
  uznała wymaganie po wariancie nazwy z listy umiejętności, a dosłownego
  słowa nie ma nigdzie. Do czasu odpowiedzi chip jest bez dopisku i bez
  kliknięcia; błąd to komunikat z „Spróbuj ponownie”, nigdy „bez wzmianki”.
- **Klik w „✓”** rozwija pod chipami „Skąd ✓ …”: cytat z CV z podświetlonym
  słowem i „Pokaż w CV” (to samo okno co „Podgląd CV”, z lupą ustawioną na to
  słowo), do 3 notatek z datą (data źródła z Traffita) i autorem, „+N
  kolejne”, oraz miejsca w profilu z nazwą („Lista umiejętności”, „Historia
  stanowisk”, „Pola z Traffita”, „Odczyt CV”, „Fakty z rozmów”,
  „Stanowisko”, „Tagi”). Bez CV zamiast cytatu: „W tekście CV tego słowa nie
  ma — zapytaj w rozmowie”.
- **Reguła słowa ta sama co bramka i przegląd DL:** `mention_snippet` (całe
  słowo, aliasy, rodzina SQL, mapa wiedzy). Gdy cytat trafia inną nazwą niż
  słowo wymagania (PostgreSQL przy SQL), pole `via` i dopisek „(jako
  „postgresql”)”. Notatki-dowody jak w bramce: rodzaje rozmów, bez maili
  i wpisów automatu, karta z przeczeniem odpada (`evidence_note_text`).
- **CV = tekst głównego CV** (`raw_cv_text`). Firmowe CV i inne pliki nie są
  źródłem „CV” — to, co z nich trafiło do profilu, widać jako „profil”.
- **Trasa:** `POST /api/search/candidates/requirement-evidence`
  (`job_id`, `candidate_id`, do 30 etykiet), ta sama bramka co `/scores`
  (`CandidateSearchAccess` + `_authorized_job`), tylko odczyt, 60/min.
- **Skala w dniu zmiany** (kopia z 10.11, 43209): 27 z 254 propozycji
  z „✓ angular” nie ma Angulara w tekście CV.
