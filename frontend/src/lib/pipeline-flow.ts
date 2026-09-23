/**
 * Czyste helpery kroków 05 („Screening") i 06 („CV do klienta") programu
 * „flow w języku C2" — docs/c2-flow-program.md, PR 6/7.
 *
 * Oba kroki czytają TĘ SAMĄ odpowiedź `GET /api/pipeline/kanban/{job_id}`,
 * którą strona rekrutacji pobiera już dziś dla listwy kroków — żadnego nowego
 * endpointu. Ten moduł nie renderuje niczego i nie woła sieci: przekłada
 * kolumny kanbana na kolejki obu stanowisk i liczy bramkę ruchu. Dzięki temu
 * da się to przetestować bez montowania ekranu, a warstwa widoku nie hoduje
 * własnej kopii tych samych reguł.
 */

import { colId, type KanbanColumn, type KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  CONTRACT_STAGE_NAMES,
  isContractStage,
  isInterviewStage,
} from "@/lib/job-flow-stages";
import { terminalOf } from "@/lib/kanban-terminal";
import { placeStage } from "@/lib/board-stages";
import { formatDate } from "@/lib/utils";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";

/** Legacy-enumy etapów, na których stoją oba stanowiska (`PipelineStage`). */
/** Poczekalnia kandydatów z ogłoszeń (auto-match) — PRZED „Nowi" (migracja 0317). */
export const POSTING_STAGE = "posting";
export const SCREENING_STAGE = "screening";
export const VERIFIED_STAGE = "verified";
export const CV_SENT_STAGE = "cv_sent";
/** Etap decyzji klienta — źródło KPI „akceptacja" w kroku 07. */
export const ACCEPTANCE_STAGE = "acceptance";

export interface FlowQueueEntry {
  item: KanbanItem;
  /** Kolumna, w której karta stoi TERAZ — potrzebna do `requestMove`. */
  col: KanbanColumn;
  colId: string;
}

/**
 * Znajdź kolumnę po legacy-enumie etapu.
 *
 * Szablon rekrutacji może mieć własne nazwy kolumn (`stage_def_id`), ale każda
 * zmapowana kolumna niesie też `stage` z `PipelineStage` — i to po nim, nie po
 * nazwie, rozpoznaje etapy backend (`dst.stage === "cv_sent"` w `KanbanBoardV2`).
 * Kolumna spoza szablonu („Poza szablonem") raportuje `stage: "new"` i nigdy
 * nie jest celem ruchu — nie trafia tu z definicji.
 */
export function findStageColumn(
  columns: KanbanColumn[],
  stage: string,
): KanbanColumn | null {
  return columns.find((c) => c.stage === stage) ?? null;
}

/** Kandydaci stojący na wskazanym etapie, w kolejności z tablicy. */
function entriesForStage(columns: KanbanColumn[], stage: string): FlowQueueEntry[] {
  const col = findStageColumn(columns, stage);
  if (!col) return [];
  return col.items.map((item) => ({ item, col, colId: colId(col) }));
}

/**
 * Kolejka kroku 05: kandydaci w kolumnie Tablicy „Nowi".
 *
 * Od Pipeline v4 (23.09.2026) screening robi się w „Nowych" — kolumna zbiera
 * etapy posting / new / prep_call / screening (`placeStage`, ta sama reguła
 * co Tablica), więc kolejka to wszystkie karty tych kolumn szablonu,
 * w kolejności z tablicy.
 *
 * Świadomie BEZ etapów zewnętrznych (`client_interview` i dalej), na których
 * `KanbanBoardV2` też otwiera arkusz Championa — tam screening robi się
 * DLA KLIENTA przed rozmową i to jest krok 07, nie 05. Wrzucenie ich tutaj
 * zamieniłoby „kto czeka na moją rozmowę" w „kto ma gdziekolwiek arkusz".
 */
export function selectScreeningQueue(columns: KanbanColumn[]): FlowQueueEntry[] {
  const out: FlowQueueEntry[] = [];
  for (const col of columns) {
    if (!isNewColumn(col)) continue;
    for (const item of col.items) out.push({ item, col, colId: colId(col) });
  }
  return out;
}

/**
 * Kolumna szablonu, która na Tablicy wpada do „Nowych" (i nie jest terminalna).
 * Kubełek „Poza szablonem" z tabeli osób (`__off_template__`) nie jest etapem —
 * `placeStage` zrzuca nieznany kod do „Nowych", więc odcinamy go jawnie.
 */
export function isNewColumn(col: KanbanColumn): boolean {
  if (col.category === "terminal" || col.stage === "__off_template__") return false;
  return placeStage(col).column === "new";
}

/**
 * Karty ze stawką PONAD budżet PLN/h rekrutacji — na dowolnym etapie
 * nie-terminalnym.
 *
 * Od 17.09.2026 bramka „Oczekuje" jest usunięta: przekroczenie budżetu nie
 * wstrzymuje karty, tylko jest informacją (odznaka „ponad budżet"). Porównanie
 * idzie z AKTUALNYM budżetem godzinowym rekrutacji (`effective_budget_hourly`,
 * `isOverHourlyBudget`) — tym samym, który pokazuje nagłówek. Lista służy
 * szynie screeningu i KPI — nie blokuje żadnego ruchu.
 */
export function selectOverBudget(
  columns: KanbanColumn[],
  budgetHourly: number | null | undefined,
): FlowQueueEntry[] {
  const out: FlowQueueEntry[] = [];
  if (budgetHourly == null) return out;
  for (const col of columns) {
    if (col.category === "terminal") continue;
    for (const item of col.items) {
      if (isOverHourlyBudget(item, budgetHourly)) {
        out.push({ item, col, colId: colId(col) });
      }
    }
  }
  return out;
}

/**
 * Karty z OSTRZEŻENIEM widocznym na karcie — weto hiring managera — na
 * dowolnym etapie nie-terminalnym.
 *
 * Od 17.09.2026 weto nie blokuje ruchu: serwer odpowiada 409
 * `ELIGIBILITY_WARNING`, a tablica pyta „Przenieś mimo to". Globalnej czarnej
 * listy kanban nie niesie na karcie — ta pojawia się dopiero w oknie ruchu.
 * Ten sam zbiór liczy {@link countHmVeto}.
 */
export function selectWithWarning(columns: KanbanColumn[]): FlowQueueEntry[] {
  const out: FlowQueueEntry[] = [];
  for (const col of columns) {
    if (col.category === "terminal") continue;
    for (const item of col.items) {
      if (item.hm_veto) {
        out.push({ item, col, colId: colId(col) });
      }
    }
  }
  return out;
}

/**
 * Kolejka kroku 06: zweryfikowani, czyli gotowi do wysyłki CV.
 *
 * Karty „ponad budżet" ZOSTAJĄ w kolejce z odznaką — przekroczenie budżetu
 * jest informacją, nie blokadą (bramka „Oczekuje" usunięta 17.09.2026).
 */
export function selectVerifiedQueue(columns: KanbanColumn[]): FlowQueueEntry[] {
  return entriesForStage(columns, VERIFIED_STAGE);
}

/** Ilu kandydatów jest już u klienta — „CV Wysłane" i dalsze etapy zewnętrzne. */
export function countAtClient(columns: KanbanColumn[]): number {
  return columns.reduce((sum, col) => {
    if (col.category === "terminal") return sum;
    if (col.stage === CV_SENT_STAGE || col.category === "external") {
      return sum + col.items.length;
    }
    return sum;
  }, 0);
}

/**
 * Ilu kandydatów stoi w kolumnie.
 *
 * `count` jest liczbą Z SERWERA i to ona zasila licznik „Pipeline" na listwie
 * kroków; `items.length` bywa krótsze, jeśli backend kiedykolwiek przytnie
 * kartę. Klaster KPI w jobbarze mówi o tym samym, co listwa tuż pod nim, więc
 * musi liczyć TAK SAMO — inaczej ten sam ekran pokazuje dwie różne liczby pod
 * dwiema nazwami tego samego zbioru.
 */
function columnSize(col: KanbanColumn): number {
  return col.count ?? col.items?.length ?? 0;
}

const isTerminalColumn = (col: KanbanColumn) => col.category === "terminal";

/** Kandydaci „w procesie" — suma kolumn nie-terminalnych. */
export function countInProcess(columns: KanbanColumn[]): number {
  return columns.reduce(
    (sum, col) => (isTerminalColumn(col) ? sum : sum + columnSize(col)),
    0,
  );
}

/**
 * Kandydaci „u klienta" — WYŁĄCZNIE kolumny `external`.
 *
 * Świadomie węższe niż {@link countAtClient}, które dokłada `cv_sent`. To dwa
 * różne pytania: „komu wysłaliśmy CV" i „kto jest w procesie po stronie
 * klienta". Klaster KPI pokazuje oba obok siebie w kroku 06, więc muszą być
 * rozłączne — inaczej ta sama osoba jest policzona dwa razy w jednym wierszu.
 */
export function countExternal(columns: KanbanColumn[]): number {
  return columns.reduce(
    (sum, col) => (col.category === "external" ? sum + columnSize(col) : sum),
    0,
  );
}

/**
 * Kandydaci stojący na etapie dłużej niż `days` dni — sygnał „utknęli".
 *
 * Karty terminalne są poza zbiorem: odrzucony kandydat „stoi" na swoim etapie
 * bezterminowo i nie jest sprawą do załatwienia. `days_in_stage` bywa
 * nieobecne (starsze wiersze) — brak danych NIE liczy się jako zaległość.
 */
export function countStalled(columns: KanbanColumn[], days: number): number {
  return columns.reduce((sum, col) => {
    if (isTerminalColumn(col)) return sum;
    return (
      sum +
      (col.items ?? []).filter(
        (item) => (item.days_in_stage ?? 0) > days,
      ).length
    );
  }, 0);
}

/** Karty z wetem hiring managera — poza kolumnami terminalnymi. */
export function countHmVeto(columns: KanbanColumn[]): number {
  return columns.reduce((sum, col) => {
    if (isTerminalColumn(col)) return sum;
    return sum + (col.items ?? []).filter((item) => Boolean(item.hm_veto)).length;
  }, 0);
}

/** Kandydaci na etapach kroku 07 „Rozmowy i decyzja". */
export function countInterviewStages(columns: KanbanColumn[]): number {
  return columns.reduce(
    (sum, col) => (isInterviewStage(col) ? sum + columnSize(col) : sum),
    0,
  );
}

/** Kandydaci na etapach kroku 08 „Umowa" (podpis → zatrudnienie → onboarding). */
export function countContractStages(columns: KanbanColumn[]): number {
  return columns.reduce(
    (sum, col) => (isContractStage(col) ? sum + columnSize(col) : sum),
    0,
  );
}

/** Ilu kandydatów stoi na wskazanym legacy-etapie (`PipelineStage`). */
export function countStage(columns: KanbanColumn[], stage: string): number {
  const col = findStageColumn(columns, stage);
  return col ? columnSize(col) : 0;
}

/** Zatrudnieni — rozpoznawani po `terminal_type`, nie po nazwie kolumny. */
export function countHired(columns: KanbanColumn[]): number {
  return columns.reduce(
    (sum, col) => (terminalOf(col) === "hired" ? sum + columnSize(col) : sum),
    0,
  );
}

/**
 * Kandydaci z wysłaną, jeszcze niepodpisaną umową.
 *
 * Rozpoznawane po NAZWIE kolumny i to nie jest tu wyjątek od reguły: etapy
 * podpisu nie mają `legacy_enum_value`, więc backend raportuje dla nich
 * `stage: "new"` — nazwa jest jedynym identyfikatorem, jaki system dla nich ma
 * (patrz `job-flow-stages.ts`). Reużywamy tamtejszą stałą zamiast wpisywać
 * napis drugi raz: dwie kopie tej nazwy rozjeżdżają się przy pierwszej zmianie
 * szablonu i objawiają się cichym zerem.
 */
export function countContractSent(columns: KanbanColumn[]): number {
  const target = CONTRACT_STAGE_NAMES[0].toLocaleLowerCase("pl-PL");
  return columns.reduce((sum, col) => {
    const name = (col.name ?? "").trim().toLocaleLowerCase("pl-PL");
    return name === target ? sum + columnSize(col) : sum;
  }, 0);
}

export interface MoveGateInput {
  item: KanbanItem;
  readOnly: boolean;
  /**
   * Etap docelowy WYPISUJE kandydata z procesu (`rejected`/`withdrawn`)?
   * „Zatrudniony" też jest terminalem, ale nie wypisaniem — backend puszcza go
   * przez bramkę dopuszczalności, więc tu podaje się dla niego `false`.
   */
  terminal?: boolean;
  /**
   * Legacy-enum etapu docelowego (`KanbanColumn.stage`). Wymagany, bo weto
   * hiring managera dotyczy WYŁĄCZNIE etapów, które stawiają kandydata przed
   * klientem — bez celu ruchu bramka nie wie, czy weto w ogóle obowiązuje.
   * Własny etap bez legacy-enuma raportuje `new` i weta nie dotyczy.
   */
  targetStage: string | null;
}

/**
 * Etapy, na których serwer PODNOSI ostrzeżenie o wecie hiring managera — lustro
 * `VETO_ENFORCED_STAGES` z `backend/app/services/hiring_manager_verdicts.py`.
 * Od 17.09.2026 weto nie blokuje ruchu: serwer odpowiada 409
 * `ELIGIBILITY_WARNING`, a tablica pyta „Przenieś mimo to".
 */
export const HM_VETO_ENFORCED_STAGES: ReadonlySet<string> = new Set([
  "cv_sent",
  "client_interview",
]);

/**
 * Powód, dla którego ruchu NIE wolno wykonać — albo `null`, gdy wolno.
 *
 * Od 17.09.2026 (decyzja właściciela „żadna bramka nie blokuje przepływu")
 * jedyną twardą blokadą jest brak prawa zapisu. Karta „Oczekuje" już nie
 * powstaje, a weto hiring managera, czarna lista, NDA i konkurent są
 * OSTRZEŻENIAMI serwera (409 `ELIGIBILITY_WARNING`, okno „Przenieś mimo to" —
 * `lib/pipeline-eligibility-warning.ts`). `terminal` i `targetStage` zostają
 * w sygnaturze dla zgodności wołających (warsztaty 05–07).
 */
export function moveBlockedReason({ readOnly }: MoveGateInput): string | null {
  if (readOnly) return "Tylko do odczytu — brak prawa zapisu w tym pipeline.";
  return null;
}

/**
 * Ostrzeżenie o wecie hiring managera, które serwer podniesie przy ruchu na
 * `targetStage` — albo `null`. Lustro `VETO_ENFORCED_STAGES`: dotyczy tylko
 * etapów stawiających kandydata przed klientem, a ruchy wypisujące
 * (`terminal`) go omijają. To INFORMACJA, nie blokada — pojedynczy ruch pyta
 * „Przenieś mimo to".
 */
export function hmVetoWarningReason({
  item,
  terminal = false,
  targetStage,
}: Pick<MoveGateInput, "item" | "terminal" | "targetStage">): string | null {
  if (terminal || !item.hm_veto) return null;
  if (targetStage == null || !HM_VETO_ENFORCED_STAGES.has(targetStage)) return null;
  const when = item.hm_veto.rejected_at
    ? ` (${formatDate(item.hm_veto.rejected_at)})`
    : "";
  return (
    `hiring manager tej rekrutacji już odrzucił tego kandydata${when} — ` +
    `${item.hm_veto.rejection_reason_name}`
  );
}

/**
 * Powód, dla którego ruch ZBIORCZY pomija kartę — albo `null`.
 *
 * Ruch zbiorczy nie ma okna „Przenieś mimo to" (serwer odrzuca paczkę
 * z ostrzeżeniem twardym 409), więc tablica pomija z wyjaśnieniem karty
 * z ostrzeżeniem widocznym na karcie (weto HM) zamiast liczyć je jako nieudane.
 * Taką kartę przenosi się pojedynczo, z potwierdzeniem.
 */
export function bulkMoveSkipReason(input: MoveGateInput): string | null {
  return moveBlockedReason(input) ?? hmVetoWarningReason(input);
}

export interface PrimaryForwardMove {
  /** Etap, na który dok proponuje ruch naprzód — `null`, gdy nie proponuje. */
  target: KanbanColumn | null;
  /**
   * Etap, który stoi na drodze naprzód, i powód blokady. Od 17.09.2026 zawsze
   * `null` (weto HM nie blokuje) — pole zostaje dla zgodności konsumentów.
   */
  blocked: { col: KanbanColumn; reason: string } | null;
}

/**
 * Główna akcja „naprzód" doku karty: PIERWSZY etap nieterminalny PO bieżącym
 * w kolejności szablonu (terminalne pomijamy — „Odrzuć z powodem" to osobny
 * przycisk, a „Zatrudniony" nie jest krokiem naprzód z doku).
 *
 * Od 17.09.2026 weto hiring managera nie zatrzymuje szukania — serwer ostrzega
 * przy ruchu i pyta „Przenieś mimo to". Dok nie proponuje ruchu wyłącznie
 * wtedy, gdy tablica jest tylko do odczytu.
 */
export function primaryForwardMove({
  item,
  columns,
  currentColId,
  readOnly,
}: {
  item: KanbanItem;
  columns: KanbanColumn[];
  currentColId: string;
  readOnly: boolean;
}): PrimaryForwardMove {
  const none: PrimaryForwardMove = { target: null, blocked: null };
  const currentIndex = columns.findIndex((c) => colId(c) === currentColId);
  if (currentIndex < 0) return none;
  for (let i = currentIndex + 1; i < columns.length; i += 1) {
    const col = columns[i];
    if (terminalOf(col) != null) continue;
    const reason = moveBlockedReason({
      item,
      readOnly,
      terminal: false,
      targetStage: col.stage,
    });
    // Jedyna blokada to brak prawa zapisu — wtedy dok nie proponuje nic
    // (jak dotąd), zamiast wskazywać „zablokowany" etap.
    if (!reason) return { target: col, blocked: null };
    return none;
  }
  return none;
}

/** Imię i nazwisko z karty, z uczciwym fallbackiem. */
export function itemFullName(item: KanbanItem): string {
  return `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
}

/** Maksymalnie tyle nazwisk z powodami w komunikacie ruchu zbiorczego. */
export const BULK_FAILURE_NAMES_SHOWN = 3;

/**
 * Komunikat nieudanego ruchu zbiorczego (audyt 22.09 r2, REC-06).
 *
 * Ruch zbiorczy jest cichy per kandydat (nie ma okna „Przenieś mimo to"), więc
 * dotąd kończył się samym „Nie udało się przenieść 2 z 5" — bez tego, KOGO
 * i DLACZEGO (np. weto hiring managera). Teraz: do 3 nazwisk z powodami,
 * reszta jako „i N więcej".
 */
export function bulkMoveFailureMessage(
  failures: readonly { name: string; reason: string }[],
  total: number,
): string {
  const head = `Nie udało się przenieść ${failures.length} z ${total} kandydatów`;
  if (failures.length === 0) return `${head}.`;
  const shown = failures
    .slice(0, BULK_FAILURE_NAMES_SHOWN)
    .map((f) => `${f.name} — ${f.reason.replace(/[.\s]+$/, "")}`)
    .join("; ");
  const rest = failures.length - BULK_FAILURE_NAMES_SHOWN;
  return `${head}: ${shown}${rest > 0 ? ` (i ${rest} więcej)` : ""}.`;
}

// ── Grupy etapów (krok 04 Pipeline, fala 3 „parytet z makietami") ──────
//
// Lewa kolumna Pipeline'u pokazuje SZEŚĆ grup zamiast piętnastu wierszy —
// „Default B2B" ma trzynaście pustych kolumn i płaska lista etapów jest
// w praktyce listą zer. Grupa jest wyłącznie WIDOKIEM: nie zmienia celów
// ruchu, kolejności kolumn ani niczego, co czyta `onDragEnd`.
//
// Przynależność liczy się z `category` / `terminal_type` / legacy `stage`,
// NIGDY z polskiej nazwy kolumny — nazwy są edytowalne per szablon
// (`pipeline_stage_defs.name`), więc reguła po nazwie rozjeżdża się przy
// pierwszej rekrutacji, która nazwie etap po swojemu. Wyjątkiem są dwa
// etapy podpisu, których backend NIE mapuje na żaden legacy enum — te
// rozpoznaje `isContractStage` po nazwie i jest to ta sama, jedyna nazwa,
// której używa hook podpisu po stronie serwera (patrz `job-flow-stages.ts`).

export type PipelineGroupKey =
  | "posting"
  | "intake"
  | "screening"
  | "verification"
  | "client"
  | "contract"
  | "closed";

export const PIPELINE_GROUP_LABEL: Record<PipelineGroupKey, string> = {
  posting: "Ogłoszenia",
  intake: "Nowi / Analiza CV",
  screening: "Screening",
  verification: "Zweryfikowani",
  client: "U klienta (CV → interview)",
  contract: "Umowa → zatrudnieni",
  closed: "Odrzuceni / wycofani",
};

/** Krótka etykieta na zwiniętą kolumnę-zastępnik na tablicy. */
export const PIPELINE_GROUP_SHORT_LABEL: Record<PipelineGroupKey, string> = {
  posting: "Ogłoszenia",
  intake: "Nowi",
  screening: "Screening",
  verification: "Zweryfikowani",
  client: "U klienta",
  contract: "Umowa → zatrudnieni",
  closed: "Zamknięci",
};

const GROUP_ORDER: readonly PipelineGroupKey[] = [
  "posting",
  "intake",
  "screening",
  "verification",
  "client",
  "contract",
  "closed",
];

export interface PipelineColumnGroup {
  key: PipelineGroupKey;
  label: string;
  columns: KanbanColumn[];
  /** Suma kandydatów w kolumnach grupy. */
  count: number;
}

/**
 * Grupa kolumny liczona BEZ znajomości reszty tablicy.
 *
 * Wystarcza wszędzie poza jednym miejscem: własny etap wewnętrzny stojący
 * PO screeningu (w „Default B2B" są to „Przepuszczony przez DZ" i „Wysłać
 * do Cpro") nie ma legacy enuma, więc bez pozycji w szablonie nie da się go
 * odróżnić od etapu wejściowego. Tę różnicę dokłada
 * {@link groupKanbanColumns}, które widzi całą listę.
 */
export function groupKeyForColumn(col: KanbanColumn): PipelineGroupKey {
  // Kontrakt PRZED terminalem: „Zatrudniony" JEST terminalem (`hired`), ale
  // należy do „Umowa → zatrudnieni". Odwrotna kolejność wrzuciłaby go do
  // „Odrzuceni / wycofani", czyli pod nagłówek, który mówi coś przeciwnego.
  if (isContractStage(col)) return "contract";
  const terminal = terminalOf(col);
  if (terminal != null || col.category === "terminal") return "closed";
  // Kandydaci z ogłoszeń mają własną grupę — inaczej zlewaliby się z „Nowi"
  // i grupa wejściowa liczyłaby ludzi, których nikt jeszcze nie przejrzał.
  if (col.stage === POSTING_STAGE) return "posting";
  if (col.stage === SCREENING_STAGE) return "screening";
  if (col.stage === VERIFIED_STAGE) return "verification";
  if (col.stage === CV_SENT_STAGE || col.category === "external") return "client";
  return "intake";
}

/**
 * Kolumny szablonu pogrupowane w sześć wierszy lewej kolumny.
 *
 * Zwraca WYŁĄCZNIE grupy, które ten szablon faktycznie ma (choćby puste) —
 * wiersz „U klienta 0" dla szablonu bez etapów zewnętrznych obiecywałby etap,
 * którego nie ma. Kolejność grup jest stała; kolejność kolumn wewnątrz grupy
 * pozostaje taka jak w szablonie.
 */
export function groupKanbanColumns(columns: KanbanColumn[]): PipelineColumnGroup[] {
  const screeningIndex = columns.findIndex((c) => c.stage === SCREENING_STAGE);
  // Pierwsza kolumna „u klienta" (CV wysłane albo cokolwiek zewnętrznego):
  // od niej w prawo proces toczy się po stronie klienta.
  const firstClientIndex = columns.findIndex(
    (c) => groupKeyForColumn(c) === "client",
  );
  const buckets = new Map<PipelineGroupKey, KanbanColumn[]>();

  columns.forEach((col, index) => {
    let key = groupKeyForColumn(col);
    // Etap wewnętrzny STOJĄCY PO screeningu to etap weryfikacji/przekazania,
    // nie wejście. Bez tej korekty „Przepuszczony przez DZ" trafiałby do
    // „Nowi / Analiza CV" i grupa wejściowa liczyłaby ludzi, których nikt
    // już nie analizuje.
    if (key === "intake" && screeningIndex >= 0 && index > screeningIndex) {
      key = "verification";
    }
    // Własny etap bez legacy enuma, oznaczony w szablonie jako wewnętrzny,
    // ale STOJĄCY między etapami klienta („Preparation Meeting" w „Default
    // B2B" stoi za „CV Wysłane") — to spotkanie u klienta, nie weryfikacja.
    // Bez tej korekty na tablicy pojawiała się samotna kolumna między dwoma
    // zwiniętymi zastępnikami, a liczba kolumn przekraczała próg trybu
    // przeglądowego, więc karty zwężały się do trybu kompaktowego.
    if (key === "verification" && firstClientIndex >= 0 && index > firstClientIndex) {
      key = "client";
    }
    const bucket = buckets.get(key);
    if (bucket) bucket.push(col);
    else buckets.set(key, [col]);
  });

  return GROUP_ORDER.filter((key) => buckets.has(key)).map((key) => {
    const groupColumns = buckets.get(key) as KanbanColumn[];
    return {
      key,
      label: PIPELINE_GROUP_LABEL[key],
      columns: groupColumns,
      count: groupColumns.reduce((sum, c) => sum + c.count, 0),
    };
  });
}

/**
 * Ton kropki wiersza kolejki wg wieku na etapie (makieta kroków 05–08).
 *
 * Trzy stany, nie dwa: `neutral` znaczy „nie wiemy, ile ta karta tu stoi"
 * (`days_in_stage` bywa nieobecne), a nie „jest w porządku" — zielona kropka
 * przy nieznanym wieku obiecuje wiedzę, której nie mamy.
 *
 * Z SLA klienta (karta klienta, `sla_business_days`) progi liczą się od niego:
 * przekroczone SLA to `bad`, 60 % SLA to `warn`. Bez SLA zostają progi
 * z makiety — 7 dni `bad`, 3 dni `warn`.
 */
export function stageAgeTone(
  days: number | null | undefined,
  slaDays?: number | null,
): "neutral" | "ok" | "warn" | "bad" {
  if (days == null || !Number.isFinite(days)) return "neutral";
  const hardLimit = slaDays != null && slaDays > 0 ? slaDays : 7;
  const softLimit =
    slaDays != null && slaDays > 0 ? Math.ceil(slaDays * 0.6) : 3;
  if (days >= hardLimit) return "bad";
  if (days >= softLimit) return "warn";
  return "ok";
}

/**
 * Stawka oczekiwana z karty jako „118 PLN/h" — albo `null`, gdy jej nie ma.
 *
 * Karta niesie `expected_rate_value` jako string LUB number (backend zwraca
 * `Numeric` jako string), więc formatowanie mieszka w jednym miejscu, a nie
 * w każdej szynie z osobna.
 */
export function formatExpectedRate(item: KanbanItem): string | null {
  const raw = item.expected_rate_value;
  if (raw == null || raw === "") return null;
  const unit = item.expected_rate_unit;
  const shortUnit =
    unit === "hourly"
      ? "PLN/h"
      : unit === "daily"
        ? "PLN/dzień"
        : unit === "monthly"
          ? "PLN/mc"
          : (item.expected_rate_currency ?? "PLN");
  return `${raw} ${shortUnit}`;
}
