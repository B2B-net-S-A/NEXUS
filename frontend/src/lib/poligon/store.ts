// Rekrutacja ćwiczebna Poligonu w pamięci karty przeglądarki.
//
// Odczyty o rekrutacji ćwiczebnej i jej osobach (identyfikatory 990000+)
// podaje zestaw z `dataset.json` (buduje go `backend/scripts/build_poligon_dataset.py`).
// Zapisy zmieniają tylko ten stan. Żaden zapis nie idzie do serwera: to, czego
// poligon nie umie, kończy się odmową z komunikatem, nie prawdziwym zapisem.
// Odczyty spoza rekrutacji ćwiczebnej (pasek górny, powiadomienia) idą do API
// jak zwykle — wtedy `handle` zwraca `"network"`.

export interface PoligonPerson {
  candidate_id: number;
  entry_id: number;
  name: string;
  lastname: string;
}

export interface PoligonDataset {
  meta: {
    job_id: number;
    client_id: number;
    template_candidate_id: number;
    template_entry_id: number;
    trainers: Record<string, { id: number; name: string }>;
    people: PoligonPerson[];
  };
  responses: Record<string, unknown>;
}

export interface PoligonRequest {
  method: string;
  /** Ścieżka z ewentualnym `?query` (bez hosta). */
  url: string;
  params?: Record<string, unknown> | null;
  body?: unknown;
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
    }
  | { type: "claim"; candidateId: number }
  | { type: "note"; candidateId: number | null; content: string }
  | { type: "blocked"; method: string; path: string }
  | { type: "missing"; key: string };

export const POLIGON_ID_MIN = 990_000;
export const POLIGON_ID_MAX = 999_999;
const DAY_MS = 86_400_000;

export const BLOCKED_WRITE_MESSAGE =
  "Na poligonie ta akcja się nie zapisuje. W prawdziwej rekrutacji zadziała normalnie.";
const MISSING_MESSAGE = "Tego ekranu nie ma jeszcze na poligonie.";

type Json = unknown;
type KanbanItem = Record<string, Json> & { candidate_id: number; stage?: string; stage_def_id?: number };
type KanbanColumn = Record<string, Json> & { stage?: string; stage_def_id?: number; items: KanbanItem[]; count?: number };

function clone<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);
}

/** `@rel:-3.2` → data sprzed 3,2 dnia, `@reld:-3` → sam dzień. */
export function resolveDates(value: Json, now: number): Json {
  if (typeof value === "string") {
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

  const kanbanKey = `GET /api/pipeline/kanban/${meta.job_id}`;
  const kanban = clone(responses[kanbanKey]) as { columns: KanbanColumn[] } | undefined;
  const addedNotes = new Map<number, Array<Record<string, Json>>>();
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
    emit({
      type: "move",
      candidateId,
      fromStage,
      toStage: target.stage ?? null,
      rejectionReasonId: reasonId,
      rejectionReasonName: reasonName,
      rejectionNote: typeof body.rejection_reason === "string" ? body.rejection_reason.trim() : "",
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

  function read(method: string, path: string, query: Array<[string, string]>): PoligonResponse {
    if (path === kanbanKey.slice(4)) return { status: 200, data: clone(kanban) };

    const raw = `${path}?${new URLSearchParams(query).toString()}`;
    const { text, person } = toTemplate(raw);
    const [tPath, tQuery = ""] = text.split("?");
    const tParams = [...new URLSearchParams(tQuery).entries()];
    const key = datasetKey(method, tPath, tParams);

    let data: Json | undefined = responses[key];
    if (data === undefined) {
      // Ten sam adres z innymi parametrami (np. sortowanie listy) — bierzemy pierwszy nagrany.
      const prefix = `${method.toUpperCase()} ${tPath}`;
      const near = Object.keys(responses).find((k) => k === prefix || k.startsWith(`${prefix}?`));
      data = near ? responses[near] : undefined;
    }
    if (data === undefined) {
      emit({ type: "missing", key });
      return { status: 404, data: { detail: MISSING_MESSAGE } };
    }
    data = asPerson(clone(data), person);

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
  const OWNED_PATHS = new Set(["/api/jobs", "/api/jobs/quick-counts"]);
  /** Zapisy, które w rzeczywistości są odczytami (wyniki dopasowania, podpowiedzi). */
  const READ_POSTS = new Set(["/api/search/candidates/scores"]);

  function handle(req: PoligonRequest): PoligonResponse | "network" {
    const method = (req.method || "get").toUpperCase();
    const { path, query } = splitUrl(req);
    const body = (req.body && typeof req.body === "object" ? req.body : {}) as Record<string, Json>;
    const owned =
      OWNED_PATHS.has(path) || mentionsPoligon(`${path}?${new URLSearchParams(query).toString()}`) || mentionsPoligon(JSON.stringify(req.body ?? ""));

    if (method === "GET" || method === "HEAD") {
      return owned ? read("GET", path, query) : "network";
    }
    // Od tego miejsca tylko zapisy — żaden nie wychodzi z przeglądarki.
    if (path.startsWith("/api/novelties/")) return { status: 204, data: null };
    if (path === "/api/pipeline/move") return move(body);
    if (path === "/api/pipeline/claim") return claim(body);
    if (path === "/api/notes") return addNote(body);
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
    meta,
  };
}

export type PoligonStore = ReturnType<typeof createPoligonStore>;
