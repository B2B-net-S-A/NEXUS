# Rekrutacja „wersja 3" — raport wdrożenia (21.09.2026)

Makiety: „Wersja 3" (rekrutacja = jedna tabela + panel osoby + okna wysuwane).
Decyzje Artura: patrz sekcja w `CLAUDE.md` „Rekrutacja „wersja 3"".

## Co weszło

| PR | Zakres |
|---|---|
| #1641 | Tabela osób (`components/v2/recruitment/`), panel osoby, okna wysuwane (Zlecenie, Baza pytań, Historia i czat, Szukaj ręcznie), propozycje z bazy, kanban jako przełącznik, aliasy wszystkich starych `?tab=`, inwentarz funkcji + test parytetu, `usePipelineMove`, reguła „kto ma ruch" w dwóch lustrach, migracja `0333_job_proposals` |
| #1657 | Automaty w tle (`0335_recruitment_automations`: nocny przegląd bazy, nowe CV → propozycje, CV firmowe po „Zweryfikowany", podpowiedzi stawki/dostępności z notatek), lista rekrutacji (liczniki etapów, „wymaga ruchu", „Do przejrzenia", sort „Wymaga uwagi"), menu „Więcej", stos wejściowy jako osobny właściciel `review` |
| #1659 | Poprawki po testach UI na produkcji: grupy tabeli nigdy wszystkie zwinięte, panel otwiera pierwszą widoczną osobę, licznik propozycji = widoczne propozycje, status przeglądu w jednej linii, historia w wąskim oknie, podpowiedzi w „Więcej" + stopka ⌘K |
| #1660 | Ujednolicenie silników wyszukiwania (trzy koszyki umiejętności, tryb tekstu, migracja zapisanych wyszukiwań `0336`) — osobny program |

## Testy UI na produkcji (rekrutacja 5094, PKO BP Java Senior)

- Tabela: grupa „Bez ruchu" rozwinięta (6 osób), „Do przejrzenia 461" zwinięta, panel sam otwarty na pierwszej osobie. ✅
- Propozycje z bazy: licznik 35 = liczba widocznych wierszy; źródła „Cała baza 20", „Podobne projekty 16" z deduplikacją; status przeglądu w jednej linii („9600 widocznych z 62673 sprawdzonych · ocena niepełna: 18") z rozwijanymi szczegółami. ✅
- Panel propozycji: wymagania, stawka wobec budżetu, „Dlaczego pasuje". ✅
- „Więcej": każda pozycja z jednozdaniową podpowiedzią, stopka „Wszystko jest też pod ⌘K". ✅
- Testy UI wyłącznie do odczytu — żaden ruch ani zapis na danych prawdziwych kandydatów.

## Silniki (produkcja, odczyt)

| Silnik | Wynik |
|---|---|
| Lista `/api/candidates` (umiejętność + lokalizacja, nazwisko) | filtry poprawne |
| Wyszukiwarka `/api/search/candidates` | `skills_must` działał jako ranking, nie filtr (41 z 50 wyników bez Springa przy „Musi mieć: Java, Spring") → naprawia #1660 |
| `/ai-matches` | sensowny ranking, 8,3 s, bez trybu awaryjnego |
| Pełny przegląd bazy | 62 673 osób w ~262 s, przeżył deploy (2 przejęcia), 9 600 widocznych, 80 mocnych; najwyższy wynik ten sam co w `/ai-matches` |
| Talent Radar | jawne must-have ukrywają 881 osób bez wymagań i 119 ponad budżet — zgodnie z regułą |

## Znane rozbieżności i problemy danych

- Przypinanie pozycji w „Więcej" — niezrobione.
- „Brak opiekuna TAC" świeci na ~4 256 z 4 265 rekrutacji — plakietka bez wartości informacyjnej; do decyzji (ukryć albo ograniczyć do rekrutacji opublikowanych).
- Stawka i dostępność w tabeli najczęściej „—" — puste dane w bazie, nie błąd widoku.
- Kandydaci bez imienia i nazwiska („? ?") potrafią wysoko wchodzić w ranking — wynik importu; backfill nazwisk (`/api/admin/candidates/backfill-names`) nieuruchomiony.
- „Następny krok" w tabeli jest ogólny, dopóki automaty w tle nie przepracują pierwszej nocy.

## Do sprawdzenia po pierwszej nocy

- Okno „Historia i czat" → „Praca w tle" na kilku rekrutacjach.
- Rozmiar `candidate_search` w `GET /api/admin/index-coverage` (przeglądy `origin=auto` giną po 7 dniach).
- Propozycje z nowych CV (`AUTO_MATCH_MODE=propose`) — nic nie trafia wprost do pipeline'u.
- Migracja zapisanych wyszukiwań (#1660): najpierw `POST /api/saved-searches/migrate-semantics?dry_run=true`.
