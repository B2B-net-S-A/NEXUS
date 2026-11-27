// Rekrutacja ćwiczebna Poligonu w pamięci karty przeglądarki.
//
// Odczyty o rekrutacji ćwiczebnej i jej osobach (identyfikatory 990000+)
// podaje zestaw z `dataset.json` (buduje go `backend/scripts/build_poligon_dataset.py`).
// Zapisy zmieniają tylko ten stan. Żaden zapis nie idzie do serwera: to, czego
// poligon nie umie, kończy się odmową z komunikatem, nie prawdziwym zapisem.
// Odczyty spoza rekrutacji ćwiczebnej (pasek górny, powiadomienia) idą do API
// jak zwykle — wtedy `handle` zwraca `"network"`. Narzędzia rekrutera z ćwiczeń
// z 16.11.2026 (telefon, terminy u klienta, CV z pliku, zapisane wyszukiwania,
// listy, czat, asystent CV, Jarvis) i terminy od klienta Delivery Leada są w `tools.ts`.

import { BOARD_COLUMN_ORDER, placeStage, type BoardColumnKey, type StageLike } from "@/lib/board-stages";

import { forViewer, NO_AMOUNTS, type PoligonViewer } from "./amounts";
import { createTools } from "./tools";

/** Odczyt narzędzia do własnych obliczeń: bez zdejmowania kwot (wynik nie idzie na ekran wprost). */
const ALL_AMOUNTS: PoligonViewer = { amounts: true, companyMargin: true };

export interface PoligonPerson {
  candidate_id: number;
  entry_id: number;
  name: string;
  lastname: string;
}

export interface PoligonDataset {
  meta: {
    job_id: number;
    job_reference?: string;
    client_id: number;
    client_name?: string;
    template_candidate_id: number;
    template_entry_id: number;
    /** Osoba na „Rozmowie u klienta”, która czeka na wybór terminu z kandydatem. */
    slot_candidate_id: number;
    /** Osoba, którą NEXUS „odczytuje” z pliku CV w ćwiczeniu. */
    cv_candidate_id: number;
    trainers: Record<string, { id: number; name: string }>;
    people: PoligonPerson[];
    /** Osoby po stronie klienta ćwiczebnego (kontakt klienta), nie kandydaci. */
    client_people?: string[];
    /** Odpowiedzi wymyślone w skrypcie (klient ćwiczebny): kwoty zdejmuje `amounts.ts`. */
    fiction_responses?: string[];
  };
  responses: Record<string, unknown>;
}

export interface PoligonRequest {
  method: string;
  /** Ścieżka z ewentualnym `?query` (bez hosta). */
  url: string;
  params?: Record<string, unknown> | null;
  body?: unknown;
  /** Zalogowana osoba — jej są zapisane wyszukiwania i listy na poligonie. */
  viewerId?: number | null;
  /** Co osoba widzi z kwot klienta ćwiczebnego (z jej uprawnień, jak serwer). */
  viewer?: PoligonViewer;
  /** Ustawia i zdejmuje stop do podpisu przedwstępnej (DL, HoR, admin — 0762). */
  canSetPreContractStop?: boolean;
  /** Wstrzymuje i wznawia rekrutację (DL, HoR, admin — `WorkStateEditor`, 26.11.2026). */
  canManageHold?: boolean;
}

export interface PoligonResponse {
  status: number;
  data: unknown;
}

export type PoligonAction =
  | {
      type: "move";
      candidateId: number;
      fromStage: string | null;
      toStage: string | null;
      rejectionReasonId: number | null;
      rejectionReasonName: string | null;
      rejectionNote: string;
      /** „Wróć do poprawy” z przeglądu Delivery Leada: pola do poprawy. */
      fixFields: string[];
      /** Wysyłka z przeglądu Delivery Leada: stawka do klienta. */
      clientRate: { value: number; unit: string; currency: string } | null;
    }
  | { type: "claim"; candidateId: number }
  | { type: "note"; candidateId: number | null; content: string }
  | { type: "screening"; candidateId: number; sheetSaved: boolean; fields: Record<string, string> }
  | { type: "assign"; candidateId: number; jobId: number }
  | { type: "screening_call"; candidateId: number; start: string }
  | { type: "slot_choose"; candidateId: number; index: number }
  /** Delivery Lead wpisał terminy od klienta (`POST /api/interview-cycle/slots`). */
  | { type: "slot_request"; candidateId: number; starts: string[]; durationMinutes: number; replaced: boolean }
  | { type: "cv_upload"; candidateId: number }
  | { type: "saved_search"; notify: boolean; criteria: boolean; name: string }
  | { type: "pool_add"; candidateId: number; poolId: number }
  | { type: "chat"; content: string; mentions: number[] }
  | { type: "cv_command"; command: string; operations: number }
  | { type: "cv_applied"; operations: number }
  | { type: "jarvis"; message: string; candidateId: number | null }
  | { type: "view"; path: string; query: Record<string, string> }
  /** Serwer odmówiłby ruchu na „Zweryfikowany” — czego brakuje. */
  | { type: "gate"; candidateId: number; missing: string[] }
  | { type: "blocked"; method: string; path: string }
  | { type: "missing"; key: string };

export const POLIGON_ID_MIN = 990_000;
/** Zapis zaliczonego ćwiczenia (`novelty_progress`, id `poligon-…`) — idzie do API. */
export const POLIGON_PROGRESS = /^\/api\/novelties\/poligon-[a-z0-9-]+\/events$/;
const NOVELTY_EVENTS = /^\/api\/novelties\/[a-z0-9-]+\/events$/;
/** Etapy lekcji nowości (23.11.2026) — przebieg idzie na Poligonie, a zapis musi dojść do serwera. */
const LESSON_EVENTS = /^\/api\/novelties\/lessons\/[a-z0-9-]+\/events$/;
export const POLIGON_ID_MAX = 999_999;
const DAY_MS = 86_400_000;
/** Bramka „Zweryfikowany” działa tylko przy wejściu z tych kolumn (serwer:
 *  `assert_verified_requirements`) — zwrot z „QC CV” do poprawy jej nie przechodzi. */
const GATED_FROM = new Set(["new", "screening"]);

export const BLOCKED_WRITE_MESSAGE =
  "Na poligonie ta akcja się nie zapisuje. W prawdziwej rekrutacji zadziała normalnie.";
const MISSING_MESSAGE = "Tego ekranu nie ma jeszcze na poligonie.";

function isRecordedStatus(data: unknown): data is { "@status": number } {
  return typeof data === "object" && data !== null && typeof (data as Record<string, unknown>)["@status"] === "number";
}

type Json = unknown;
type KanbanItem = Record<string, Json> & { candidate_id: number; stage?: string; stage_def_id?: number };
type KanbanColumn = Record<string, Json> & { stage?: string; stage_def_id?: number; items: KanbanItem[]; count?: number };

function clone<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);
}

/** Dzień za `workdays` dni robocze (pon.–pt.) od `now`, o godzinie `hh:mm` UTC. */
function workdayAt(now: number, workdays: number, hh: number, mm: number): string {
  const day = new Date(now);
  for (let left = workdays; left > 0; ) {
    day.setUTCDate(day.getUTCDate() + 1);
    if (day.getUTCDay() !== 0 && day.getUTCDay() !== 6) left -= 1;
  }
  return new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hh, mm)).toISOString();
}

/**
 * `@rel:-3.2` → data sprzed 3,2 dnia, `@reld:-3` → sam dzień, `@relt:2T09:00` → za
 * 2 dni robocze o 9:00 UTC (terminy u klienta i prepy: pełne godziny, bez weekendu),
 * `@relm:-1` → poprzedni miesiąc (`2026-10`; rozliczenie klienta ćwiczebnego),
 * `@releom:-2:1` → ostatni dzień miesiąca o 1 po miesiącu dnia sprzed 2 dni
 * (koniec okresu wypowiedzenia „liczonego od kolejnego miesiąca”).
 */
export function resolveDates(value: Json, now: number): Json {
  if (typeof value === "string") {
    const at = /^@relt:(\d+)T(\d{2}):(\d{2})$/.exec(value);
    if (at) return workdayAt(now, Number(at[1]), Number(at[2]), Number(at[3]));
    const month = /^@relm:(-?\d+)$/.exec(value);
    if (month) {
      const d = new Date(now);
      return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + Number(month[1]), 1)).toISOString().slice(0, 7);
    }
    const eom = /^@releom:(-?\d+):(-?\d+)$/.exec(value);
    if (eom) {
      const d = new Date(now + Number(eom[1]) * DAY_MS);
      return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + Number(eom[2]) + 1, 0)).toISOString().slice(0, 10);
    }
    if (value.startsWith("@rel:")) return new Date(now + Number(value.slice(5)) * DAY_MS).toISOString();
    if (value.startsWith("@reld:")) return new Date(now + Number(value.slice(6)) * DAY_MS).toISOString().slice(0, 10);
    return value;
  }
  if (Array.isArray(value)) return value.map((v) => resolveDates(v, now));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolveDates(v, now)]));
  }
  return value;
}

function isPoligonId(n: number): boolean {
  return n >= POLIGON_ID_MIN && n <= POLIGON_ID_MAX;
}

/** Czy żądanie dotyczy rekrutacji ćwiczebnej (jakikolwiek identyfikator 990000+). */
export function mentionsPoligon(text: string): boolean {
  return (text.match(/\b\d{6}\b/g) ?? []).some((m) => isPoligonId(Number(m)));
}

function splitUrl(req: PoligonRequest): { path: string; query: Array<[string, string]> } {
  const [rawPath, rawQuery = ""] = req.url.split("?");
  const path = rawPath.replace(/^https?:\/\/[^/]+/, "");
  const query: Array<[string, string]> = [...new URLSearchParams(rawQuery).entries()];
  for (const [k, v] of Object.entries(req.params ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    query.push([k, Array.isArray(v) ? v.join(",") : String(v)]);
  }
  return { path, query };
}

/** Klucz zestawu: posortowane parametry bez dat i list osób (tak jak w skrypcie budującym). */
function datasetKey(method: string, path: string, query: Array<[string, string]>): string {
  const kept = query
    .filter(([k, v]) => k !== "user_ids" && !/^\d{4}-\d{2}-\d{2}/.test(v))
    .sort(([a], [b]) => a.localeCompare(b));
  const qs = new URLSearchParams(kept).toString();
  return `${method.toUpperCase()} ${path}${qs ? `?${qs}` : ""}`;
}

export function createPoligonStore(dataset: PoligonDataset, now: number = Date.now()) {
  const meta = dataset.meta;
  const responses = resolveDates(dataset.responses, now) as Record<string, Json>;
  const people = new Map(meta.people.map((p) => [p.candidate_id, p]));
  const peopleByEntry = new Map(meta.people.map((p) => [p.entry_id, p]));
  const template = people.get(meta.template_candidate_id);
  const fiction = new Set(meta.fiction_responses ?? []);

  const kanbanKey = `GET /api/pipeline/kanban/${meta.job_id}`;
  const kanban = clone(responses[kanbanKey]) as { columns: KanbanColumn[] } | undefined;
  const addedNotes = new Map<number, Array<Record<string, Json>>>();
  /** Zapisany screening osoby: arkusz i pola karty („Dlaczego”, lokalizacja…). */
  const screenings = new Map<number, { sheet: Record<string, Json> | null; fields: Record<string, string>; version: number }>();
  const listeners = new Set<(action: PoligonAction) => void>();
  let nextNoteId = 999_001;

  function emit(action: PoligonAction): void {
    for (const fn of listeners) fn(action);
  }

  /** Panel osoby: odpowiedzi nagrano dla jednej osoby — inne osoby dostają tę samą treść ze swoim imieniem. */
  function toTemplate(text: string): { text: string; person: PoligonPerson | null } {
    let person: PoligonPerson | null = null;
    const out = text.replace(/\b\d{6}\b/g, (m) => {
      const n = Number(m);
      const byCandidate = people.get(n);
      if (byCandidate && n !== meta.template_candidate_id) {
        person = byCandidate;
        return String(meta.template_candidate_id);
      }
      const byEntry = peopleByEntry.get(n);
      if (byEntry && n !== meta.template_entry_id) {
        person = byEntry;
        return String(meta.template_entry_id);
      }
      return m;
    });
    return { text: out, person };
  }

  function asPerson(value: Json, person: PoligonPerson | null): Json {
    if (!person || !template) return value;
    const swap = (v: Json): Json => {
      if (typeof v === "number") {
        if (v === meta.template_candidate_id) return person.candidate_id;
        if (v === meta.template_entry_id) return person.entry_id;
        return v;
      }
      if (typeof v === "string") {
        return v
          .replaceAll(`${template.name} ${template.lastname}`, `${person.name} ${person.lastname}`)
          .replace(new RegExp(`^${template.name}$`), person.name)
          .replace(new RegExp(`^${template.lastname}$`), person.lastname);
      }
      if (Array.isArray(v)) return v.map(swap);
      if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, swap(x)]));
      return v;
    };
    return swap(value);
  }

  function findItem(candidateId: number): { column: KanbanColumn; item: KanbanItem } | null {
    for (const column of kanban?.columns ?? []) {
      const item = column.items.find((i) => i.candidate_id === candidateId);
      if (item) return { column, item };
    }
    return null;
  }

  function rejectionReasons(): Array<{ id: number; name: string }> {
    const tpl = Object.entries(responses).find(([k]) => k.startsWith("GET /api/pipeline-templates/"));
    const reasons = (tpl?.[1] as { rejection_reasons?: Array<{ id: number; name: string }> } | undefined)?.rejection_reasons;
    return reasons ?? [];
  }

  function entryOf(candidateId: number): number | null {
    return people.get(candidateId)?.entry_id ?? null;
  }

  const REQUIREMENTS_KEY = `GET /api/pipeline/move-requirements?candidate_id=${meta.template_candidate_id}&job_id=${meta.job_id}&to_stage_def_id=`;

  function recordedRequirements(): { items: Array<Record<string, Json> & { key: string; status: string; blocking: boolean; label: string }> } & Record<string, Json> {
    const key = Object.keys(responses).find((k) => k.startsWith(REQUIREMENTS_KEY));
    return clone((key ? responses[key] : { items: [] }) as never);
  }

  /** Braki przed „Zweryfikowany” wg zapisanego screeningu (te same klucze co serwer). */
  function verifiedMissing(candidateId: number): Array<{ key: string; label: string }> {
    const saved = screenings.get(candidateId);
    return recordedRequirements()
      .items.filter((item) => item.blocking)
      .filter((item) => {
        if (item.key === "screening_sheet") return !saved?.sheet;
        if (item.status === "ok") return false;
        return !(saved?.fields[item.key] ?? "").trim();
      })
      .map((item) => ({ key: item.key, label: item.label }));
  }

  /** Stop do podpisu przedwstępnej (0762): karta z `pre_contract.stop_column`
   *  nie wchodzi na tę kolumnę ani dalej — także u Delivery Leada (lustro
   *  `pre_contract_stop.assert_pre_contract_signed`). */
  function preContractStop(candidateId: number, to: KanbanColumn | null): { detail: string; message: string } | null {
    const meta = findItem(candidateId)?.item.pre_contract as { stop_column?: string | null; label?: string } | null | undefined;
    const stop = meta?.stop_column as BoardColumnKey | null | undefined;
    if (!stop || !to) return null;
    const at = BOARD_COLUMN_ORDER.indexOf(stop);
    if (at < 0 || BOARD_COLUMN_ORDER.indexOf(placeStage(to as StageLike).column) < at) return null;
    return {
      detail: String(meta?.label ?? ""),
      // Tekst jak `pre_contract_stop.stop_message` (na Poligonie stop pochodzi z ustawienia rekrutacji).
      message:
        "Osoba czeka na podpis umowy przedwstępnej (przed wysłaniem CV; ustawienie rekrutacji). " +
        "Blokadę zdejmuje Delivery Lead albo Head of Recruitment w panelu osoby › Umowa.",
    };
  }

  /** „Przesuń dalej”: wymagania liczone ze stanu poligonu, nie z nagrania. */
  function moveRequirements(query: Array<[string, string]>): PoligonResponse {
    const candidateId = Number(query.find(([k]) => k === "candidate_id")?.[1]);
    const toDef = Number(query.find(([k]) => k === "to_stage_def_id")?.[1]);
    const from = findItem(candidateId)?.column ?? null;
    const to = kanban?.columns.find((c) => c.stage_def_id === toDef) ?? null;
    const recorded = recordedRequirements();
    const base = { ...recorded, from_column: from?.stage ?? null, to_column: to?.stage ?? null, skipped_columns: [], owner_note: null };
    const stop = preContractStop(candidateId, to);
    if (stop) {
      const item = {
        key: "pre_contract",
        label: "Umowa przedwstępna niepodpisana — osoba stoi do podpisu",
        detail: stop.detail,
        status: "missing",
        blocking: true,
        action: { kind: "open_pre_contract", label: "Otwórz umowę", stage_id: entryOf(candidateId) },
        column: to ? placeStage(to as StageLike).column : null,
      };
      return { status: 200, data: { ...base, items: [item], primary: { kind: "blocked", label: "Najpierw podpis umowy przedwstępnej", target_stage_def_id: null } } };
    }
    if (to?.stage !== "verified" || !GATED_FROM.has(String(from?.stage ?? ""))) {
      return { status: 200, data: { ...base, items: [], primary: { kind: "move", label: `Przesuń: ${String(to?.label ?? to?.name ?? "dalej")}`, target_stage_def_id: toDef } } };
    }
    const missingList = verifiedMissing(candidateId);
    const missing = new Set(missingList.map((m) => m.key));
    // Okno „Przesuń dalej” i ramka „Następny etap” pokazują braki — to ta sama bramka co odmowa serwera.
    if (missingList.length) emit({ type: "gate", candidateId, missing: missingList.map((m) => m.label) });
    const items = recorded.items.map((item) =>
      item.blocking && !missing.has(item.key) ? { ...item, status: "ok", detail: null, action: null } : item,
    );
    const first = recorded.items.find((i) => missing.has(i.key));
    return {
      status: 200,
      data: {
        ...base,
        items,
        primary: first
          ? { kind: "blocked", label: `Najpierw uzupełnij: ${first.label}`, target_stage_def_id: null }
          : { kind: "move", label: "Przesuń: Przygotowanie CV", target_stage_def_id: toDef },
      },
    };
  }

  function screeningForm(candidateId: number, data: Json): Json {
    const saved = screenings.get(candidateId);
    if (!saved || !data || typeof data !== "object") return data;
    const form = data as Record<string, Json> & { card?: Record<string, Json> };
    const card = (form.card ?? {}) as Record<string, Json> & { fields?: Record<string, Json> };
    return {
      ...form,
      version: saved.version,
      versions_count: saved.version,
      sheet: saved.sheet,
      card: { ...card, fields: { ...(card.fields ?? {}), ...saved.fields } },
    };
  }

  function saveScreening(body: Record<string, Json>): PoligonResponse {
    const candidateId = Number(body.candidate_id);
    if (!people.has(candidateId)) return { status: 404, data: { detail: MISSING_MESSAGE } };
    const prev = screenings.get(candidateId) ?? { sheet: null, fields: {}, version: 0 };
    const sheetIn = body.sheet as { answers?: Array<Record<string, Json>>; overall_fit?: Json; experience_checks?: Json } | null;
    const cardIn = (body.card as { fields?: Record<string, Json> } | null)?.fields ?? {};
    const fields = { ...prev.fields };
    for (const [k, v] of Object.entries(cardIn)) fields[k] = typeof v === "string" ? v : "";
    const sheet = sheetIn
      ? {
          answers: (sheetIn.answers ?? []).map((a) => ({ ...a, answer: a.response ?? "" })),
          experience_checks: sheetIn.experience_checks ?? [],
          overall_fit: sheetIn.overall_fit ?? "uncertain",
          notes: "",
          answered_at: new Date().toISOString(),
          answered_by: null,
        }
      : prev.sheet;
    const next = { sheet, fields, version: prev.version + 1 };
    screenings.set(candidateId, next);
    const changed = [...(sheetIn ? ["sheet"] : []), ...Object.keys(cardIn)];
    emit({ type: "screening", candidateId, sheetSaved: Boolean(sheet), fields });
    const recorded = read("GET", "/api/screening-form", [["candidate_id", String(candidateId)], ["job_id", String(meta.job_id)]], { quiet: true });
    return {
      status: 200,
      data: { ...(recorded.data as Record<string, Json>), saved_version: next.version, undo_to_version: null, changed, note_id: null, cache_invalidated: false },
    };
  }

  /** Osoba ćwiczebna ląduje w „Nowych” (przypisanie z bazy, osoba z pliku CV). */
  function addToNew(candidateId: number): boolean {
    const person = people.get(candidateId);
    const first = kanban?.columns.find((c) => c.stage === "new" && c.stage_def_id !== undefined);
    if (!person || !first) return false;
    if (!findItem(candidateId)) {
      const template = first.items[0] ?? kanban?.columns.flatMap((c) => c.items)[0];
      const item: KanbanItem = {
        ...clone(template),
        id: person.entry_id,
        candidate_id: candidateId,
        name: person.name,
        lastname: person.lastname,
        stage: first.stage,
        stage_def_id: first.stage_def_id,
        moved_at: new Date(now).toISOString(),
        days_in_stage: 0,
        taken_by_name: null,
        can_take: true,
      };
      first.items = [item, ...first.items];
      first.count = first.items.length;
    }
    return true;
  }

  /** Karta w kolumnie etapu `stage`, bez zdarzenia `move` (ruch serwera po zapisie, np. terminy od klienta). */
  function relocate(candidateId: number, stage: string): KanbanItem | null {
    const found = findItem(candidateId);
    const target = kanban?.columns.find((c) => c.stage === stage);
    if (!found || !target) return null;
    if (found.column === target) return found.item;
    found.column.items = found.column.items.filter((i) => i !== found.item);
    found.column.count = found.column.items.length;
    const moved: KanbanItem = {
      ...found.item,
      stage: target.stage,
      stage_def_id: target.stage_def_id,
      moved_at: new Date(now).toISOString(),
      days_in_stage: 0,
      process_state_version: Number(found.item.process_state_version ?? 0) + 1,
    };
    target.items = [moved, ...target.items];
    target.count = target.items.length;
    return moved;
  }

  function assign(candidateId: number, jobId: number): PoligonResponse {
    if (!kanban || jobId !== meta.job_id || !addToNew(candidateId)) return { status: 404, data: { detail: MISSING_MESSAGE } };
    emit({ type: "assign", candidateId, jobId });
    return { status: 200, data: { ok: true, candidate_id: candidateId, job_id: jobId, stage: "new" } };
  }

  function move(body: Record<string, Json>): PoligonResponse {
    const candidateId = Number(body.candidate_id);
    const found = findItem(candidateId);
    if (!kanban || !found) return { status: 404, data: { detail: MISSING_MESSAGE } };
    const target = kanban.columns.find(
      (c) =>
        (body.stage_def_id !== undefined && c.stage_def_id === Number(body.stage_def_id)) ||
        (body.stage !== undefined && c.stage === body.stage),
    );
    if (!target) return { status: 422, data: { detail: "Nie ma takiego etapu w tej rekrutacji." } };
    const stop = preContractStop(candidateId, target);
    if (stop) {
      return { status: 409, data: { detail: { code: "PRE_CONTRACT_NOT_SIGNED", message: stop.message, origin: "job", needed_before: "cv_sent" } } };
    }
    if (target.stage === "verified" && GATED_FROM.has(String(found.column.stage ?? ""))) {
      const missing = verifiedMissing(candidateId);
      if (missing.length) {
        const labels = missing.map((m) => m.label);
        emit({ type: "gate", candidateId, missing: labels });
        return {
          status: 409,
          data: {
            detail: {
              code: "VERIFIED_REQUIREMENTS_MISSING",
              missing: missing.filter((m) => m.key === "screening_sheet").map((m) => m.key),
              card_fields: missing.filter((m) => m.key !== "screening_sheet").map((m) => m.key),
              client_required: [],
              screening_stage_id: entryOf(candidateId),
              message: `Przed „Przygotowaniem CV” uzupełnij: ${labels.join(", ")}.`,
            },
          },
        };
      }
    }
    const reasonId = body.rejection_reason_id === undefined || body.rejection_reason_id === "" ? null : Number(body.rejection_reason_id);
    const reasonName = reasonId === null ? null : (rejectionReasons().find((r) => r.id === reasonId)?.name ?? null);
    const fromStage = found.column.stage ?? null;
    found.column.items = found.column.items.filter((i) => i !== found.item);
    found.column.count = found.column.items.length;
    const moved: KanbanItem = {
      ...found.item,
      stage: target.stage,
      stage_def_id: target.stage_def_id,
      moved_at: new Date(now).toISOString(),
      days_in_stage: 0,
      rejection_reason_id: reasonId,
      rejection_reason_name: reasonName,
      rejection_note: typeof body.rejection_reason === "string" ? body.rejection_reason : null,
      process_state_version: Number(found.item.process_state_version ?? 0) + 1,
    };
    target.items = [moved, ...target.items];
    target.count = target.items.length;
    const rateValue = body.client_rate_value === undefined || body.client_rate_value === null ? NaN : Number(body.client_rate_value);
    emit({
      type: "move",
      candidateId,
      fromStage,
      toStage: target.stage ?? null,
      rejectionReasonId: reasonId,
      rejectionReasonName: reasonName,
      rejectionNote: typeof body.rejection_reason === "string" ? body.rejection_reason.trim() : "",
      fixFields: Array.isArray(body.fix_fields) ? body.fix_fields.filter((f): f is string => typeof f === "string") : [],
      clientRate: Number.isFinite(rateValue)
        ? { value: rateValue, unit: String(body.client_rate_unit ?? "hourly"), currency: String(body.client_rate_currency ?? "PLN") }
        : null,
    });
    return { status: 200, data: { id: moved.id, verification_status: "active", process_state_version: moved.process_state_version } };
  }

  function claim(body: Record<string, Json>): PoligonResponse {
    const candidateId = Number(body.candidate_id);
    const found = findItem(candidateId);
    if (!found) return { status: 404, data: { detail: MISSING_MESSAGE } };
    found.item.taken_by_name = "Ty";
    found.item.can_take = false;
    emit({ type: "claim", candidateId });
    return { status: 200, data: { ok: true } };
  }

  /** Pierwsza nagrana notatka — wzór kształtu, żeby ekran dostał wszystkie pola. */
  function noteTemplate(): Record<string, Json> {
    const list = responses[`GET /api/notes?candidate_id=${meta.template_candidate_id}`];
    const items = Array.isArray(list) ? list : (list as { items?: unknown[] } | undefined)?.items;
    return clone((items?.[0] as Record<string, Json> | undefined) ?? {});
  }

  function addNote(body: Record<string, Json>): PoligonResponse {
    const candidateId = body.candidate_id === undefined ? null : Number(body.candidate_id);
    const content = String(body.content ?? "").trim();
    const note = {
      ...noteTemplate(),
      id: nextNoteId++,
      candidate_id: candidateId,
      job_id: body.job_id ?? null,
      content,
      content_rendered: content,
      author_name: "Ty",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      pinned: false,
      note_type: body.note_type ?? "general",
    };
    if (candidateId !== null) addedNotes.set(candidateId, [note, ...(addedNotes.get(candidateId) ?? [])]);
    emit({ type: "note", candidateId, content });
    return { status: 201, data: note };
  }

  function read(
    method: string,
    path: string,
    query: Array<[string, string]>,
    opts: { quiet?: boolean; viewer?: PoligonViewer; canSetPreContractStop?: boolean } = {},
  ): PoligonResponse {
    if (!opts.quiet && method === "GET") emit({ type: "view", path, query: Object.fromEntries(query) });
    if (path === kanbanKey.slice(4)) return { status: 200, data: clone(kanban) };
    if (path === "/api/pipeline/move-requirements") return moveRequirements(query);
    // „Odrzuć:” w panelu osoby (23.11.2026): na Poligonie stałe trzy powody,
    // bo ćwiczący nie ma tu własnej historii odrzuceń.
    if (path === "/api/pipeline/my-quick-reject-reasons") {
      return {
        status: 200,
        data: {
          since: new Date(now - 29 * 86_400_000).toISOString().slice(0, 10),
          reasons: [
            { key: "missing_skill", count: 12, source: "mine" },
            { key: "too_junior", count: 9, source: "mine" },
            { key: "too_expensive", count: 7, source: "mine" },
          ],
        },
      };
    }
    // Trenerzy poligonu nie mają urlopów.
    if (path === "/api/hr/leave/absence") return { status: 200, data: { on: new Date(now).toISOString().slice(0, 10), items: [] } };

    const raw = `${path}?${new URLSearchParams(query).toString()}`;
    // Odpowiedź zapisana dla tej osoby (np. etap bez CV do klienta,
    // `poligon_cv_practice.py`) wygrywa z osobą-szablonem.
    const own = datasetKey(method, path, query);
    const { text, person } = own in responses ? { text: raw, person: null } : toTemplate(raw);
    const [tPath, tQuery = ""] = text.split("?");
    const tParams = [...new URLSearchParams(tQuery).entries()];
    const key = datasetKey(method, tPath, tParams);

    let data: Json | undefined = responses[key];
    let matched = key;
    if (data === undefined) {
      // Ten sam adres z innymi parametrami (np. sortowanie listy) — bierzemy pierwszy nagrany.
      const prefix = `${method.toUpperCase()} ${tPath}`;
      const near = Object.keys(responses).find((k) => k === prefix || k.startsWith(`${prefix}?`));
      data = near ? responses[near] : undefined;
      matched = near ?? key;
    }
    if (data === undefined) {
      emit({ type: "missing", key });
      return { status: 404, data: { detail: MISSING_MESSAGE } };
    }
    // Nagrana odmowa serwera (np. 404 „rekrutacja nie ma jeszcze migawki”) —
    // to odpowiedź, nie brak w zestawie.
    if (isRecordedStatus(data)) return { status: data["@status"], data: { detail: "Brak danych." } };
    data = asPerson(clone(data), person);
    // Klient ćwiczebny: kwoty tylko dla osoby, która widzi je na prawdziwym kliencie.
    if (fiction.has(matched)) data = forViewer(path, data, opts.viewer ?? NO_AMOUNTS);
    // Stop do podpisu przedwstępnej: „Wyjątek dla tej osoby” widzi tylko DL, HoR i admin.
    if (path === "/api/pre-contracts/pair" && data && typeof data === "object") {
      data = { ...(data as Record<string, Json>), can_set_stop: opts.canSetPreContractStop === true };
    }

    if (path === "/api/screening-form") {
      data = screeningForm(Number(query.find(([k]) => k === "candidate_id")?.[1]), data);
    }
    if (path === "/api/candidates" && data && typeof data === "object") {
      // Szukanie w bazie poligonu: słowo z pól tekstowych zapytania pasuje
      // do imienia, nazwiska, stanowiska albo umiejętności osoby („Scrum”).
      const words = query
        .filter(([k]) => /^(q|q_.*|search|name|keywords?)$/.test(k))
        .flatMap(([, v]) => v.toLowerCase().split(/[\s,]+/))
        .filter((w) => w.length >= 2);
      const list = data as { items?: Array<Record<string, Json>>; total?: number };
      if (words.length && Array.isArray(list.items)) {
        list.items = list.items.filter((c) => {
          const skills = (Array.isArray(c.skills) ? c.skills : []).map((x) => (x && typeof x === "object" ? (x as { name?: unknown }).name : x));
          const text = [c.name, c.lastname, c.current_position, c.role, c.ai_summary, ...skills].map((x) => String(x ?? "").toLowerCase()).join(" ");
          return words.some((w) => text.includes(w));
        });
        list.total = list.items.length;
      }
    }

    if (path === "/api/notes") {
      const cid = Number(query.find(([k]) => k === "candidate_id")?.[1]);
      const pinnedOnly = query.some(([k, v]) => k === "pinned_only" && v === "true");
      const added = pinnedOnly ? [] : (addedNotes.get(cid) ?? []);
      if (Array.isArray(data)) data = [...added, ...data];
      else if (data && typeof data === "object" && Array.isArray((data as { items?: unknown[] }).items)) {
        const page = data as { items: unknown[]; total?: number };
        data = { ...page, items: [...added, ...page.items], ...(typeof page.total === "number" ? { total: page.total + added.length } : {}) };
      }
    }
    if (path === "/api/jobs" && data && typeof data === "object") {
      const q = query.find(([k]) => k === "q")?.[1]?.toLowerCase().trim();
      const list = data as { items?: Array<{ title?: string; client_name?: string; reference_number?: string }>; total?: number };
      if (q && Array.isArray(list.items)) {
        list.items = list.items.filter((j) =>
          [j.title, j.client_name, j.reference_number].some((f) => (f ?? "").toLowerCase().includes(q)),
        );
        list.total = list.items.length;
      }
    }
    return { status: 200, data };
  }

  /** Paths odczytywane z zestawu, choć nie mają identyfikatora poligonu. */
  const OWNED_PATHS = new Set([
    "/api/jobs",
    "/api/jobs/quick-counts",
    "/api/candidates",
    "/api/saved-searches",
    // „Moi ludzie” poligonu to osoby ćwiczebne, nie ludzie z konta osoby.
    "/api/my-people",
    "/api/my-people/summary",
    "/api/talent-pools",
    "/api/me/career-link/people",
    // „@” w notatce podpowiada trenerów poligonu, nie prawdziwy zespół.
    "/api/users/mentionable",
    // „Czeka na Ciebie” na pulpicie: osoby ćwiczebne, bo lekcja „Pracuj po
    // kolei” potrzebuje kolejki także u osoby bez własnych kart (25.11.2026).
    "/api/board-tasks",
    // Klient ćwiczebny (22.11.2026): listy klientów, kontraktów, zamówień
    // z maila i widoki Finansów pokazują tylko „Bank Północny”, nie
    // prawdziwych klientów osoby, która ćwiczy.
    "/api/clients/directory/clients",
    "/api/client-reports/calendar",
    "/api/my-relationships",
    "/api/clients-lookup",
    "/api/reports/clients",
    "/api/contracts",
    "/api/contractors/stats",
    "/api/order-mail/queue",
    "/api/order-mail/recheck-runs",
    "/api/order-mail/sync/status",
    "/api/finance/rate-divergences",
    "/api/finance/order-cost-corrections",
    "/api/finance/order-changes/summary",
    // Zadania asystenta prawnego (lekcja z 26.11.2026): zadanie kontraktu
    // ćwiczebnego, nie prawdziwe wypowiedzenia u klientów osoby.
    "/api/legal/tasks",
    // Porcja dnia (lekcje „Porcja…”, 26.11.2026): karty z osobami ćwiczebnymi,
    // profil „Kogo szukamy” i rekrutacja spoza P0 do „Oddaj do Nowych”, nie
    // prawdziwa porcja osoby — pusta albo bez profilu nie miała elementów
    // z zadań (`backend/scripts/poligon_review_batch_practice.py`).
    "/api/review-batch/me",
    "/api/review-batch/me/queue",
    "/api/review-batch/me/focus",
  ]);
  /** Zapisy, które w rzeczywistości są odczytami (wyniki dopasowania, podpowiedzi). */
  const READ_POSTS = new Set([
    "/api/search/candidates/scores",
    "/api/my-people/matches/seen",
    // Podgląd maila odrzucenia w przeglądzie Delivery Leada — nic nie wysyła.
    "/api/rejection-emails/preview",
    // Plan przelewów (Finanse → Przelewy): POST, bo serwer sprawdza wykaz VAT.
    // Na Poligonie faktura kontraktora ćwiczebnego, nie prawdziwe faktury
    // (lekcja „Zajęcia i spory”, 25.11.2026: ekran pokazywał błąd pobrania).
    "/api/finance/payments/plan",
  ]);

  const tools = createTools({
    meta,
    now,
    emit,
    findItem,
    addToNew,
    relocate,
    // `unredacted` tylko do obliczeń narzędzia (np. cytat z uwagi QC), nigdy do odpowiedzi ekranu.
    recorded: (method, path, query = [], unredacted = false) =>
      read(method, path, query, { quiet: true, viewer: unredacted ? ALL_AMOUNTS : undefined }),
    people,
    template,
  });

  // Rekrutacja „Wstrzymana” (lekcje z 26.11.2026). Odczyt bez stanu — zawsze
  // „Szukamy”, bo etap „sam” po pokazie znowu potrzebuje „Wstrzymaj rekrutację…”
  // i „Zgłoś DL-owi”. Zapisy odpowiadają jak serwer, ale niczego nie zostawiają.
  function holdView(canManage: boolean, over: Record<string, Json> = {}): Json {
    const rec = meta.trainers?.rec;
    return {
      job_id: meta.job_id,
      state: "searching",
      reason: null,
      review_on: null,
      since: null,
      by_id: null,
      by_name: null,
      can_manage: canManage,
      recipients: canManage && rec ? [{ user_id: rec.id, name: rec.name, people: 2 }] : [],
      my_open_report: null,
      ...over,
    };
  }

  function hold(method: string, report: boolean, body: Record<string, Json>, canManage: boolean): PoligonResponse {
    if (report) return method === "POST" ? { status: 201, data: { ok: true } } : { status: 405, data: null };
    if (method === "GET") return { status: 200, data: holdView(canManage) };
    if (!canManage) return { status: 403, data: { detail: "Stan rekrutacji zmienia Delivery Lead." } };
    if (method === "PUT") {
      return {
        status: 200,
        data: holdView(true, {
          state: "on_hold",
          reason: typeof body.reason === "string" ? body.reason : "",
          review_on: typeof body.review_on === "string" ? body.review_on : null,
          since: new Date(now).toISOString(),
          by_name: "Ty",
        }),
      };
    }
    if (method === "DELETE") return { status: 200, data: holdView(true) };
    return { status: 405, data: null };
  }

  function handle(req: PoligonRequest): PoligonResponse | "network" {
    const method = (req.method || "get").toUpperCase();
    const { path, query } = splitUrl(req);
    const body = (req.body && typeof req.body === "object" ? req.body : {}) as Record<string, Json>;
    const holdMatch = path.match(/^\/api\/jobs\/(\d+)\/hold(\/report)?$/);
    if (holdMatch && Number(holdMatch[1]) === meta.job_id) {
      return hold(method, Boolean(holdMatch[2]), body, req.canManageHold === true);
    }
    // Narzędzia z ćwiczeń z 16.11.2026: stan w pamięci karty, odczyty i zapisy.
    const tool = tools.handle(method, path, body, req.viewerId ?? null);
    if (tool) {
      if (method === "GET") emit({ type: "view", path, query: Object.fromEntries(query) });
      // Kopia, jak przy odczytach z zestawu: ekran nie może trzymać referencji
      // do stanu poligonu (react-query uznałby zmienioną listę za tę samą).
      return { status: tool.status, data: clone(tool.data) };
    }
    const owned =
      OWNED_PATHS.has(path) || mentionsPoligon(`${path}?${new URLSearchParams(query).toString()}`) || mentionsPoligon(JSON.stringify(req.body ?? ""));

    if (method === "GET" || method === "HEAD") {
      return owned
        ? read("GET", path, query, { viewer: req.viewer, canSetPreContractStop: req.canSetPreContractStop })
        : "network";
    }
    // Od tego miejsca tylko zapisy. Jedyny, który wychodzi z przeglądarki, to
    // postęp osoby na poligonie (zaliczone ćwiczenie) — dane rekrutacji nie.
    if (POLIGON_PROGRESS.test(path)) return "network";
    // Przeklikanie nowości z porannej porcji idzie na poligonie (18.11.2026):
    // zaliczenie ma dotrzeć na serwer. Reszta zdarzeń nowości zostaje tutaj.
    if (NOVELTY_EVENTS.test(path) && body.event === "toured") return "network";
    if (LESSON_EVENTS.test(path)) return "network";
    if (path.startsWith("/api/novelties/")) return { status: 204, data: null };
    if (path === "/api/pipeline/move") return move(body);
    if (path === "/api/pipeline/claim") return claim(body);
    if (path === "/api/notes") return addNote(body);
    if (path === "/api/screening-form" && method === "PUT") return saveScreening(body);
    const assignMatch = path.match(/^\/api\/candidates\/(\d+)\/assign-to-job\/(\d+)$/);
    if (assignMatch) return assign(Number(assignMatch[1]), Number(assignMatch[2]));
    if (READ_POSTS.has(path) || /\/screening\/reassign-suggestions$/.test(path)) return read("POST", path, query);
    emit({ type: "blocked", method, path });
    return { status: 409, data: { detail: BLOCKED_WRITE_MESSAGE } };
  }

  return {
    handle,
    subscribe(fn: (action: PoligonAction) => void): () => void {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    /** Do ćwiczeń: gdzie stoi osoba. */
    stageOf(candidateId: number): string | null {
      return (findItem(candidateId)?.item.stage as string | undefined) ?? null;
    },
    /** Jarvis na poligonie: stała odpowiedź o osobie z Tablicy, bez modelu (`lib/poligon/jarvis.ts`). */
    jarvisAnswer: tools.jarvisAnswer,
    /** Układ CV etapu osoby ćwiczebnej (`null` spoza poligonu) — podgląd PDF w `adapter.ts`. */
    cvLayoutOf: tools.layoutOf,
    meta,
  };
}

export type PoligonStore = ReturnType<typeof createPoligonStore>;
