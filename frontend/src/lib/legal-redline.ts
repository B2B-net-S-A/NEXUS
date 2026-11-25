/**
 * „Popraw dokument” (asystent prawny, część D): typy odpowiedzi
 * `POST /api/legal/redline`, wywołania API i czysta logika panelu —
 * podział akapitu na tekst / skreślenie / wstawkę, stany „Przyjmij / Odrzuć”,
 * poprawki „Zmień” i lista zmian do pliku DOCX.
 *
 * Reguła: docs/claude/asystent-prawny/popraw-dokument-docx-ze-sledzeniem-zmian.md
 */

import { api, contractsApi } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

export const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export type RedlineChangeKind = "replace" | "insert_paragraph" | "delete_paragraph";
export type CitationState = "ok" | "missing" | "mismatch";

export interface RedlineSource {
  ref: string;
  label: string;
  quote: string;
  kind: string;
  url?: string | null;
  state: CitationState;
}

export interface RedlineChange {
  id: string;
  kind: RedlineChangeKind;
  paragraph: number;
  new_text: string;
  find: string;
  start: number | null;
  end: number | null;
  before: boolean;
  reason: string;
  sources: RedlineSource[];
  blocked: boolean;
}

export interface RedlineParagraph {
  index: number;
  text: string;
  style: string | null;
  in_table: boolean;
  heading: boolean;
}

export type RedlineAiStatus = "ok" | "failed" | "off" | "no_instruction" | "too_long" | "diff" | "manual";

export interface RedlineResponse {
  source: {
    name: string;
    sha256: string;
    contract_id: number | null;
    document_id: number | null;
    generated_id: number | null;
  };
  paragraphs: RedlineParagraph[];
  changes: RedlineChange[];
  notes: string[];
  dropped: { paragraph: number | null; reason: string }[];
  ai: { status: RedlineAiStatus; model: string | null };
}

/** Skąd jest dokument: plik z Dokumentów kontraktu albo plik w ręku (z dysku, z rejestru Generatora). */
export type RedlineTarget =
  | { kind: "contract-document"; contractId: number; documentId: number; name: string; docType?: string | null }
  | { kind: "file"; file: File; contractId: number | null; generatedId: number | null };

export function isDocxName(name: string | null | undefined): boolean {
  return Boolean(name && /\.docx$/i.test(name.trim()));
}

function targetForm(target: RedlineTarget): FormData {
  const fd = new FormData();
  if (target.kind === "contract-document") {
    fd.append("contract_id", String(target.contractId));
    fd.append("document_id", String(target.documentId));
  } else {
    fd.append("file", target.file);
    if (target.contractId != null) fd.append("contract_id", String(target.contractId));
    if (target.generatedId != null) fd.append("generated_id", String(target.generatedId));
  }
  return fd;
}

// `api` ma domyślnie `Content-Type: application/json` — bez nadpisania
// FormData wychodzi bez granicy multipart i serwer nie widzi pól. Model
// i budowa pliku trwają dłużej niż domyślne 30 s.
// Nagłówek multipart stoi w każdym wywołaniu wprost — strażnik
// `formdata-multipart.test.ts` czyta źródło wywołania, nie stałą.

export type ProposeMode =
  | { mode: "ai"; instruction: string }
  | { mode: "diff"; newText: string }
  | { mode: "manual" };

export async function proposeRedline(target: RedlineTarget, request: ProposeMode): Promise<RedlineResponse> {
  const fd = targetForm(target);
  if (request.mode === "ai") fd.append("instruction", request.instruction);
  if (request.mode === "diff") fd.append("new_text", request.newText);
  if (request.mode === "manual") fd.append("use_ai", "false");
  const res = await api.post<RedlineResponse>("/api/legal/redline", fd, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: SLOW_ENDPOINT_TIMEOUT_MS,
  });
  return res.data;
}

/** Błąd odpowiedzi z `responseType: "blob"` — JSON z Bloba, żeby `apiErrorMessage` przeczytał `detail`. */
async function withJsonErrorBody(err: unknown): Promise<never> {
  const response = (err as { response?: { data?: unknown } } | null)?.response;
  if (response && typeof Blob !== "undefined" && response.data instanceof Blob) {
    try {
      response.data = JSON.parse(await response.data.text());
    } catch {
      // Treść nie jest JSON-em — zostaje komunikat zapasowy wołającego.
    }
  }
  throw err;
}

export async function renderRedline(
  target: RedlineTarget,
  sha256: string,
  changes: RedlineChange[],
): Promise<{ blob: Blob; filename: string }> {
  const fd = targetForm(target);
  fd.append("sha256", sha256);
  fd.append("changes", JSON.stringify(changes));
  try {
    const res = await api.post<Blob>("/api/legal/redline/render", fd, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      responseType: "blob",
    });
    const disposition = String(res.headers["content-disposition"] ?? "");
    return { blob: res.data, filename: dispositionFilename(disposition, "Dokument — poprawki asystenta.docx") };
  } catch (err) {
    return withJsonErrorBody(err);
  }
}

/**
 * Plik ze śledzeniem zmian to szkic, nie obowiązująca umowa. Bez folderu
 * nazwa z numerem umowy trafiała do karty „Obowiązuje teraz → Umowa”, a plik
 * w folderze to archiwum (`kontrakty/foldery-w-dokumentach-kontraktu.md`).
 */
export const REDLINE_FOLDER_NAME = "Poprawki asystenta";

export async function redlineFolderId(contractId: number): Promise<number> {
  const listed = await contractsApi.documentFolders(contractId);
  const existing = listed.data.folders.find(
    (f) => f.name.trim().toLocaleLowerCase("pl") === REDLINE_FOLDER_NAME.toLocaleLowerCase("pl"),
  );
  if (existing) return existing.id;
  const created = await contractsApi.createDocumentFolder(contractId, { name: REDLINE_FOLDER_NAME });
  return created.data.folder.id;
}

export function dispositionFilename(disposition: string, fallback: string): string {
  const extended = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (extended) {
    try {
      return decodeURIComponent(extended[1]);
    } catch {
      // zły zapis procentowy — niżej zwykły parametr
    }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

// ── stan panelu ─────────────────────────────────────────────────────────────

export type Decision = "pending" | "accepted" | "rejected";

export interface ChangeEdit {
  new_text: string;
  reason: string;
}

/** Zmiana po „Zmień”: nowy tekst i powód człowieka; cytaty bez pokrycia znikają, a z nimi blokada. */
export function effectiveChange(change: RedlineChange, edit: ChangeEdit | undefined): RedlineChange {
  if (!edit) return change;
  const sources = change.sources.filter((s) => s.state === "ok");
  return { ...change, new_text: edit.new_text, reason: edit.reason, sources, blocked: false };
}

/** Kolejność zmian w dokumencie: akapit, potem miejsce w akapicie; nowy akapit za zmianami swojej kotwicy. */
export function orderChanges(changes: readonly RedlineChange[]): RedlineChange[] {
  const rank = (c: RedlineChange) => (c.kind === "insert_paragraph" ? (c.before ? -1 : Number.MAX_SAFE_INTEGER) : c.start ?? 0);
  return [...changes].sort((a, b) => a.paragraph - b.paragraph || rank(a) - rank(b));
}

export function changeNumbers(changes: readonly RedlineChange[]): Map<string, number> {
  return new Map(orderChanges(changes).map((c, i) => [c.id, i + 1]));
}

export interface RedlineSummary {
  total: number;
  accepted: number;
  rejected: number;
  pending: number;
  blocked: number;
}

export function summarize(
  changes: readonly RedlineChange[],
  decisions: Record<string, Decision>,
  edits: Record<string, ChangeEdit>,
): RedlineSummary {
  const out: RedlineSummary = { total: changes.length, accepted: 0, rejected: 0, pending: 0, blocked: 0 };
  for (const change of changes) {
    const state = decisions[change.id] ?? "pending";
    out[state] += 1;
    if (effectiveChange(change, edits[change.id]).blocked) out.blocked += 1;
  }
  return out;
}

/** Zmiany do pliku DOCX: tylko przyjęte, po poprawkach człowieka. */
export function acceptedChanges(
  changes: readonly RedlineChange[],
  decisions: Record<string, Decision>,
  edits: Record<string, ChangeEdit>,
): RedlineChange[] {
  return orderChanges(changes)
    .filter((c) => decisions[c.id] === "accepted")
    .map((c) => effectiveChange(c, edits[c.id]));
}

/** „Przyjmij wszystkie” pomija zablokowane — cytat bez pokrycia przyjmuje się dopiero po „Zmień”. */
export function acceptAll(
  changes: readonly RedlineChange[],
  decisions: Record<string, Decision>,
  edits: Record<string, ChangeEdit>,
): Record<string, Decision> {
  const next = { ...decisions };
  for (const change of changes) {
    if ((next[change.id] ?? "pending") !== "pending") continue;
    if (effectiveChange(change, edits[change.id]).blocked) continue;
    next[change.id] = "accepted";
  }
  return next;
}

// ── podgląd tekstu ze zmianami ──────────────────────────────────────────────

export type Piece =
  | { kind: "text"; text: string }
  | { kind: "del"; text: string; changeId: string; decision: Decision }
  | { kind: "ins"; text: string; changeId: string; decision: Decision };

/**
 * Akapit jako kawałki: tekst, skreślenie, wstawka. Odrzucona zmiana to
 * zwykły tekst oryginału (bez znaczników), przyjęta i czekająca — skreślenie
 * i wstawka obok siebie, jak w Wordzie.
 */
export function paragraphPieces(
  paragraph: RedlineParagraph,
  changes: readonly RedlineChange[],
  decisions: Record<string, Decision>,
  edits: Record<string, ChangeEdit>,
): Piece[] {
  const text = paragraph.text;
  const own = changes.filter((c) => c.paragraph === paragraph.index && c.kind !== "insert_paragraph");
  const whole = own.find((c) => c.kind === "delete_paragraph");
  if (whole) {
    const decision = decisions[whole.id] ?? "pending";
    return decision === "rejected" ? [{ kind: "text", text }] : [{ kind: "del", text, changeId: whole.id, decision }];
  }
  const inline = orderChanges(own).filter((c) => c.start != null && c.end != null);
  const pieces: Piece[] = [];
  let pos = 0;
  for (const raw of inline) {
    const change = effectiveChange(raw, edits[raw.id]);
    const start = change.start as number;
    const end = change.end as number;
    if (start < pos || end > text.length) continue;
    if (start > pos) pieces.push({ kind: "text", text: text.slice(pos, start) });
    const decision = decisions[change.id] ?? "pending";
    const original = text.slice(start, end);
    if (decision === "rejected") {
      if (original) pieces.push({ kind: "text", text: original });
    } else {
      if (original) pieces.push({ kind: "del", text: original, changeId: change.id, decision });
      if (change.new_text) pieces.push({ kind: "ins", text: change.new_text, changeId: change.id, decision });
    }
    pos = end;
  }
  if (pos < text.length) pieces.push({ kind: "text", text: text.slice(pos) });
  return mergeText(pieces);
}

function mergeText(pieces: Piece[]): Piece[] {
  const out: Piece[] = [];
  for (const piece of pieces) {
    const last = out[out.length - 1];
    if (piece.kind === "text" && last?.kind === "text") {
      out[out.length - 1] = { kind: "text", text: last.text + piece.text };
    } else {
      out.push(piece);
    }
  }
  return out;
}

/** Nowe akapity przed (`before`) i za akapitem `index`, w kolejności zmian; odrzucone znikają z podglądu. */
export function insertedParagraphs(
  index: number,
  changes: readonly RedlineChange[],
  decisions: Record<string, Decision>,
  edits: Record<string, ChangeEdit>,
  position: "before" | "after",
): { change: RedlineChange; decision: Decision }[] {
  return changes
    .filter(
      (c) => c.kind === "insert_paragraph" && c.paragraph === index && (position === "before") === Boolean(c.before),
    )
    .map((c) => ({ change: effectiveChange(c, edits[c.id]), decision: decisions[c.id] ?? "pending" }))
    .filter((item) => item.decision !== "rejected");
}

const SECTION_MARK = /^§\s*\d+[a-zA-Z]?\b/;

/**
 * Opis miejsca zmiany na karcie: najbliższy „§ N” nad zmianą (z tytułem
 * z następnego krótkiego akapitu, jak w naszych umowach), potem nagłówek
 * ze stylem, a na końcu początek samego akapitu.
 */
export function changePlace(change: RedlineChange, paragraphs: readonly RedlineParagraph[]): string {
  for (let i = change.paragraph; i >= 0; i -= 1) {
    const text = paragraphs[i]?.text.trim() ?? "";
    if (!SECTION_MARK.test(text)) continue;
    if (text.length > 12) return text.slice(0, 70);
    const title = paragraphs[i + 1]?.text.trim() ?? "";
    return i + 1 < change.paragraph && title && title.length <= 80 ? `${text} ${title}` : text;
  }
  for (let i = change.paragraph; i >= 0; i -= 1) {
    const p = paragraphs[i];
    if (p?.heading && p.text.trim()) return p.text.trim().slice(0, 60);
  }
  const p = paragraphs[change.paragraph];
  const head = p?.text.trim().slice(0, 40);
  return head ? `„${head}${(p?.text.trim().length ?? 0) > 40 ? "…" : ""}”` : `Akapit ${change.paragraph + 1}`;
}

export function changeKindLabel(change: RedlineChange): string {
  if (change.kind === "insert_paragraph") return "Nowy ustęp";
  if (change.kind === "delete_paragraph") return "Skreślenie ustępu";
  if (!change.find) return "Dopisanie";
  if (!change.new_text) return "Skreślenie";
  return "Zmiana treści";
}

/** Zdanie o stanie modelu nad listą zmian (pusta lista nie może wyglądać jak „bez uwag”). */
export function aiStatusMessage(status: RedlineAiStatus, count: number): string | null {
  switch (status) {
    case "ok":
      return count === 0 ? "Asystent nie zaproponował zmian dla tego polecenia." : null;
    case "failed":
      return "Asystent nie odpowiedział — możesz wkleić poprawioną treść i porównać wersje albo spróbować ponownie.";
    case "off":
      return "Propozycje asystenta są wyłączone w Ustawieniach AI — zostaje porównanie wersji.";
    case "too_long":
      return "Dokument jest za długi dla asystenta — porównaj wersje, wklejając poprawioną treść.";
    case "no_instruction":
      return "Wpisz polecenie, żeby asystent zaproponował zmiany.";
    case "diff":
      return count === 0 ? "Obie wersje są takie same — nie ma zmian." : null;
    default:
      return null;
  }
}

/**
 * Tekst do porównania: akapit w wierszu, a złamanie wiersza w akapicie
 * (`w:br`) jako U+2028 — serwer zamienia je z powrotem (`diff.py`). Bez tego
 * akapit „§ 2 ⏎ Definicje” rozjeżdżał porównanie na dziesiątki zmian.
 */
export function documentText(paragraphs: readonly RedlineParagraph[]): string {
  return paragraphs.map((p) => p.text.replace(/\n/g, "\u2028")).join("\n");
}
