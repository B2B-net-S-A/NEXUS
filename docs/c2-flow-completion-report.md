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
| 2 | #1403 | 02 Zlecenie i Champion · 05 Screening · 06 CV do klienta · 07 Rozmowy i decyzja · 08 Umowa | prod `08978d7` |
| 3 | ten PR | parytet z makietami: jobbar z KPI, liczniki filtrów, grupy etapów i karty pipeline'u, dok gotowości z 7 warunkami, nagłówki i zakładki doków w warsztatach 05–08 | — |

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

## Fala 3 — parytet z makietami (8.09.2026)

Po fali 2 Artur obejrzał produkcję: „nie wygląda to tak samo jak makiety". Porównanie krok po
kroku na rekrutacji z makiet (`/jobs/552495`, ZOB-2947, 26 w procesie) pokazało, że układ
trzech kolumn i listwa kroków się zgadzają, a różni się **gęstość**: nagłówek rekrutacji nie
miał klienta, subtytułu ani KPI, panel „Zespół i priorytet" bywał rozwinięty na każdej
zakładce (zapisana preferencja — domyślna wartość była już „zwinięty"; teraz jest stałą
`JOB_HEADER_COLLAPSED_DEFAULT` z testem), listwa obcinała „Baza pytań", lista liczyła tylko
jeden z sześciu szybkich filtrów i to z bieżącej strony, rail pipeline'u miał 15 wierszy zamiast
6 grup, karty nie mówiły, co dalej, dok Championa dzielił gotowość na dwie listy, a warsztaty
05–08 nie miały nagłówków, pigułek i zakładek doku z makiet. Czterech wykonawców (osobne
worktree od `origin/main`, cherry-pick na `claude/flow-wave-3-parity`, jeden PR):

- **Jobbar i listwa** (`JobDetailCompactHeader`, `lib/job-header-kpis.ts`,
  `lib/job-header-subtitle.ts`): `tytuł · klient`, subtytuł (lokalizacja/tryb · budżet PLN/h ·
  deadline · właściciel), trzy KPI zależne od zakładki liczone z tego samego kanbana co
  listwa; „w rankingu / ≥ 75 pkt" czytane WYŁĄCZNIE z cache'u zapytania C2 (`enabled: false`)
  — nagłówek nie wywołuje Qdranta. Dziewięć selektorów kolumn w `lib/pipeline-flow.ts`
  zastąpiło trzy idiomy „ile jest w kolumnie", żeby listwa i jobbar nie pokazywały dwóch liczb
  pod jedną nazwą.
- **01 Lista** (`JobsListV2`, backend `GET /api/jobs/quick-counts` + `owner_missing`):
  sześć liczników jednym zapytaniem (`count(*) FILTER`), predykaty `jobs_*_clause`
  współdzielone z `list_jobs` — testy porównują każdy licznik z `total` listy z tym samym
  filtrem, nie ze stałą. „Brak ownera requestu" (`tac_id IS NULL`) filtrował dotąd tylko
  wczytaną stronę (`lib/jobs-quick-filters.ts` usunięte). Status jako pigułki wyłącznie
  z istniejących wartości (`draft/published/closed`), klient pod tytułem, mini-lejek z liczbami,
  deadline z liczbą dni, dok z nawigacją `‹ N z M ›` (kontrakt `job-list-nav.ts` między listą
  a dokiem), zakładkami Gotowość · Pipeline · Zespół · Historia i stopką „Ostatnia zmiana".
- **02 Zlecenie i Champion** (`JobReadinessDock`, `ReadinessRow`, `ChampionProfileEditor`):
  jedna lista siedmiu warunków (trzy wiersze weryfikacji/briefingu to te same mutacje co
  `ChampionVerificationChecklist` — wyniesione, nie skopiowane), gauge „N / 7" z procentem,
  bramka „Przekaż do searchu" jako jedna linia z rozwinięciem, „Rekomendowane wyszukiwania
  (AI)" inline; edytor w kolejności makiety (Zlecenie → 1 → 3 → 2·4·5 zwinięte, gdy puste → 6).
  Zostało „kompletność zlecenia", nie „gotowość do searchu" — to rozłączny zbiór z bramką
  `/readiness` i pilnuje tego test regresyjny.
- **04 Pipeline** (`groupKanbanColumns`, `lib/pipeline-next-action.ts`, `KanbanBoardV2`,
  `PipelineFiltersRail`, `PipelineCandidateDock`): sześć grup po `category`/`terminal_type`
  (nigdy po nazwie kolumny), „Bez następnej akcji", SLA klienta z karty klienta; puste grupy
  „U klienta"/„Umowa → zatrudnieni" zwijają się do jednej kolumny, która **przyjmuje
  upuszczenie** na pierwszy etap grupy (bez tego pierwsze CV do klienta wymagałoby „Rozwiń
  etapy" — regres złapany przy odbiorze); karta = nazwisko + awatar rekrutera + wiek +
  następna akcja (deterministycznie z kategorii etapu); dok z `‹ N z M ›`, osią czasu etapu
  i „Przenieś na etap: <następny>" tą samą ścieżką co drag&drop. Trzy poprawki układu (łamanie
  nazwisk, wcięcie, padding) wyszły z pomiaru w DOM, nie z testów.
- **05–08 warsztaty** (`workbench-chrome.tsx` — wspólny szkielet nagłówka, kart i doku):
  nagłówki `Krok · Nazwisko` z subtytułem i pigułkami, zakładki doku (Stawka i decyzja ·
  Notatki · Dopasowanie / Wyślij · Linki i historia / Decyzja · Oferta / Po podpisie ·
  Zamówienie · Alerty DL), reguły CV klienta jako lista warunków, marża (podgląd) wyłącznie
  w bloku stawki widocznym dla admina, oś czasu podpisu z `statusHistory`, „Odrzuć z powodem"
  przez `requestMove` (ten sam `RejectionV2`). Braki do aktywacji kontraktu renderują się
  neutralnie, nie zielono — wiersz kontraktu stoi za bramką Delivery, więc ekran nie wie,
  które pola są wypełnione.

**Po deployu (zrzuty z produkcji obok makiet, 8.09 ~09:00):** lista, jobbar, pipeline i cztery
warsztaty odpowiadają makietom. Sześć rzeczy wyszło dopiero na zrzutach i weszło w follow-upie
(jeden PR): pełna nazwa prawna klienta łamała nagłówek na dwa wiersze (klient ucina się
w jednej linii, pełna nazwa w `title`); przy 1440 px listwa kroków łamała się na dwa wiersze
(etykieta „Zespół i priorytet" dopiero od `2xl`, ikona i `title` zawsze); własny etap
„Preparation Meeting" oznaczony w szablonie jako wewnętrzny stał samotnie między dwoma
zwiniętymi zastępnikami — reguła pozycyjna w `groupKanbanColumns` (etap za pierwszą kolumną
klienta jest etapem klienta) zbija „Default B2B" do dziewięciu pozycji, czyli do progu pełnej
karty; dok umowy bez wybranego kandydata powtarzał tytuł rekrutacji w podtytule; etykieta
szybkiego filtra ucinała się przy czterocyfrowym liczniku; klucz preferencji panelu „Zespół
i priorytet" podbity do `:v3`, bo preferencja „rozwinięty" pochodzi z czasów, gdy panel był
jedynym miejscem właściciela i hiring managera. Do tego znalezisko auto-review PR #1410:
`nextActionFor` dla „Zatrudniony" z zaległym `pending`/wetem HM. Po deployu follow-upu listwa
nadal łamała się na dwa wiersze — pomiar w DOM (okno 1615 px: listwa potrzebowała 1448 px,
miała 1261) zamiast zgadywania; ikony kroków i etykieta „Zespół i priorytet" wracają dopiero
od 1800 px, a „Zlecenie i Champion" / „Rozmowy i decyzja" skracają się poniżej 1536 px
(pełna nazwa w `title`).

Poza falą (świadomie, brak źródła danych albo osobny zakres): „Źródło" na tablicy
(`KanbanItem` nie niesie źródła), „Wiadomość" zbiorcza, „Pliki" w doku pipeline'u, ocena ryzyka
kandydata, aktor „ostatniej aktywności", „Zaloguj rozmowę"/„Przełóż (M365)", licznik dni
w stopce Championa (profil nie ma daty utworzenia), przełącznik New/Old w nagłówku CV.

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
