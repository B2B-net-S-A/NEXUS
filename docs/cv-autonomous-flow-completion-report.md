# Autonomiczny przepływ CV — raport wdrożenia (17.09.2026)

Decyzje Artura (17.09.2026): auto-dopasowanie dodaje do pipeline'u i powiadamia;
bez backfillu 49 tys. profili; CV z maila od nieznanego nadawcy zakłada kandydata;
zero limitów AI, zostaje alarm wydatków.

## Co się zmieniło dla użytkownika

1. **Brak limitów AI.** Wyczerpana kwota nie przełącza już odczytu CV na regex.
   Ustawienia → AI to raport: model, tokeny i koszt per funkcja, suma miesiąca,
   alarm wydatków i dziennik automatycznych dopasowań.
2. **Pełny profil z CV** (prompt `cv_enrichment` v7): technologie, opis, forma
   zatrudnienia, lokalizacja i klient końcowy per stanowisko; wykształcenie
   z latami; certyfikaty, projekty, osiągnięcia; oś „Technologie w czasie”
   (kiedy i gdzie kandydat używał technologii, łączny czas bez podwójnego
   liczenia). Długie CV trafia do modelu z zachowanym końcem (okno 24 000 znaków).
3. **Jedna ścieżka po odczycie CV** dla uploadu, „Odśwież z CV”, „Nowy kandydat
   z CV”, linku aplikacyjnego i maila: pola → języki → indeks technologii →
   kategoria → wektor → cache → auto-dopasowanie.
4. **CV z maila od nadawcy spoza bazy** podpina się do istniejącego kandydata
   (e-mail/telefon/LinkedIn z treści CV) albo zakłada nowego (`source=email`).
5. **Auto-dopasowanie**: nowe CV → opublikowane rekrutacje; publikacja albo istotna
   zmiana rekrutacji → CV odczytane w ostatnich 90 dniach. Pasujący kandydat
   (≥70 pkt, must-have spełnione, bez kar) trafia na etap „Ogłoszenia” z tagiem
   `auto-match`, właściciel dostaje dzwonek. Do 3 rekrutacji na kandydata,
   do 10 kandydatów na rekrutację.

## Stan po wdrożeniu

**Auto-dopasowanie startuje w trybie próbnym** (`AUTO_MATCH_DRY_RUN=True`):
ocenia i zapisuje każdą decyzję w dzienniku (Ustawienia → AI → „Automatyczne
dopasowania”), ale nikogo nie dodaje i nie wysyła powiadomień. Przejście na żywo
po przejrzeniu dziennika: `AUTO_MATCH_DRY_RUN=false` przez workflow
„Coolify set env”.

Waga świeżości skilli w scoringu (`AI_SCORING_SKILL_RECENCY`) jest wyłączona do
pomiaru `scripts/eval_matching.py --scorer canonical` przed/po.

## Pliki

| Obszar | Pliki |
|---|---|
| Limity AI | `services/ai_quota.py`, `api/ai_settings.py`, `api/public_share.py`, `services/candidate_activity_summary_service.py`, `frontend/src/app/settings/ai/page.tsx` |
| Profil v7 | `services/llm_prompts.py`, `services/cv_parser.py`, `services/cv_enrichment.py`, `services/profile_projection.py`, `models/candidate_skill_usage.py`, `services/embedding_service.py`, `services/canonical_text.py`, `services/scoring_service.py`, `frontend/src/components/candidates/CvRichProfileSections.tsx`, `candidate-profile-helpers.ts`, `CandidateDetailV2.tsx` |
| Wspólna ścieżka | `services/cv_ingest_service.py`, `api/candidates.py`, `services/m365/attachment_handler.py`, `tasks/m365_cv_parse.py` |
| Auto-dopasowanie | `models/candidate_auto_match.py`, `services/auto_match_outbox.py`, `services/auto_match_rules.py`, `services/auto_match_service.py`, `tasks/candidate_auto_match.py`, `api/proposals_bulk.py` (`add_candidates_to_job`), `api/jobs.py`, `frontend/src/components/settings/AutoMatchOverview.tsx`, `NotificationsDropdown.tsx` |

## Migracje (z lustrem w `entrypoint.sh`)

- `0323_candidate_skill_usage` — indeks użycia technologii.
- `0324_candidate_auto_match` — `candidate_match_outbox`, `candidate_auto_match_log`,
  `notificationtype.auto_match`, `emailmatchmethod.cv_identity`.

Lustro sprawdzone: baza cofnięta do 0322 i uzupełniona wyłącznie instrukcjami
z entrypointu ma identyczne kolumny, indeksy, więzy i enumy jak po migracjach.

## Nowe endpointy

- `GET /api/settings/ai/auto-match` (admin) — stan, liczniki 7 dni, ostatnie decyzje.
- Usunięte: `PATCH /api/settings/ai/master`, `PATCH /api/settings/ai/features/{feature}`.

## Weryfikacja

- Backend: 809 testów dotkniętych obszarów zielonych na świeżej bazie PostgreSQL
  (nowe: `test_cv_profile_v7.py`, `test_cv_ingest_service.py`, `test_auto_match.py`).
- Frontend: `tsc --noEmit` czysty, 305 testów vitest zielonych.
- Wizualnie: sekcje profilu v7 na desktopie i 375 px (podgląd z danymi przykładowymi).

## Przegląd adwersarialny (przed wdrożeniem)

Niezależny przegląd całej zmiany znalazł 13 błędów. Wszystkie naprawione, każdy
z testem regresji w `test_auto_match.py` / `test_cv_profile_v7.py`:

- kolejka mogła zakleszczyć się na konflikcie unikalności (`failed` obok `pending`)
  i zostawiać zdarzenia ubite deployem w `processing` na zawsze;
- dzwonek `auto_match` był niewidoczny dla rekruterów (brak w mapie sekcji);
- decyzje trybu próbnego blokowały dodanie po przejściu na żywo, a zmiana wymagań
  rekrutacji nie oceniała ponownie wcześniej odrzuconych;
- pula wyszukiwania brała najbliższe rekrutacje z całej bazy (głównie zamknięte)
  — teraz Qdrant szuka wyłącznie wśród opublikowanych rekrutacji i świeżych
  profili v7;
- CV z maila: znacznik próby blokował późniejszy odczyt po ręcznym podpięciu,
  wyjątek zapętlał płatny odczyt, e-mail i telefon wskazujące dwie różne osoby
  mogły wpisać cudzy kontakt, a CV z kontaktem firmowym zakładało „kandydata”;
- okno „Nowy kandydat z CV” miało 30 s na odpowiedź przy dłuższym odczycie v7
  (teraz 120 s, a odczyt ma sufit 110 s);
- słabszy odczyt (regex, nocny backfill) kasował pełny profil;
- dodatki wspólnej ścieżki mogły zatruć sesję i zgubić zapis profilu.

## Znane ograniczenia

- Stare profile (49 tys.) nie mają osi technologii ani certyfikatów — dostaną je
  przy wgraniu lub odświeżeniu CV.
- Punkty rekrutacji w Qdrancie nadal nie mają `content_hash`; auto-dopasowanie
  tego nie potrzebuje (mierzy tekst kandydata jako zapytanie).
- Warstwa lokalizacji w scoringu czyta legacy `candidate.location`.
- Koszt odczytu CV rośnie ~2–3× na plik (większe okno i odpowiedź).
- Testy JJIT (`test_jjit_import.py`) zostawiają w bazie znacznik „widziane”,
  więc powtórzone na tej samej bazie padają — CI stawia świeżą bazę.
