# Okienko „Rozmowy” w górnym pasku — raport (13.10.2026)

## Skąd zmiana

Powiadomienia o rozmowach u klienta i prepach (kategoria „Rozmowy”, 9 typów)
stały w dzwonku razem ze wszystkim innym: jeden wiersz na zdarzenie, bez akcji,
część z numerem kandydata zamiast nazwiska. Dzwonek jest czytany w 0–8%
(pomiar 30.09–07.10.2026), a telefon po rozmowie u klienta ma okno 30 minut.

## Decyzje Artura (13.10.2026)

1. Osobna ikona i okienko „Rozmowy” między „Czatami” a dzwonkiem (wariant A
   z makiet: https://claude.ai/artifact/Nt9BUPasXNjSYpZGmEpf37).
2. Dzwonek przestaje pokazywać i liczyć kategorię „Rozmowy”.
3. Pigułka pilna w pasku tylko dla telefonu po rozmowie u klienta.
4. Dymki z akcją.

Doprecyzowania z planu, zaakceptowane razem z nim: wiersz „Brak terminów od
klienta” nie wchodzi do okienka (stan do 30 dni, licznik nigdy by nie gasł);
dymek dostaje każdy typ rozmów, nie tylko trzy (dziś każdy daje dymek dzwonka);
pigułka poniżej 1536 px jest zwarta; kto nie widzi „Kalendarza” w menu, zostaje
przy dzwonku; do okienka trafiają wszystkie przypomnienia kalendarza.

## Co się zmieniło

- **Ikona „Rozmowy”** między „Czatami” a dzwonkiem, dla osób, które widzą
  „Kalendarz” w menu. Licznik = liczba wierszy okienka; czerwony, gdy coś
  dzieje się teraz albo zadanie jest pilne.
- **Okienko** ma trzy części i stopkę:
  - „Teraz” — telefon po rozmowie u klienta z odliczaniem, prep albo rozmowa
    od kwadransa przed startem (prep z przyciskiem „Dołącz”);
  - „Czeka na Ciebie” — wybór i potwierdzenie terminu, brak prepu, prep słaby,
    bez nagrania albo po rozmowie, zaległy debrief; jedna pozycja na kandydata
    w rekrutacji;
  - „Nowe” — potwierdzony termin, zapisany debrief z warunkiem kandydata,
    eskalacja po 2 h, sprawy prepów zespołu u Head of Recruitment, przypomnienia;
  - stopka „Dziś jeszcze” i link do kalendarza.
- **Akcja w wierszu** („Zapisz debrief”, „Wybierz termin”, „Potwierdź”,
  „Zaplanuj Prep 2”, „Przełóż”, „Zobacz ocenę”) otwiera to samo okno co ekran
  „Rozmowy u klienta”, bez zmiany strony.
- **Zadania znikają same po wykonaniu** — pochodzą ze stanu cyklu, nie
  z listy „przeczytane / nieprzeczytane”. Nieaktualny sygnał (termin już
  wybrany, debrief już zapisany) nie zostaje w „Nowe”.
- **Pigułka** zamiast ikony przez okno telefonu po rozmowie: poniżej 1536 px
  ikona telefonu i minuty, szerzej także nazwisko.
- **Dymki**: koniec rozmowy u klienta („Zapisz debrief”, raz na przeglądarkę),
  przypomnienie przed prepem z linkiem Teams („Dołącz”), pozostałe
  powiadomienia kategorii („Pokaż” otwiera okienko).
- **Dzwonek** u osób z okienkiem nie pokazuje, nie liczy i nie gasi kategorii
  „Rozmowy”; pokazuje jednorazową podpowiedź, gdzie się podziały.

Bez migracji i bez nowych typów powiadomień.

## Kod

| Część | Pliki |
|---|---|
| Lista i gaszenie kategorii, `exclude_interviews` w dzwonku | `backend/app/api/notifications.py` |
| Na kogo czeka zadanie, `mine` w zadaniach i agendzie | `backend/app/services/interview_cycle.py`, `backend/app/api/interview_cycle.py` |
| Składanie okienka (czysta funkcja), typy kategorii, parser linków | `frontend/src/lib/interview-window.ts`, `lib/interview-notifications.ts` |
| Zapytania | `frontend/src/lib/api/interviewNotifications.ts`, `lib/api/interviewCycle.ts` |
| Ikona, panel, kontener, okna akcji | `frontend/src/components/v2/shell/InterviewNotificationsDropdown.tsx`, `InterviewActionDialogs.tsx` |
| Dzwonek i gniazdo | `frontend/src/components/NotificationsDropdown.tsx`, `hooks/useNotifications.ts`, `hooks/useHasInterviewsWindow.ts` |
| Harness | `/preview/interview-notifications` |
| Reguły | `docs/claude/powiadomienia/okienko-rozmowy-w-gornym-pasku.md` |

## Weryfikacja

| Co | Stan | Dowód |
|---|---|---|
| Reguła „moje” i wskazanie wykonawcy dla 10 rodzajów zadań | przechodzi | `pytest tests/test_interview_cycle.py` (część bez bazy), 27 testów, 13.10.2026 |
| Strażnicy tras (`test_route_authz_contract`, `test_section_ceiling_contract`, `test_notification_section_access`, `test_authz_guard_matrix`) | przechodzą | lokalnie, Python 3.12 bez bazy; wzorzec `authz_golden/notifications.json` +2 wiersze |
| Lint i format backendu | przechodzą | `ruff check`, `ruff format --check` na zmienionych plikach |
| Testy backendu z bazą (`test_interview_notifications_window.py`, `test_interview_cycle.py`) | w CI | lokalnie nieuruchamiane (bez Postgresa) — sito na PR-ze B2B-net-S-A/NEXUS#2170 |
| Testy frontendu: logika okienka, kontener, dzwonek, gniazdo, strażnicy | przechodzą | `npx vitest run` — pliki zmiany i sąsiednie katalogi, 316 plików, 4751 testów |
| Typy, lint, bramka nieosiągalnych modułów | przechodzą | `npm run type-check`, `npx eslint` na zmienionych plikach, `check-unreachable-modules.mjs` |
| Wygląd okienka i stanów | sprawdzone na harnessie | zrzuty przy 1280×720, 1280×960 i 360 px; przy 360 px bez poziomego przewijania |
| Ikona i pigułka w prawdziwym pasku przy 1280 px z przypiętym menu | mieszczą się | jednorazowa strona z `TopbarV2` (usunięta): pasek 1040 px bez przelewu; wyszukiwarka 136 px z ikoną i 90 px z pigułką przy trzech pozycjach KPI i okruszkach 262 px; okienko 707–1127 px |
| Dymek końca rozmowy i akcja wiersza | sprawdzone w testach i na sondzie | dymek z „Zapisz debrief” widoczny na sondzie; okna akcji w testach kontenera |
| Przegląd kodu i przegląd bezpieczeństwa (niezależni agenci) | uwagi wprowadzone | kod: jeden błąd blokujący — zaległy debrief rozmowy starszej niż 14 dni znikał z okienka (agenda sięga 14 dni) — poprawiony testem; bezpieczeństwo: nic blokującego, dodane `https:` przed otwarciem linku spotkania i domyślne `mine = False` |
| Dymki z gniazda na żywo | niepotwierdzone | lokalnie nie ma backendu; test haka i kontenera pokrywa drogę zdarzenia |
| Wdrożenie, licznik dzwonka i okienko na produkcji | po scaleniu | `/api/health`, zapytania dzwonka z `exclude_interviews=true`, przeklikanie jako rekruter i Delivery Lead |

## Poza zakresem

- Gaszenie sygnałów zadań po stronie serwera przy wykonaniu akcji — nadal wiszą
  jako nieprzeczytane w „Moich zadaniach”.
- Teksty „kandydatem #id” w przypomnieniach po rozmowie (okienko podstawia
  nazwisko samo, „Moje zadania” nie).
- Powiadomienie o zaplanowaniu, przełożeniu albo odwołaniu prepu.
- Wyszukiwarka w pasku przy 1280 px z przypiętym menu zwęża się o szerokość
  nowej ikony (ze 180 px — wyliczone — do zmierzonych 136 px, w oknie telefonu
  do 90 px). Jeśli to za mało,
  najprostsza ulga to schowanie przełączników wyglądu poniżej 1536 px.
