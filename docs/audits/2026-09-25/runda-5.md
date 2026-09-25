# Audyt NEXUS 26.09.2026 — runda 5

> **Baza:** `8da65ef74` (main po PR #1844) · **Status:** naprawione w PR „fix: naprawa pozycji z rundy 5 audytu (26.09.2026)” — wszystkie 8 pozycji + niskie z wyszukiwania (klucz liczby w podpowiedziach). Decyzja: czat CV przyjmuje pytania jeszcze 2 h po ostatnim dozwolonym wyświetleniu (`CHAT_AFTER_LAST_VIEW`).
> Poprzednie rundy: [README](README.md). Reguły po naprawach: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”.

## Zakres

Czterech agentów, tylko odczyt, znaleziska sprawdzone przez koordynatora w kodzie (oznaczenie „POTWIERDZONE”):

1. Weryfikacja wszystkich poprawek rundy 4 (`c72f411a4..8da65ef74`, ~60 plików).
2. Powierzchnie publiczne i uwierzytelnianie — pierwszy raz trasa po trasie (41 tras bez logowania, auth, SSO, OAuth, klucze serwisowe, WebSocket, pliki, SSRF, CORS, limity).
3. Wyszukiwanie kandydatów (PR #1834 i poprawki, #1845) oraz nocny import Traffita.
4. Lustro DDL `entrypoint.sh` vs migracje 0350–0384, 65 pętli tła, frontend nowych modułów.

## Wynik

| Waga | Liczba | Pozycje |
|---|---|---|
| wysokie | 1 | R5-2 (DELETE omija limit ciała → OOM) |
| średnio-wysokie | 1 | R5-1 (przesunięcie daty końca nie anuluje zastępstwa) |
| średnie | 2 | R5-3 (czat CV bez limitu wyświetleń, uśpione), R5-4 (druk edytora CV bez CSP) |
| niskie | 4 | R5-5 … R5-8 |

Trend błędów w kodzie poprawionym w poprzedniej rundzie: 61 → 19 → 2 → 10 → **1**.

## Szczegóły


### Poprawki R4
- R5-1 [POPRAWKA-R4] średnio-wysokie: contracts.py:~4041-4064 PATCH przesuwający datę końca w przód nie anuluje zaplanowanego zastępstwa (tylko aneks, bulk-extend, undo, clears_ending) → 01.01 zastępstwo wchodzi wstecz z datą 01.10 (target.start_date), okresy A i B nakładają się; activate_due_takeovers nie odrzuca entry_date <= departure.
- niskie: reaktywacja konta — manual zwolniony jako inactive nie wraca; LEAGUE_NO_RETROACTIVITY_NOTE nieaktualny tekst; test_audit_r4_contracts.py:481 globalne activated == 0.
### Publiczne/auth
- R5-2 POTWIERDZONE [NOWY, luka SEC-03] wysokie: body_size_limit._BODY_METHODS bez DELETE, null_character_guard buforuje DELETE → anonimowy DELETE z ogromnym ciałem = OOM jedynego uvicorna (dowód skryptem: POST 413, DELETE wczytał 50 KB przy limicie 1 KB).
- R5-3 POTWIERDZONE [NOWY] średnie (uśpione, CV_INTERACTIVE_ENABLED=false): POST /api/public/cv-i/{token}/chat nie sprawdza max_views (tylko GET, public_share.py:446).
- R5-4 POTWIERDZONE [NOWY] średnie: cv_generator_b2b.print_generated_editor (~3776) składa HTML ze <script> bez printable_document (CSP w meta), bliźniak candidate_stage_cv._wrap_printable_cv ma.
- do wiadomości: refresh token nie rotowany / wylogowanie nie unieważnia; stary WS ?token=; timing /login (hasło wyłączone na prod); /public/sign/* działa przy SIGNING_ENABLED=false; /api/health/deep i webhook M365 bez limitu.
### Schemat/pętle/frontend
- R5-5 [NOWY] niskie: AcademyScreen.tsx:77-94 replaceRow bez counts/unieważnienia applications → liczniki nieaktualne ≤2 min.
- R5-6 POTWIERDZONE [NOWY] niskie/średnie: nordea_invoice_lines.fill_missing (376-402) bez blokady/warunku zapisu, OCR w otwartej transakcji → może nadpisać ręczną formułę (pierwszy bieg).
- R5-7 POTWIERDZONE [NOWY] niskie: request_allocation_notices.py:178 now.weekday() na UTC (błąd tylko przy review_time < 02:00).
- R5-8 [NOWY] niskie UX: /jobs/new po nieudanej publikacji portal → ?tab=portals, sekcja zwinięta.
- Czyste: lustro DDL 0350–0384 (skrypt porównujący), 65 pętli z heartbeat/EXEMPT, frontend nowych modułów (brak confirm, puste stany na isSuccess, apiErrorMessage, linki ?tab=, typy TS).
### Wyszukiwanie/import Traffita
- Brak blokujących. Czyste: wiersze wymagań front↔back (q_any_group, parse_q_groups, limit 20), v1 bez zmian, zapisane wyszukiwania i skaner (lustra payloadu), eksport z filtra, keyword_terms/whole_word/tsquery (.js, DOT_PREFIXES), keyword_suggest (savepoint + statement_timeout), Szukaj ręcznie (not_assigned w zapytaniu), zapis Championa (wiersze bez przeliczenia), #1845 (lista id-first, korpus za flagą); Traffit: kontakty+aliasy, archiwum 0377/0378, adopcja po mailu, _late_email_owner, watermark/kwarantanna/carried_errors, pipelines, aktywności.
- Niesprawdzone (pobieżnie): fazy candidate_files, candidates_cv, candidates_cv_text, enrich_names, workflows, sources, talents, mappers.py, rejection_backfill.
- Poza progiem: keyword_suggest liczba pod kluczem bez polskich znaków; pamięć listy w sessionStorage bez klucza użytkownika.

## Co zrobiono (naprawa)

| Pozycja | Naprawa |
|---|---|
| R5-2 | Jedna stała `REQUEST_BODY_METHODS` (z DELETE) dla limitu ciała i strażnika NUL; GET/OPTIONS/HEAD nie są buforowane. |
| R5-1 | PATCH daty końca w przód / na „bezterminowo” (także korekta rozwiązanej umowy) anuluje zaplanowane zastępstwo; nocne wejście anuluje zastępstwo z dniem wejścia nie po dniu odejścia (`entry_not_after_departure`). |
| R5-4 | Druk szkicu CV z generatora i render szablonu umowy przez `printable_document` (CSP w `<meta>`); test AST na własne `window.print`. |
| R5-3 | Czat `/cv-i/{token}/chat` respektuje `max_views` bez zużywania wyświetleń (okno 2 h po ostatnim wyświetleniu). |
| R5-5 | Akademia: liczniki przeliczane od razu po akcji (`withReplacedApplication`). |
| R5-6 | Faktura Nordei: OCR poza transakcją, zapis warunkowy (`invoice_lines IS NULL`, ten sam plik i stempel); `save_line` czyta PDF przed blokadą. |
| R5-7 | Poniedziałek przypomnień w `BUSINESS_TZ` (`is_stale_check_day`); pozostałe `.weekday()` na UTC oznaczone komentarzem. |
| R5-8 | `?tab=portals` otwiera okno zlecenia z rozwiniętą i przewiniętą sekcją portali (`wintab=portals`). |
| niskie | Liczba osób w podpowiedziach słów ma klucz z polską pisownią (`_count_key`). |

## Do wiadomości (poza progiem blokady)

- Refresh token nie jest rotowany, a wylogowanie niczego nie unieważnia po stronie serwera (odwołanie tylko przez zmianę hasła, reset admina, zmianę ról).
- Stary kanał WebSocket nadal przyjmuje token w `?token=`.
- `/login` i `/forgot-password` odpowiadają szybciej dla nieistniejącego konta (logowanie hasłem na produkcji wyłączone — 503).
- `/public/sign/*` działa mimo `SIGNING_ENABLED=false` (stare linki prawdopodobnie wygasły).
- `/api/health/deep` i webhook M365 bez limitu zapytań.
