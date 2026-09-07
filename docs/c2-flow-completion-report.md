# Program „flow rekrutacyjny w języku C2" — raport końcowy

> Decyzja Artura (7.09.2026): „działaj ze wszystkimi ekranami tak jak zrobiłeś makiety".
> Makiety: artefakt „Rekrutacja od zlecenia do umowy" (claude.ai/code, 53c9c6e4…), osiem kroków,
> porównanie z produkcją i inwentarz 200 funkcji („Nic nie znika"). Plan i briefy:
> [c2-flow-program.md](c2-flow-program.md). C2 (warsztat AI Matching, `AIMatchingSection` +
> `JobMatchDock`) pozostał bez zmian przez cały program — był kierunkiem, nie przedmiotem prac.

## Jak to weszło

| Fala | PR | Zakres | Stan |
|---|---|---|---|
| fundament | #1388 | listwa kroków w `JobDetailCompactHeader` (kroki w kolejności procesu, zdjęte „Narzędzia ▾"/„Pozyskaj ▾") | prod `aec2f246` |
| 1 | #1396 (+ #1399) | 01 Lista rekrutacji · 03 Rama źródeł nad C2 · 04 Dok „Karta w procesie" na kanbanie · bugfix licznika kafelków | prod `59514bc` / `33b75ec` |
| 2 | ten PR | 02 Zlecenie i Champion · 05 Screening · 06 CV do klienta · 07 Rozmowy i decyzja · 08 Umowa | — |

Metoda (ta sama w obu falach): trzech agentów implementuje w osobnych worktree od `origin/main`,
każdy kończy PR-em bez merge'a; koordynator zbiera commity cherry-pickiem na gałąź integracyjną
fali, zleca **adwersarialny przegląd** każdego kroku (osobny agent-recenzent) i sam weryfikuje
znaleziska w kodzie backendu, nakłada poprawki, uruchamia bramki raz centralnie
(`tsc --noEmit`, ESLint, vitest, pytest w obrazie weryfikacyjnym) i otwiera jeden PR na falę.
Powód fal: każdy merge na `main` to pełny rebuild Coolify — trzy PR-y naraz to trzy rebuildy
bez powodu. Powód przeglądu: agenci dostarczyli dobry kod z realnymi defektami, których testy
jednostkowe nie łapią (patrz niżej).

## Co powstało, krok po kroku

- **01 Lista** (`JobsListV2`, `JobReadinessDock`): lewa kolumna filtrów z licznikami, mini-lejek
  w wierszu z `stage_breakdown` (jedno GROUP BY na stronę, zero zapytań per wiersz), dok
  „Gotowość zlecenia" z bramką `/readiness`; domyślny widok = lista (jednorazowa migracja
  `nexus-ui` v5). Bugfix: kafelki czytały pola, których API nigdy nie zwracało (zawsze „0/N").
- **02 Zlecenie i Champion** (`ChampionProfileEditor`, wariant `champion` tego samego doku):
  edytor na pełną szerokość, chip stanu sekcji z realnego znacznika pochodzenia, zespół
  i priorytet w doku, karta „Zlecenie" read-only z istniejącym modalem edycji.
- **03 Rama źródeł** (`SourcingHub`): cztery karty (AI Matching · C2 / Wyszukaj manualnie /
  Podobne projekty / Portale) z licznikami nad C2, „Rekomendowani" zwinięte, kompaktowa
  Historia requestu.
- **04 Dok pipeline'u** (`PipelineCandidateDock`, `PipelineFiltersRail`): rail etapów z filtrami
  (przyciemnianie, nie usuwanie — indeksy `@hello-pangea/dnd`), dok z zakładkami i pigułkami
  „Przenieś na etap" przez tę samą gałąź co drag&drop (`requestMove`).
- **05 Screening** (`ScreeningWorkbench`): kolejka → arkusz Championa inline → dok stawki
  z bramką budżetową (lustro `rate_normalization.py`) i ruch na „Zweryfikowany".
- **06 CV do klienta** (`CvHandoffWorkbench`): zweryfikowani → reguły klienta i limit CV →
  generator osadzony (`next/dynamic`) → jedna akcja `link → ruch → stawka`.
- **07 Rozmowy i decyzja** (`JobInterviewsTab`, `InterviewDecisionDock`): etapy zewnętrzne,
  feedback hiring managera (jedyny nowy endpoint programu), oferta/reakcja, decyzja.
- **08 Umowa** (`JobContractTab`): status podpisu, hook „Zatrudniony", braki do aktywacji,
  „Zamknij rekrutację z powodem".

## Co złapał przegląd (i dlaczego testy tego nie widziały)

Każde z tych znalezisk miało zielone testy jednostkowe — mockowały warstwę, w której siedział błąd.

- **Dok listy wchodził w 403 bez kliknięcia**: auto-wybierał pierwszy wiersz bez patrzenia na
  `can_open`, a `GET /api/jobs/{id}` jest fail-closed dla Delivery Leada spoza pary klient–TAC.
- **Dwa sprzeczne werdykty na jednej karcie**: licznik „5/5 · gotowość do searchu" liczył zbiór
  ROZŁĄCZNY z bramką `/readiness` (tytuł/klient/kontekst/≥2 pytania) — mógł stać na zielono nad
  czerwoną bramką. Teraz „kompletność zlecenia".
- **„Claim" dla ról, którym backend zawsze odmawia** (finance/HoR/TCM mają zapis w pipeline,
  ale nie są w `_OWNERSHIP_ELIGIBLE_ROLES`).
- **Bramka doku pipeline'u** blokowała `pending` (backend go nie zna, drag przenosi) i za mało
  blokowała weto HM (backend odrzuca KAŻDY ruch nie-terminalny).
- **Stawka do klienta jako pierwszy, fatalny krok wysyłki**: endpoint jest admin-only i pisze
  na najnowszym etapie — blokowałaby wysyłkę każdemu poza adminem, a u admina lądowała na
  złym etapie. Sekwencja przepisana jak na tablicy; sekret linku (zwracany raz) zachowany
  przy padniętym ruchu.
- **Arkusz screeningu zostawał na historycznym etapie** (`transition_process` nie kopiuje
  `screening_answers`; portal klienta czyta etap najnowszy) — po ruchu przepisywany.
- **Regresja wizualna kafelków** (tytuł ściskany do zera w wąskiej kolumnie) — złapana dopiero
  zrzutem z produkcji; jsdom nie ma layoutu.

## Co świadomie zostało poza programem

- Krok 05: „Odrzuć z powodem" w doku, akceptacja weryfikacji z lewej kolumny (`AdminUser`).
- Krok 06: dok nie zna istniejącej stawki do klienta (`KanbanItem` jej nie niesie).
- Krok 08: kwoty kontraktu i marża (rejestr za sekcją Delivery).
- Kolejki 05/06 nie widzą kubełka „Poza szablonem".
- Lista: filtr „Brak ownera requestu" zawęża bieżącą stronę (backend nie ma `tac_id IS NULL`);
  „Wyszukaj manualnie" bez żywego licznika wyników (płatne zapytanie).

## Jak zweryfikować na produkcji

1. `/jobs` — widok listy domyślny; lewa kolumna z licznikami; mini-lejek; dok z bramką.
2. `/jobs/<id>` — listwa: `Zlecenie i Champion · Pozyskiwanie ▾ · Pipeline [N] · Screening [N]
   · CV do klienta [N] · Rozmowy i decyzja [N] · Umowa [N] · Baza pytań ‖ Historia · Chat`.
3. Każda zakładka kroku: grid `230 px · 1fr · 360 px`, dok przyklejony na `xl`, pod treścią
   na `lg`; brak poziomego scrolla strony; pusto ≠ awaria ≠ 403.
4. `?tab=similar` otwiera ramę źródeł z C2 pod spodem; `?tab=champion` — krok 02.
