// Narzędzia rekrutera na poligonie (ćwiczenia z 16.11.2026): telefon
// screeningowy, wybór terminu u klienta, osoba z pliku CV, zapisane
// wyszukiwanie, lista (pula), czat rekrutacji, asystent CV i Jarvis.
// Delivery Lead: terminy od klienta (wpisane ręcznie albo z wklejonego maila).
//
// Tak jak reszta `store.ts`: zapisy zmieniają tylko stan w pamięci karty
// i zgłaszają zdarzenie dla ćwiczeń. Nic nie idzie do serwera, a „odpowiedź
// AI” (plan asystenta CV, Jarvis) to stałe reguły — bez wywołania modelu.

import { autoTexts, whySlots } from "@/lib/cv-page1-why";

import { CV_FICTION_HIGHLIGHT, CV_FICTION_TERMS, CV_FICTION_WHY, cvFictionHtml } from "./cv-fiction";
import { POLIGON_CLIENT_MAIL_SLOTS } from "./exercises";
import { practiceLetterApprove, practiceLetterDraft } from "./legal-letter";
import type { PoligonAction, PoligonDataset, PoligonPerson, PoligonResponse } from "./store";

type Json = unknown;
type Row = Record<string, Json>;
type KanbanItem = Row & { candidate_id: number; stage?: string };

/** Etapy, z których umawia się telefon screeningowy (`ENTRY_STAGES` frontu, serwer: 409 poza nimi). */
const CALL_STAGES = new Set(["posting", "new", "screening", "prep_call"]);
/** Parametry listy kandydatów, które nie są kryterium (strona, sortowanie, widok). */
const LIST_PARAM = /^(page|page_size|limit|offset|sort|order|semantics_version|view|include_.*)$/;

export const SAVED_SEARCH_NO_ALERT_PARAMS =
  "Alert wymaga parametrów API w filters.api — zapisz wyszukiwanie ponownie z aktualnej wersji aplikacji.";
/** Etapy, w których DL wpisuje terminy od klienta (przycisk w panelu osoby: „CV wysłane” i „Rozmowa u klienta”). */
const SLOT_STAGES = new Set(["cv_sent", "client_interview"]);
const OPEN_SLOT_STATUSES = new Set(["awaiting_recruiter", "awaiting_dl"]);
export const SLOTS_MAIL_OTHER =
  "Na poligonie NEXUS odczytuje tylko maila klienta z ćwiczenia (terminy o 10:00 i 13:00). Wklej go z okna ćwiczenia albo wpisz terminy ręcznie.";
/**
 * Osoby, których CV do klienta jest od startu w układzie „Nowe CV” — edytor
 * otwiera się na zakładce „Strona 1” (lekcja „Nowe CV: strona 1”, 25.11.2026).
 * Pokaz idzie na pierwszej, „sam” na drugiej.
 */
export const POLIGON_NEW_CV_CANDIDATES = [990108, 990109] as const;
const PAGE1_TEXT_MAX = 400;
const MSG_PAGE1_EMPTY = "Podaj wynik do strony 1.";
const MSG_PAGE1_TOO_LONG = `Zdanie na stronie 1 może mieć najwyżej ${PAGE1_TEXT_MAX} znaków.`;
const CV_COMMAND_EMPTY =
  "Nic nie zmieniłem — na poligonie asystent zna kilka poleceń. Wpisz na przykład „pogrub Scrum i Jira”.";

export interface ToolsContext {
  meta: PoligonDataset["meta"];
  now: number;
  emit: (action: PoligonAction) => void;
  findItem: (candidateId: number) => { column: { stage?: string; label?: Json; name?: Json }; item: KanbanItem } | null;
  /** Osoba ląduje w „Nowych” rekrutacji ćwiczebnej (jak przypisanie z bazy). */
  addToNew: (candidateId: number) => boolean;
  /** Karta przechodzi do kolumny etapu bez zdarzenia `move` (jak ruch serwera po terminach od klienta). */
  relocate: (candidateId: number, stage: string) => KanbanItem | null;
  /** Odczyt z zestawu bez zdarzenia `view` (np. profil osoby-szablonu). */
  recorded: (method: string, path: string, query?: Array<[string, string]>, unredacted?: boolean) => PoligonResponse;
  people: Map<number, PoligonPerson>;
  template: PoligonPerson | undefined;
}

function isoNow(now: number): string {
  return new Date(now).toISOString();
}

function textOf(value: Json): string {
  return typeof value === "string" ? value : "";
}

/** Dzień za `workdays` dni robocze od `now`, o godzinie `hour` czasu przeglądarki (jak okno terminów). */
function workdayLocal(now: number, workdays: number, hour: number): Date {
  const day = new Date(now);
  for (let left = workdays; left > 0; ) {
    day.setDate(day.getDate() + 1);
    if (day.getDay() !== 0 && day.getDay() !== 6) left -= 1;
  }
  day.setHours(hour, 0, 0, 0);
  return day;
}

function proposals(n: number): string {
  if (n === 1) return "1 propozycja";
  const rest = n % 10;
  return rest >= 2 && rest <= 4 && (n % 100 < 12 || n % 100 > 14) ? `${n} propozycje` : `${n} propozycji`;
}

/** Czy zapis wyszukiwania ma jakiekolwiek kryterium (słowo, filtr) — inaczej alert łapałby całą bazę. */
export function savedSearchHasCriteria(filters: Json): boolean {
  const api = (filters as { api?: Json } | null)?.api;
  if (!api || typeof api !== "object") return false;
  return Object.entries(api as Row).some(([k, v]) => {
    if (LIST_PARAM.test(k)) return false;
    if (Array.isArray(v)) return v.length > 0;
    return v !== null && v !== undefined && String(v).trim() !== "" && v !== false;
  });
}

export function createTools(ctx: ToolsContext) {
  const { meta, emit } = ctx;
  let nextId = 999_101;
  const savedSearches: Row[] = [];
  const pools: Row[] = [];
  const poolMembers = new Map<number, Set<number>>();
  const chat: Row[] = [];
  /** Treść CV firmowego per etap (wpis osoby) po autozapisie edytora. */
  const branded = new Map<number, { html: string; revision: number; status: string }>();
  /** Układ CV per etap (Nowe CV / Klasyczne, 23.11.2026); brak wpisu = klasyczny jak u klienta bez reguły. */
  const layouts = new Map<number, "classic" | "new">();
  /** Dodatki strony 1 nowego CV per etap po zmianach w edytorze (wyróżnik, zdania). */
  const page1 = new Map<number, Row>();
  const newByDefault = new Set(
    meta.people.filter((p) => (POLIGON_NEW_CV_CANDIDATES as readonly number[]).includes(p.candidate_id)).map((p) => p.entry_id),
  );
  const layoutFor = (entryId: number): "classic" | "new" =>
    layouts.get(entryId) ?? (newByDefault.has(entryId) ? "new" : "classic");

  /** Odznaka „Wybierz termin” z zestawu (osoba na „Rozmowie u klienta”) — wzór dla nowych wniosków DL-a. */
  const badgeTemplate = JSON.parse(JSON.stringify(ctx.findItem(meta.slot_candidate_id)?.item.interview_badge ?? null)) as
    | (Row & { steps?: Row[] })
    | null;

  const personByEntry = (entryId: number): PoligonPerson | undefined =>
    meta.people.find((p) => p.entry_id === entryId);

  // ── Telefon screeningowy ─────────────────────────────────────────────
  function bookCall(body: Row, viewerId: number | null): PoligonResponse {
    const candidateId = Number(body.candidate_id);
    const found = ctx.findItem(candidateId);
    if (!found) return { status: 404, data: { detail: "Tej osoby nie ma na rekrutacji ćwiczebnej." } };
    if (!CALL_STAGES.has(String(found.item.stage ?? ""))) {
      return { status: 409, data: { detail: "Telefon screeningowy umawiasz osobie z „Nowych” albo „Screeningu”." } };
    }
    const start = textOf(body.start);
    const note = textOf(body.note) || null;
    const eventId = nextId++;
    found.item.booked_call = { event_id: eventId, start_time: start, note, owner_id: viewerId, owner_name: "Ty", in_outlook: false };
    found.item.taken_by_name = "Ty";
    found.item.can_take = false;
    emit({ type: "screening_call", candidateId, start });
    return {
      status: 201,
      data: { event_id: eventId, candidate_id: candidateId, job_id: meta.job_id, start_time: start, note, status: "scheduled", outlook: "not_connected" },
    };
  }

  function changeCall(eventId: number, body: Row | null): PoligonResponse {
    for (const p of meta.people) {
      const item = ctx.findItem(p.candidate_id)?.item;
      const call = item?.booked_call as Row | null | undefined;
      if (!item || !call || call.event_id !== eventId) continue;
      if (body === null) {
        item.booked_call = null;
        return { status: 200, data: { ...call, candidate_id: p.candidate_id, job_id: meta.job_id, status: "cancelled", outlook: "not_connected" } };
      }
      const next = { ...call, start_time: textOf(body.start) || call.start_time, note: textOf(body.note) || null };
      item.booked_call = next;
      emit({ type: "screening_call", candidateId: p.candidate_id, start: String(next.start_time) });
      return { status: 200, data: { ...next, candidate_id: p.candidate_id, job_id: meta.job_id, status: "scheduled", outlook: "not_connected" } };
    }
    return { status: 404, data: { detail: "Nie ma takiego telefonu." } };
  }

  // ── Wybór terminu u klienta ──────────────────────────────────────────
  function chooseSlot(requestId: number, body: Row): PoligonResponse {
    for (const p of meta.people) {
      const item = ctx.findItem(p.candidate_id)?.item;
      const badge = item?.interview_badge as (Row & { slot_request?: Row & { slots?: Row[] }; steps?: Row[] }) | undefined;
      const request = badge?.slot_request;
      if (!item || !badge || !request || request.id !== requestId) continue;
      if (request.status !== "awaiting_recruiter") {
        return { status: 409, data: { detail: "Termin z tej propozycji jest już wybrany." } };
      }
      const index = Number(body.index);
      const slot = request.slots?.[index];
      if (!slot) return { status: 422, data: { detail: "Nie ma takiego terminu." } };
      const chosen = { ...request, status: "awaiting_dl", chosen_index: index };
      item.interview_badge = {
        ...badge,
        kind: "confirm_slot",
        label: "Termin wybrany · czeka na DL",
        tentative_interview_at: textOf(body.start) || slot.start,
        phase: "awaiting_dl_confirm",
        steps: (badge.steps ?? []).map((s) => (s.key === "choice" ? { ...s, state: "done" } : s)),
        slot_request: chosen,
      };
      emit({ type: "slot_choose", candidateId: p.candidate_id, index });
      return { status: 200, data: { ...chosen, outlook: null } };
    }
    return { status: 404, data: { detail: "Nie ma takiej propozycji terminów." } };
  }

  // ── Terminy od klienta (Delivery Lead) ───────────────────────────────
  function createSlots(body: Row, viewerId: number | null): PoligonResponse {
    const candidateId = Number(body.candidate_id);
    const found = ctx.findItem(candidateId);
    if (Number(body.job_id) !== meta.job_id || !found) {
      return { status: 422, data: { detail: "Kandydat nie jest w pipeline tej rekrutacji." } };
    }
    if (!SLOT_STAGES.has(String(found.item.stage ?? ""))) {
      return { status: 422, data: { detail: "Terminy od klienta wpisujesz osobie z „CV wysłane” albo „Rozmowy u klienta”." } };
    }
    const badge = found.item.interview_badge as (Row & { slot_request?: Row }) | null | undefined;
    const open = badge?.slot_request;
    const replaces = body.replaces_request_id === undefined ? null : Number(body.replaces_request_id);
    if (open && OPEN_SLOT_STATUSES.has(String(open.status)) && !open.expired && open.id !== replaces) {
      return {
        status: 409,
        data: {
          detail: {
            code: "SLOTS_ALREADY_OPEN",
            message: "Ten kandydat ma już otwarte terminy do wyboru w tej rekrutacji. Możesz je zastąpić tymi z formularza.",
            open_request_id: open.id,
          },
        },
      };
    }
    const duration = Number(body.duration_minutes) || 60;
    const starts = (Array.isArray(body.slots) ? body.slots : []).map((s) => textOf((s as Row).start)).filter(Boolean);
    if (!starts.length) return { status: 422, data: { detail: "Dodaj co najmniej jeden termin od klienta." } };
    if (starts.some((s) => new Date(s).getTime() < Date.now())) {
      return { status: 422, data: { detail: "Termin rozmowy nie może być w przeszłości." } };
    }
    const sorted = [...starts].sort();
    const slots = sorted.map((start) => ({ start, end: new Date(new Date(start).getTime() + duration * 60_000).toISOString() }));
    const request = {
      id: nextId++,
      status: "awaiting_recruiter",
      expired: false,
      slots,
      chosen_index: null,
      respond_by: textOf(body.respond_by) || null,
      recruiter_id: meta.trainers.rec?.id ?? null,
      created_by: viewerId,
      duration_minutes: duration,
      note: textOf(body.note) || null,
      event_id: null,
      client_reply_pending: false,
      client_replied_at: null,
    };
    // Serwer przesuwa kartę z „CV wysłane” na „Rozmowę u klienta” (`create_slot_request_for_pair`).
    const moved = found.item.stage === "cv_sent";
    const item = moved ? ctx.relocate(candidateId, "client_interview") : found.item;
    if (!item) return { status: 404, data: { detail: "Tego ekranu nie ma jeszcze na poligonie." } };
    const at = request.respond_by ?? slots[0].start;
    item.interview_badge = {
      ...(badgeTemplate ?? {}),
      kind: "choose_slot",
      label: `Wybierz termin · ${proposals(slots.length)}`,
      tone: "wait",
      at,
      steps: (badgeTemplate?.steps ?? []).map((s) =>
        s.key === "slots" ? { ...s, state: "done" } : s.key === "choice" ? { ...s, state: "current", at } : { ...s, state: "todo", at: null },
      ),
      interview_event_id: null,
      tentative_interview_at: slots[0].start,
      slot_request: request,
      preps: [],
      phase: "awaiting_recruiter_pick",
    };
    emit({ type: "slot_request", candidateId, starts: sorted, durationMinutes: duration, replaced: replaces !== null });
    return { status: 201, data: { ...request, moved_to_client_interview: moved, move_skipped_reason: null } };
  }

  /** „Wklej maila od klienta” bez modelu: stały odczyt maila z ćwiczenia, inny tekst — jasna odmowa. */
  function slotsFromMail(body: Row): PoligonResponse {
    const text = textOf(body.text);
    const empty = { slots: [], extra_slots: 0, dropped: 0, duration_minutes: null, respond_by: null, format: null, location_note: null, people: null, unclear: [] };
    if (!POLIGON_CLIENT_MAIL_SLOTS.every((s) => text.includes(s.quote))) {
      return { status: 200, data: { ...empty, status: "empty", message: SLOTS_MAIL_OTHER } };
    }
    const slots = POLIGON_CLIENT_MAIL_SLOTS.map((s) => {
      const start = workdayLocal(ctx.now, s.workdays, s.hour);
      return {
        start: start.toISOString(),
        end: new Date(start.getTime() + 45 * 60_000).toISOString(),
        window: false,
        quote: s.quote,
        warning: null,
      };
    });
    return { status: 200, data: { ...empty, status: "ok", message: null, slots, duration_minutes: 45, format: "online" } };
  }

  // ── Osoba z pliku CV ─────────────────────────────────────────────────
  function fromCv(): PoligonResponse {
    const person = ctx.people.get(meta.cv_candidate_id);
    const profile = ctx.recorded("GET", `/api/candidates/${meta.template_candidate_id}`);
    if (!person || profile.status !== 200) return { status: 404, data: { detail: "Tego ekranu nie ma jeszcze na poligonie." } };
    const base = profile.data as Row;
    const candidate = {
      ...base,
      id: person.candidate_id,
      name: person.name,
      lastname: person.lastname,
      email: null,
      phone: null,
      linkedin: null,
      created_at: isoNow(ctx.now),
    };
    emit({ type: "cv_upload", candidateId: person.candidate_id });
    return {
      status: 201,
      data: {
        candidate,
        // Pewność odczytu: e-mail i telefon CV ćwiczebne pomija — ekran pokaże je do sprawdzenia.
        confidence: { name: 0.98, lastname: 0.98, email: 0.2, phone: 0.2, location: 0.9, skills: 0.85, years_it_experience: 0.6 },
        duplicates: [],
        source: "ai",
      },
    };
  }

  function addProposals(jobId: number, body: Row): PoligonResponse {
    if (jobId !== meta.job_id) return { status: 404, data: { detail: "Tego ekranu nie ma jeszcze na poligonie." } };
    const ids = Array.isArray(body.candidate_ids) ? body.candidate_ids.map(Number) : [];
    const added: number[] = [];
    const skipped: Row[] = [];
    for (const id of ids) {
      if (ctx.findItem(id)) skipped.push({ candidate_id: id, reason: "already_in_job", reason_label: "już jest w tej rekrutacji" });
      else if (ctx.addToNew(id)) added.push(id);
    }
    for (const id of added) emit({ type: "assign", candidateId: id, jobId });
    return { status: 200, data: { added, skipped, warnings: [], total_added: added.length, total_skipped: skipped.length } };
  }

  // ── Zapisane wyszukiwania ─────────────────────────────────────────────
  function saveSearch(body: Row, viewerId: number | null): PoligonResponse {
    const notify = body.notify_new_matches === true;
    const criteria = savedSearchHasCriteria(body.filters);
    if (notify && !(body.filters as { api?: Json } | null)?.api) {
      return { status: 400, data: { detail: SAVED_SEARCH_NO_ALERT_PARAMS } };
    }
    const at = isoNow(ctx.now);
    const row = {
      id: nextId++,
      user_id: viewerId ?? 0,
      name: textOf(body.name),
      entity: textOf(body.entity) || "candidates",
      filters: body.filters ?? {},
      shared: false,
      description: null,
      pinned_to_job_id: null,
      notify_new_matches: notify,
      requires_reapproval: false,
      unseen_count: 0,
      last_viewed_at: at,
      created_at: at,
      updated_at: at,
    };
    savedSearches.unshift(row);
    emit({ type: "saved_search", notify, criteria, name: row.name });
    return { status: 201, data: row };
  }

  function patchSearch(id: number, body: Row): PoligonResponse {
    const row = savedSearches.find((r) => r.id === id);
    if (!row) return { status: 404, data: { detail: "Nie ma takiego zapisu." } };
    Object.assign(row, Object.fromEntries(Object.entries(body).filter(([k]) => k !== "confirm_reapproval")));
    if (body.notify_new_matches === true) {
      emit({ type: "saved_search", notify: true, criteria: savedSearchHasCriteria(row.filters), name: textOf(row.name) });
    }
    return { status: 200, data: row };
  }

  // ── Listy (pule) ─────────────────────────────────────────────────────
  function poolOut(row: Row): Row {
    return { ...row, candidate_count: poolMembers.get(Number(row.id))?.size ?? 0 };
  }

  function createPool(body: Row, viewerId: number | null): PoligonResponse {
    const row = {
      id: nextId++,
      name: textOf(body.name).trim() || "Moja lista",
      description: null,
      candidate_count: 0,
      created_at: isoNow(ctx.now),
      is_personal: body.is_personal !== false,
      owner_id: viewerId,
      owner_name: "Ty",
      is_marketplace: false,
      team_visible: body.team_visible === true,
    };
    pools.push(row);
    poolMembers.set(row.id, new Set());
    return { status: 201, data: row };
  }

  function addToPool(poolId: number, candidateIds: number[]): PoligonResponse {
    const members = poolMembers.get(poolId);
    if (!members) return { status: 404, data: { detail: "Nie ma takiej listy." } };
    const fresh = candidateIds.filter((id) => !members.has(id));
    if (!fresh.length) return { status: 409, data: { detail: "Ta osoba już jest na tej liście." } };
    for (const id of fresh) {
      members.add(id);
      emit({ type: "pool_add", candidateId: id, poolId });
    }
    return { status: 201, data: { message: "Dodano do listy.", pool_id: poolId, candidate_id: fresh[0], added: fresh.length, already_in_pool: 0, not_found: 0 } };
  }

  // ── Czat rekrutacji ──────────────────────────────────────────────────
  function postChat(jobId: number, body: Row, viewerId: number | null): PoligonResponse {
    const content = textOf(body.content).trim();
    if (!content) return { status: 422, data: { detail: "Napisz wiadomość." } };
    const at = isoNow(Date.now());
    const mentions = Object.values(meta.trainers)
      .filter((t) => content.includes(`@${t.name.toLowerCase().split(" ").join(".")}`) || content.includes(`@${t.name}`))
      .map((t) => t.id);
    const message = {
      id: nextId++,
      job_id: jobId,
      content,
      author: { id: viewerId ?? 0, name: "Ty", email: null, role: null },
      reply_to_message_id: body.reply_to_message_id ?? null,
      reply_to_preview: null,
      is_edited: false,
      edited_at: null,
      is_deleted: false,
      pinned: false,
      pinned_at: null,
      pinned_by: null,
      mentions,
      reactions: [],
      created_at: at,
      updated_at: at,
    };
    chat.unshift(message);
    emit({ type: "chat", content, mentions });
    return { status: 201, data: message };
  }

  // ── CV firmowe i asystent ─────────────────────────────────────────────
  /**
   * „Wpisz w punkcie 1” (nowość „Lata w punkcie 1”): podmiana frazy z liczbą
   * lat na propozycję z uwagi QC, jak `cv_qc.tenure_split_html` — bez zapisu,
   * edytor zapisuje treść sam. Inne poprawki QC na poligonie zostają wyłączone.
   */
  function qcTransform(entryId: number, body: Row): PoligonResponse | null {
    const actions = Array.isArray(body.actions) ? (body.actions as Row[]) : [];
    if (!personByEntry(entryId) || actions.length !== 1 || actions[0]?.action !== "tenure_split") return null;
    const qc = ctx.recorded("GET", `/api/pipeline/stages/${entryId}/qc`, [["transient", "true"]], true);
    const checks = (qc.data as { checks?: Array<{ key?: string; items?: Row[] }> } | null)?.checks ?? [];
    const tenure = checks.find((c) => c.key === "years_breakdown")?.items?.[0]?.tenure as Row | undefined;
    const html = typeof body.content_html === "string" ? body.content_html : "";
    const quote = typeof tenure?.quote === "string" ? tenure.quote : "";
    const proposal = typeof tenure?.proposal === "string" ? tenure.proposal : "";
    if (!quote || !proposal || !html.includes(quote)) {
      return {
        status: 200,
        data: {
          content_html: html,
          changed: false,
          applied: [],
          skipped: [{ action: "tenure_split", code: "nothing_to_do", message: "W punkcie 1 nie ma już liczby lat do podmiany." }],
        },
      };
    }
    return {
      status: 200,
      data: { content_html: html.replace(quote, proposal), changed: true, applied: [{ action: "tenure_split", count: 1 }], skipped: [] },
    };
  }


  function brandedOf(entryId: number, recorded: Row): Row {
    const saved = branded.get(entryId);
    const person = personByEntry(entryId) ?? ctx.template;
    // Etap bez CV do klienta (osoba z gotowym CV z innej rekrutacji) zostaje bez treści.
    const html = saved?.html ?? (recorded.status === "none" ? null : cvFictionHtml(person ? `${person.name} ${person.lastname}` : ""));
    const extras = (recorded.page1_extras && typeof recorded.page1_extras === "object" ? recorded.page1_extras : {}) as Row;
    return {
      ...recorded,
      candidate_stage_id: entryId,
      content_html: html,
      status: saved?.status ?? recorded.status,
      edit_revision: saved?.revision ?? recorded.edit_revision,
      // Przełącznik „Układ CV” w karcie „CV do klienta” i w edytorze (lekcja „Nowe CV”).
      new_layout_enabled: true,
      cv_layout: layoutFor(entryId),
      default_layout: "classic",
      page1_extras: page1Of(entryId, extras),
    };
  }

  /** Zdania z generatora jak po biegu w tle przy „Nowym CV”; zmiany z edytora wygrywają. */
  function page1Of(entryId: number, recorded: Row): Row {
    const generated =
      layoutFor(entryId) === "new"
        ? { why: CV_FICTION_WHY.map((item) => item.text), why_generated: JSON.parse(JSON.stringify(CV_FICTION_WHY)) }
        : {};
    return { ...recorded, ...generated, ...(page1.get(entryId) ?? {}) };
  }

  /** Lustro `PATCH …/cv/page1` w pamięci: `why` per slot (`null` = bez zmiany, "" = z generatora). */
  function setPage1(entryId: number, body: Row): PoligonResponse {
    const current = brandedFor(entryId);
    if (current.status !== 200) return current;
    const extras = { ...((current.data as Row).page1_extras as Row) };
    const next: Row = { ...(page1.get(entryId) ?? {}) };
    let touched = false;
    const proposals = (Array.isArray(extras.highlight_proposals) ? extras.highlight_proposals : []) as Row[];
    if ("highlight" in body && body.highlight && typeof body.highlight === "object") {
      const highlight = body.highlight as Row;
      if (highlight.mode === "custom" && !(textOf(highlight.label).trim() && textOf(highlight.text).trim())) {
        return { status: 422, data: { detail: "Wyróżnik potrzebuje etykiety i zdania." } };
      }
      if (highlight.mode === "ai") {
        // Lustro przyjęcia propozycji AI: tylko sprawdzona z listy.
        const chosen = proposals[Number(highlight.proposal)];
        if (!chosen || chosen.verified !== true) {
          return { status: 422, data: { detail: "Tej propozycji wyróżnika nie ma na liście sprawdzonych propozycji." } };
        }
        const { label, token, text, quote, key, kind } = chosen;
        next.highlight = { mode: "ai", label, token, text, quote, key, kind };
      } else {
        next.highlight = highlight.mode === "auto" ? null : highlight;
      }
      touched = true;
    }
    if (typeof body.highlight_reject === "number") {
      const rejected = proposals[body.highlight_reject];
      if (!rejected) return { status: 422, data: { detail: "Tej propozycji wyróżnika nie ma na liście sprawdzonych propozycji." } };
      next.highlight_proposals = proposals.filter((item) => item.key !== rejected.key);
      next.highlight_rejected = [...((extras.highlight_rejected as string[] | undefined) ?? []), rejected.key];
      const current = (next.highlight ?? extras.highlight) as Row | null | undefined;
      if (current?.mode === "ai" && current.key === rejected.key) next.highlight = null;
      touched = true;
    }
    if ("result_text" in body) {
      const text = textOf(body.result_text).trim();
      if (text.length > PAGE1_TEXT_MAX) return { status: 422, data: { detail: MSG_PAGE1_TOO_LONG } };
      next.result_text = text || null;
      touched = true;
    }
    if (Array.isArray(body.why)) {
      const slots = whySlots(extras);
      const auto = autoTexts(extras);
      for (const [index, value] of body.why.slice(0, 3).entries()) {
        if (value === null || value === undefined) continue;
        const text = textOf(value).split(/\s+/).filter(Boolean).join(" ");
        if (text.length > PAGE1_TEXT_MAX) return { status: 422, data: { detail: MSG_PAGE1_TOO_LONG } };
        slots[index] = text || auto[index];
      }
      next.why = slots;
      touched = true;
    }
    if (!touched) return { status: 422, data: { detail: MSG_PAGE1_EMPTY } };
    page1.set(entryId, next);
    return brandedFor(entryId);
  }

  /** „Ułóż zdania od nowa”: zdania z generatora wracają tam, gdzie nikt ich nie poprawiał. */
  function refreshPage1(entryId: number): PoligonResponse {
    const current = brandedFor(entryId);
    if (current.status !== 200) return current;
    const extras = (current.data as Row).page1_extras as Row;
    const auto = CV_FICTION_WHY.map((item) => item.text as string);
    const before = autoTexts(extras);
    const slots = whySlots(extras).map((slot, index) => (slot === "" || slot === before[index] ? auto[index] : slot));
    page1.set(entryId, { ...(page1.get(entryId) ?? {}), why: slots });
    const after = brandedFor(entryId);
    return after.status === 200 ? { status: 200, data: (after.data as Row).page1_extras } : after;
  }

  /** „Poszukaj w CV” (propozycja AI wyróżnika): fikcyjny certyfikat z CV, odrzucony nie wraca. */
  function findHighlight(entryId: number): PoligonResponse {
    const current = brandedFor(entryId);
    if (current.status !== 200) return current;
    const extras = (current.data as Row).page1_extras as Row;
    const rejected = (extras.highlight_rejected as string[] | undefined) ?? [];
    const proposals = rejected.includes(CV_FICTION_HIGHLIGHT.key) ? [] : [{ ...CV_FICTION_HIGHLIGHT }];
    page1.set(entryId, { ...(page1.get(entryId) ?? {}), highlight_proposals: proposals, highlight_source_sha: "poligon" });
    const after = brandedFor(entryId);
    return after.status === 200 ? { status: 200, data: (after.data as Row).page1_extras } : after;
  }

  /** Odczyt CV etapu do zapisu układu albo strony 1; etap bez CV do klienta → 409 jak na serwerze. */
  function brandedFor(entryId: number): PoligonResponse {
    const recorded = ctx.recorded("GET", `/api/candidates/stages/${entryId}/cv/branded`);
    if (recorded.status !== 200) return recorded;
    const data = brandedOf(entryId, recorded.data as Row);
    if (data.status === "none") return { status: 409, data: { detail: "Ta osoba nie ma jeszcze CV do klienta w tej rekrutacji." } };
    return { status: 200, data };
  }

  function setLayout(entryId: number, body: Row): PoligonResponse {
    const layout = body.cv_layout;
    if (layout !== "classic" && layout !== "new") return { status: 422, data: { detail: "Układ CV to „Nowe CV” albo „Klasyczne”." } };
    const current = brandedFor(entryId);
    if (current.status !== 200) return current;
    layouts.set(entryId, layout);
    return brandedFor(entryId);
  }

  /** Układ CV etapu — podgląd PDF „Nowego CV” na poligonie (`adapter.ts`). */
  function layoutOf(entryId: number): "classic" | "new" | null {
    return personByEntry(entryId) ? layoutFor(entryId) : null;
  }

  function saveBranded(entryId: number, body: Row | null): PoligonResponse {
    const recorded = ctx.recorded("GET", `/api/candidates/stages/${meta.template_entry_id}/cv/branded`);
    if (recorded.status !== 200) return recorded;
    const current = brandedOf(entryId, recorded.data as Row);
    const next = {
      html: body && typeof body.content_html === "string" ? body.content_html : String(current.content_html ?? ""),
      revision: Number(current.edit_revision ?? 0) + 1,
      status: "draft",
    };
    branded.set(entryId, next);
    return { status: 200, data: brandedOf(entryId, recorded.data as Row) };
  }

  function cvCommand(body: Row): PoligonResponse {
    const lines = (Array.isArray(body.lines) ? body.lines : []) as Array<{ id: number; kind: string; text: string; section?: string | null }>;
    const command = textOf(body.command).toLowerCase();
    const preset = textOf(body.preset);
    const operations: Row[] = [];
    if (command.includes("pogrub")) {
      const text = lines.map((l) => l.text).join("\n");
      const asked = CV_FICTION_TERMS.filter((t) => command.includes(t.toLowerCase()));
      const terms = (asked.length ? asked : [...CV_FICTION_TERMS]).filter((t) => text.includes(t));
      if (terms.length) {
        operations.push({ id: 0, type: "bold", lines: [], text: null, why: "Wymagania klienta widoczne na pierwszy rzut oka.", loses: [], new_words: [], terms });
      }
    } else if (preset === "summary_point") {
      const last = lines.filter((l) => l.kind === "bullet" && l.section === "why_points").at(-1);
      if (last) {
        operations.push({
          id: 0,
          type: "add",
          lines: [last.id],
          text: "Zna regulacje bankowe i pracuje z działem zgodności.",
          why: "Fakt z rozmowy, którego podsumowanie jeszcze nie mówi.",
          loses: [],
          new_words: [],
          quote: "z rozmowy telefonicznej",
          source: "rozmowa",
        });
      }
    }
    emit({ type: "cv_command", command: command || preset, operations: operations.length });
    if (!operations.length) return { status: 200, data: { status: "empty", operations: [], dropped: [], message: CV_COMMAND_EMPTY } };
    return { status: 200, data: { status: "ok", operations, dropped: [], message: null } };
  }

  // ── Jarvis ───────────────────────────────────────────────────────────
  /** Osoba z Tablicy, o którą pyta wiadomość (imię albo nazwisko, także odmienione). */
  function personIn(message: string): PoligonPerson | null {
    const words = message.toLowerCase().split(/[^\p{L}]+/u).filter((w) => w.length >= 3);
    const stem = (w: string) => w.toLowerCase().slice(0, Math.max(4, w.length - 2));
    const onBoard = meta.people.filter((p) => ctx.findItem(p.candidate_id));
    return (
      onBoard.find((p) => words.some((w) => w.startsWith(stem(p.lastname)))) ??
      onBoard.find((p) => words.some((w) => w.startsWith(stem(p.name)))) ??
      null
    );
  }

  function jarvisAnswer(message: string): string {
    const person = personIn(message);
    emit({ type: "jarvis", message, candidateId: person?.candidate_id ?? null });
    if (!person) {
      return (
        "Nie widzę na Tablicy rekrutacji ćwiczebnej osoby, o którą pytasz. Zapytaj o kogoś z kart, " +
        `np. „Co wiemy o ${ctx.template ? `${ctx.template.name} ${ctx.template.lastname}` : "tej osobie"}?”.`
      );
    }
    const found = ctx.findItem(person.candidate_id);
    const column = String(found?.column.label ?? found?.column.name ?? found?.item.stage ?? "");
    const call = found?.item.booked_call as Row | null | undefined;
    return [
      `**${person.name} ${person.lastname}** — rekrutacja ${meta.job_reference ?? "ĆW-01"} (${meta.client_name ?? "Bank Północny"}), kolumna „${column}”.`,
      "",
      "- Project Manager z 9 latami w bankowości, prowadziła program migracji płatności.",
      "- Oczekiwania: 105 zł/h na B2B, dostępna od przyszłego miesiąca.",
      call ? `- Masz z nią umówiony telefon (${new Date(String(call.start_time)).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" })}).` : "- Telefonu screeningowego jeszcze nie ma — umówisz go w panelu osoby.",
      "",
      "_Poligon: to odpowiedź ćwiczebna. W pracy Jarvis czyta notatki, CV i historię osoby, a odpowiedź powstaje na bieżąco._",
    ].join("\n");
  }

  /** Obsługa adresu przez narzędzia albo `null`, gdy to nie ich adres. */
  function handle(method: string, path: string, body: Row, viewerId: number | null): PoligonResponse | null {
    const get = method === "GET";
    if (path === "/api/screening-calls" && method === "POST") return bookCall(body, viewerId);
    const call = path.match(/^\/api\/screening-calls\/(\d+)(\/cancel)?$/);
    if (call && !get) return changeCall(Number(call[1]), call[2] ? null : body);

    if (path === "/api/interview-cycle/slots" && method === "POST") return createSlots(body, viewerId);
    if (path === "/api/interview-cycle/slots/from-mail" && method === "POST") return slotsFromMail(body);
    // Komu pójdą terminy: rekruter poligonu, bez zastępstw.
    if (path === "/api/interview-cycle/slots/recipient" && get) {
      return { status: 200, data: { recruiter_name: meta.trainers.rec?.name ?? null, substitute_name: null, until: null } };
    }
    const choose = path.match(/^\/api\/interview-cycle\/slots\/(\d+)\/choose$/);
    if (choose && method === "POST") return chooseSlot(Number(choose[1]), body);
    // Prepy z okna wyboru terminu: na poligonie nikt nie dostaje zaproszenia.
    if (path === "/api/interview-cycle/preps" && method === "POST") {
      return { status: 201, data: { id: nextId++, candidate_id: body.candidate_id, job_id: body.job_id, prep_no: body.prep_no, start: body.start, end: body.end, status: "scheduled" } };
    }

    if (path === "/api/candidates/from-cv" && method === "POST") return fromCv();
    const bulk = path.match(/^\/api\/jobs\/(\d+)\/proposals\/bulk$/);
    if (bulk && method === "POST") return addProposals(Number(bulk[1]), body);

    if (path === "/api/saved-searches") {
      if (get) return { status: 200, data: savedSearches };
      if (method === "POST") return saveSearch(body, viewerId);
    }
    const search = path.match(/^\/api\/saved-searches\/(\d+)(\/viewed)?$/);
    if (search) {
      const id = Number(search[1]);
      if (search[2]) return { status: 200, data: { previous_viewed_at: null, new_candidate_ids: [] } };
      if (method === "PATCH") return patchSearch(id, body);
      if (method === "DELETE") {
        const i = savedSearches.findIndex((r) => r.id === id);
        if (i >= 0) savedSearches.splice(i, 1);
        return { status: 204, data: null };
      }
    }

    if (path === "/api/talent-pools") {
      if (get) return { status: 200, data: pools.map(poolOut) };
      if (method === "POST") return createPool(body, viewerId);
    }
    const forCandidate = path.match(/^\/api\/talent-pools\/for-candidate\/(\d+)$/);
    if (forCandidate && get) {
      const cid = Number(forCandidate[1]);
      return { status: 200, data: { pool_ids: [...poolMembers].filter(([, m]) => m.has(cid)).map(([id]) => id) } };
    }
    const poolAdd = path.match(/^\/api\/talent-pools\/(\d+)\/(add|bulk-add)$/);
    if (poolAdd && method === "POST") {
      const ids = poolAdd[2] === "add" ? [Number(body.candidate_id)] : (Array.isArray(body.candidate_ids) ? body.candidate_ids.map(Number) : []);
      return addToPool(Number(poolAdd[1]), ids);
    }
    const poolRemove = path.match(/^\/api\/talent-pools\/(\d+)\/remove\/(\d+)$/);
    if (poolRemove && method === "DELETE") {
      poolMembers.get(Number(poolRemove[1]))?.delete(Number(poolRemove[2]));
      return { status: 204, data: null };
    }

    const chatPath = path.match(/^\/api\/jobs\/(\d+)\/chat\/(messages|pinned|read)$/);
    if (chatPath && Number(chatPath[1]) === meta.job_id) {
      const jobId = Number(chatPath[1]);
      // HTTP odczyt jest migawką: POST nie może zmienić poprzedniej odpowiedzi
      // w cache React Query, bo structural sharing ukryje nową wiadomość w UI.
      if (chatPath[2] === "messages" && get) return { status: 200, data: { items: [...chat], has_more: false, next_before_id: null } };
      if (chatPath[2] === "messages" && method === "POST") return postChat(jobId, body, viewerId);
      if (chatPath[2] === "pinned" && get) return { status: 200, data: [] };
      if (chatPath[2] === "read") return { status: 200, data: { job_id: jobId, unread_count: 0, last_read_message_id: chat[0]?.id ?? null, notifications_cleared: 0 } };
    }

    const brandedPath = path.match(/^\/api\/candidates\/stages\/(\d+)\/cv\/branded(\/new-draft)?$/);
    if (brandedPath) {
      const entryId = Number(brandedPath[1]);
      if (!personByEntry(entryId)) return null;
      if (get && !brandedPath[2]) {
        // Odczyt nagrany dla tej osoby wygrywa z osobą-szablonem (`store.read`).
        const recorded = ctx.recorded("GET", `/api/candidates/stages/${entryId}/cv/branded`);
        if (recorded.status !== 200) return recorded;
        return { status: 200, data: brandedOf(entryId, recorded.data as Row) };
      }
      if (method === "PATCH" || brandedPath[2]) return saveBranded(entryId, brandedPath[2] ? null : body);
    }
    const cvSetting = path.match(/^\/api\/candidates\/stages\/(\d+)\/cv\/(layout|page1)$/);
    if (cvSetting && method === "PATCH" && personByEntry(Number(cvSetting[1]))) {
      return cvSetting[2] === "layout" ? setLayout(Number(cvSetting[1]), body) : setPage1(Number(cvSetting[1]), body);
    }
    const page1Results = path.match(/^\/api\/candidates\/stages\/(\d+)\/cv\/page1\/results$/);
    if (page1Results && method === "POST" && personByEntry(Number(page1Results[1]))) {
      return refreshPage1(Number(page1Results[1]));
    }
    const page1Highlight = path.match(/^\/api\/candidates\/stages\/(\d+)\/cv\/page1\/highlight$/);
    if (page1Highlight && method === "POST" && personByEntry(Number(page1Highlight[1]))) {
      return findHighlight(Number(page1Highlight[1]));
    }
    const transform = path.match(/^\/api\/pipeline\/stages\/(\d+)\/qc\/transform$/);
    if (transform && method === "POST") return qcTransform(Number(transform[1]), body);
    const ai = path.match(/^\/api\/pipeline\/stages\/(\d+)\/cv-ai\/(command|applied|confirm-fact)$/);
    if (ai && method === "POST") {
      if (ai[2] === "command") return cvCommand(body);
      if (ai[2] === "applied") emit({ type: "cv_applied", operations: Number(body.operations ?? 0) });
      return { status: 200, data: { ok: true } };
    }

    // Pismo asystenta prawnego na kontrakcie ćwiczebnym: szkic i „Zatwierdzam”
    // bez modelu i bez zapisu (`legal-letter.ts`). DOCX zostaje zablokowany.
    const letter = path.match(/^\/api\/contracts\/(\d+)\/legal-letter\/(draft|approve)$/);
    if (letter && method === "POST" && Number(letter[1]) >= 990_000) {
      const contract = ctx.recorded("GET", `/api/contracts/${letter[1]}`, [], true);
      const draft = contract.status === 200 && contract.data && typeof contract.data === "object"
        ? practiceLetterDraft(contract.data as Row, body, ctx.now)
        : null;
      if (!draft) return null;
      if (letter[2] === "draft") return { status: 200, data: draft };
      return { status: 200, data: practiceLetterApprove(draft, body) };
    }

    if (path === "/api/jarvis/status" && get) {
      return {
        status: 200,
        data: { available: true, reason: null, used_today: 0, soft_limit: 50, busy: false, web_enabled: false, web_used_today: 0, web_limit: 0, capabilities: {} },
      };
    }
    return null;
  }

  return { handle, jarvisAnswer, layoutOf };
}

export type PoligonTools = ReturnType<typeof createTools>;
