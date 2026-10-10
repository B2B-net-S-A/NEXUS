# Jarvis 2 — pomoc na ekranie, dzień pracy, pamięć (0355, 23.09.2026)

Pomiar 21–23.09: 3 realne osoby, 18 tur, 0 akcji zapisu, 0 kliknięć podpowiedzi,
żaden DL. Diagnoza: Jarvisowi nie brakowało narzędzi, tylko obecności w pracy.
Decyzje Artura 23.09: dymek domyślnie ON (raz na ekran), 12 ekranów, treść
przewodników bez przeglądu człowieka (pilnuje test świeżości), bez głosu (RODO).

- **Przewodniki ekranów: `backend/app/data/screen_guides/guides.json`**
  (12 kluczy `SCREEN_KEYS`, lustro `lib/help/screen-key.ts`). Front czyta je
  z `GET /api/help/screens` (obrazy Dockera nie widzą swoich katalogów), Jarvis
  narzędziem `get_screen_guide`. Każdy wpis ma `sources` — zmiana któregoś pliku
  albo samego wpisu = czerwony `test_screen_guides_freshness.py`; po przeglądzie
  `cd backend && python3 scripts/stamp_screen_guides.py` (stemple per ekran w
  `screen_guides/stamps/<klucz>.json` od #1776 — PR-y na różnych ekranach się
  nie zderzają). Treść jest dla
  rekrutera: bez ścieżek, tras i nazw tabel (test to sprawdza). Stary
  `OnboardingWalkthrough` usunięty — zgnił dokładnie tak („Ogłoszenia").
- **Kotwice `data-help="<klucz>.<nazwa>"`** na istniejących elementach 12
  ekranów, zamknięta lista w `anchors` przewodnika. Model NIE podaje selektora:
  `show_on_screen` (tier `link`) przyjmuje tylko id z przewodnika BIEŻĄCEGO
  ekranu, a `requires` odfiltrowuje przyciski, których ta rola nie widzi.
  `HelpSpotlight` szuka elementu 1,5 s, brak = komunikat, nigdy cisza.
  Test `lib/help/__tests__/help-mode.test.ts` wymaga zgodności w obie strony
  (kotwica bez `data-help` i `data-help` bez kotwicy = czerwień). Nowa kotwica =
  wpis w JSON-ie + atrybut + przestemplowanie. Dok osoby nie stoi w adresie —
  `jobs.person` rozpoznaje `context.ts` po otwartym `[data-help="jobs.person.dock"]`.
- **Dymki nieproszone mają JEDEN budżet: 3 dziennie** (`lib/jarvis/bubble-budget.ts`),
  wspólny dla dymka ekranu i „utknięcia”; nigdy przy otwartym oknie Radix ani
  panelu. Poranny skrót i „Moi ludzie” mają własne reguły. Nie dokładaj źródła
  dymków obok budżetu.
- **„Utknięcie”**: interceptor w `lib/api.ts` tylko obserwuje odmowy
  403/409/412/422/423 z `detail.code`/`detail.reason`; trzecia taka sama w 2 min →
  dymek z tekstem z `lib/help/error-explainers.ts` (bez modelu). Każdy kod musi
  istnieć w backendzie (test grepuje `backend/app`).
- **„Zatrzymaj”**: `POST /api/jarvis/conversations/{id}/cancel` → zbiór w pamięci
  procesu (backend = jeden uvicorn), pętla sprawdza go przed krokiem modelu
  i przed każdym narzędziem; każdy `tool_use` dostaje wynik (inaczej historia
  psuje następną turę). Wywołania modelu w wątku nie da się przerwać w połowie.
- **`stop_reason=max_tokens`**: ucięty `tool_use` jest wyrzucany, tekst dostaje
  dopisek „napisz «dalej»”. Krótkie odpowiedzi wymusza prompt, nie limit tokenów.
- **Strumieniowanie**: `call_claude(..., stream_response=True, on_text_delta=…)`
  (tylko Anthropic; ponowienie wysyła `None` → `delta_reset`); agent przekazuje
  delty kolejką z wątku (`loop.call_soon_threadsafe`). `message` na końcu kroku
  ZASTĘPUJE tekst pisany na żywo w reduktorze — nie dokładaj drugiej wiadomości.
- **Pamięć „Co Jarvis o mnie wie”**: `jarvis_prefs.notes` (≤10 × 200 zn., bez
  `<>{}[]\``), w bloku kontekstu każdej wiadomości — nigdy w `SYSTEM_PROMPT`
  (cache). `remember_preference` składa pełną listę serwerowo (`_notes`, którego
  model nie poda — `sanitize_args`). Prompt zakazuje zapamiętywania danych
  kandydatów.
- **Nowe narzędzia** (wszystkie na istniejących trasach): `get_contract`,
  `my_board_tasks`, `my_interview_cycle`, `prep_for_interview`,
  `client_questions`, `get_debrief`, `list_job_proposals`, `get_hm_feedback`,
  `order_mail_queue`, `metric_catalog`/`evaluate_metric`, `explain_match` (BEZ
  `refresh` — pierwsze pytanie o parę i tak płaci), `get_screen_guide`; zapisy
  `save_interview_debrief`, `dismiss_job_proposal`, `record_hm_feedback`,
  `claim_candidate`, `snooze_my_person`/`pin_my_person`, `remember_preference`.
  Terminy od klienta zostają linkiem (`POST /slots` sam przesuwa kartę).
- **`search_help` pyta `GET /api/procedures?ranked=true`** (`services/help_search.py`:
  punkty zamiast AND słów, bez polskich znaków, prefiks 5 znaków, fragment
  treści). Ekran Pomocy woła bez `ranked` — jego zachowanie się nie zmienia.
- **Telemetria `jarvis_ui_events` (0355)** + lustro w `entrypoint.sh`: tylko klucz
  ekranu i kod, retencja 90 dni w `jarvis_retention`. Liczniki:
  `GET /api/jarvis/ui-events/summary?days=14` (admin). Typ dymka albo przewodnik
  z kliknięciami <25% po 2 tygodniach — do wyłączenia, nie do wzmacniania.
