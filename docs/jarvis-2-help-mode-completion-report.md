# Jarvis 2 — pomoc na ekranie, dzień pracy, pamięć (23.09.2026)

PR: #1746 · plan: `~/.claude/plans/zaplanuj-wszystko-snug-scott.md` · migracja `0355_jarvis_ui_events`.

## Dlaczego

Pomiar produkcji 21–23.09.2026 (tylko odczyt, agregaty): 6 osób, w tym 3 admini
testujący; realnie HoR, jeden rekruter i jeden sourcer. 18 tur za 0,65 USD,
0 proponowanych zapisów, 0 kliknięć podpowiedzi, 0 tur z internetem, żaden
Delivery Lead, TCM ani Finanse. Jedna trzecia pytań to kliknięcie porannego
skrótu. Odpowiedzi do 2000 znaków na krótkie pytania.

Wniosek: nie brakowało narzędzi, brakowało obecności w codziennej pracy.

## Decyzje Artura (23.09.2026)

1. Dymek przy pierwszej wizycie na ekranie domyślnie włączony, raz na ekran.
2. Przewodniki dla 12 ekranów; reszta, jeśli dymki będą klikane.
3. Treść przewodników bez przeglądu człowieka — pilnuje test świeżości.
4. Bez głosu (Web Speech w Chrome wysyła dźwięk do Google).
5. Jeden PR.

## Co powstało

| Część | Gdzie | Dowód |
|---|---|---|
| Przewodniki 12 ekranów + API | `backend/app/data/screen_guides/`, `backend/app/api/help_screens.py` | `test_screen_guides_freshness.py`, `test_jarvis_help_mode.py::test_screen_guides_hide_anchors…` |
| Klucz ekranu, podpowiedzi z przewodnika | `frontend/src/lib/help/screen-key.ts`, `lib/jarvis/context.ts` | `lib/help/__tests__/help-mode.test.ts` (23 adresy, lustro kluczy) |
| Dymek przy pierwszej wizycie, budżet 3/dzień, karta „?” | `components/jarvis/JarvisRoot.tsx`, `JarvisGuideCard.tsx`, `lib/jarvis/bubble-budget.ts` | testy budżetu i karty |
| 51 kotwic `data-help`, podświetlanie | 12 ekranów, `components/jarvis/HelpSpotlight.tsx`, narzędzie `show_on_screen` | test kotwic w obie strony; `test_show_on_screen_accepts_only_anchors…` |
| Wyjaśnianie powtarzających się odmów | `lib/help/error-explainers.ts`, `refusal-tracker.ts`, obserwator w `lib/api.ts` | każdy kod istnieje w backendzie (test), próg 3 w 2 min |
| Zatrzymaj | `POST /api/jarvis/conversations/{id}/cancel`, `agent.py` | `test_cancel_stops_the_loop…`, `test_cancel_route_is_owner_only` |
| Ucięta odpowiedź, krótsze odpowiedzi, godzina | `agent.py`, `prompt.py` | `test_truncated_answer…`, `test_context_block…` |
| Pomoc z rankingiem | `backend/app/services/help_search.py`, `GET /api/procedures?ranked=true` | `test_ranked_procedure_search_finds_a_sentence_question` |
| Kontrakt po ID + 15 narzędzi dnia pracy | `backend/app/services/jarvis/tools.py` | `test_jarvis_tool_registry_contract.py` (trasy, zakazy, klucze odświeżania) |
| Pamięć „Co Jarvis o mnie wie” | `prefs.py`, `JarvisAppearanceForm.tsx`, `remember_preference` | `test_notes_preferences_are_validated`, `test_remember_preference_appends…` |
| Strumieniowanie tekstu | `claude_client.py` (`on_text_delta`), `agent.py`, `reducer.ts` | `test_text_deltas_stream…`, testy reduktora |
| Telemetria | `jarvis_ui_events` (0355 + `entrypoint.sh`), `lib/jarvis/telemetry.ts` | `test_ui_events…`, `test_old_ui_events_are_purged`, lustro migracji |
| Stary przewodnik powitalny usunięty | `OnboardingWalkthrough.tsx` (usunięty), Ustawienia → „Pokaż wskazówki od nowa” | test ustawień |

## Jak mierzyć po wdrożeniu

`GET /api/jarvis/ui-events/summary?days=14` (admin): liczniki `bubble_shown`,
`bubble_clicked`, `bubble_dismissed`, `guide_opened`, `guide_task`,
`highlight_shown`, `highlight_missing`, `stuck_shown`, `stuck_clicked`
per ekran. Przewodnik albo typ dymka z kliknięciami poniżej 25% po dwóch
tygodniach — do wyłączenia. `highlight_missing` > 0 = kotwica nie trafia
w element (błąd katalogu).

## Świadomie poza zakresem

- Głos i dyktowanie (RODO).
- Terminy od klienta przez Jarvisa — `POST /slots` sam przesuwa kartę i powiadamia; zostaje link.
- Wyszukiwanie przewodników innych ekranów pełnym tekstem — model wybiera klucz z listy.
- Dok osoby nie stoi w adresie, więc dymek `jobs.person` pojawia się tylko przy
  wejściu z `?candidate=`; „?” i pytania rozpoznają dok po otwartym panelu.

## Znalezione

- `GET /api/candidates/{cid}/scoring/{job_id}` nie sprawdza dostępu do
  konkretnej rekrutacji (brak `ensure_job_read_access`), a przy braku cache
  woła płatne AI i zapisuje wynik. Jarvis tego nie poszerza (ten sam token),
  ale luka istnieje niezależnie.
