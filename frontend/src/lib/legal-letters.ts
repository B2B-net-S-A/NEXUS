/**
 * Pismo na stronie kontraktu i zadania asystenta prawnego (część F, 25.11.2026).
 *
 * Nic nie wychodzi samo: szkic powstaje na serwerze (wzór Generatora albo
 * zdania modelu), „Zatwierdzam” sprawdza cytaty jeszcze raz, a pismo idzie
 * oknem maila NEXUSA albo jako DOCX do Dokumentów kontraktu.
 * Reguła: `docs/claude/asystent-prawny/pismo-na-kontrakcie-i-zadania-asystenta.md`.
 */

import { api, contractsApi } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

export const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export type LetterKindKey =
  | "notice_reply"
  | "termination_notice"
  | "termination_agreement"
  | "notice_withdrawal"
  | "penalty_note"
  | "client_letter";

export interface LetterKindDef {
  key: LetterKindKey;
  label: string;
  source: "template" | "model";
  /** Pismo ma sens tylko po wypowiedzeniu złożonym przez Partnera. */
  needsPartnerNotice: boolean;
  /** Typ dokumentu Generatora (wzór) — „Otwórz w Generatorze” wydaje dokument ze skutkami. */
  template?: string;
}

/** Lustro `services/legal/letters.LETTER_KINDS` (kolejność menu). */
export const LETTER_KINDS: readonly LetterKindDef[] = [
  { key: "notice_reply", label: "Odpowiedź na wypowiedzenie Partnera", source: "model", needsPartnerNotice: true },
  {
    key: "termination_notice",
    label: "Wypowiedzenie umowy przez B2B.net",
    source: "template",
    needsPartnerNotice: false,
    template: "termination_notice",
  },
  {
    key: "termination_agreement",
    label: "Porozumienie o rozwiązaniu umowy",
    source: "template",
    needsPartnerNotice: false,
    template: "termination_agreement",
  },
  {
    key: "notice_withdrawal",
    label: "Cofnięcie wypowiedzenia",
    source: "template",
    needsPartnerNotice: true,
    template: "notice_withdrawal",
  },
  { key: "penalty_note", label: "Nota / wezwanie do zapłaty kary umownej", source: "model", needsPartnerNotice: false },
  { key: "client_letter", label: "Pismo do klienta", source: "model", needsPartnerNotice: false },
];

export function letterKind(key: string | null | undefined): LetterKindDef | undefined {
  return LETTER_KINDS.find((k) => k.key === key);
}

export interface LetterContractFacts {
  contract_type: string;
  agreement_termination_party: string | null;
  agreement_termination_mode: string | null;
}

/** Partner złożył wypowiedzenie i jest ono zapisane na kontrakcie. */
export function hasPartnerNotice(contract: LetterContractFacts): boolean {
  return contract.agreement_termination_party === "consultant" && contract.agreement_termination_mode === "notice";
}

/** Rodzaje dostępne dla kontraktu B2B; odpowiedź i cofnięcie tylko po wypowiedzeniu Partnera. */
export function availableKinds(contract: LetterContractFacts): LetterKindDef[] {
  if (contract.contract_type !== "b2b") return [];
  const notice = hasPartnerNotice(contract);
  return LETTER_KINDS.filter((kind) => !kind.needsPartnerNotice || notice);
}

/** Rodzaj otwierany domyślnie: odpowiedź, gdy Partner wypowiedział, inaczej wypowiedzenie przez nas. */
export function defaultKind(contract: LetterContractFacts, requested?: string | null): LetterKindKey {
  const kinds = availableKinds(contract);
  const asked = kinds.find((k) => k.key === requested);
  if (asked) return asked.key;
  return (kinds[0]?.key ?? "termination_notice") as LetterKindKey;
}

export type CitationStatus = "ok" | "missing" | "mismatch";

export interface LetterCheck {
  status: CitationStatus;
  reason: string;
  message: string;
  citation: { raw: string; ref: string; kind: string; quote: string | null };
  source: { kind: string; ref: string; label: string | null; url: string | null; text: string } | null;
}

export interface LetterPassage {
  kind: string;
  ref: string;
  label: string | null;
  url: string | null;
  text: string;
}

export interface LetterFact {
  label: string;
  value: string;
  note: string | null;
  tone: "ok" | "warn" | "plain";
}

export interface LetterWarning {
  level: "question" | "info";
  title: string;
  message: string;
  clause_ref: string | null;
  document_name: string | null;
  actions: ("confirm_original" | "switch_to_agreement")[];
}

export interface LetterRecipient {
  kind: "partner" | "client";
  name: string;
  lines: string[];
  email: string | null;
  candidate_id: number | null;
}

export interface LetterCounts {
  ok: number;
  missing: number;
  mismatch: number;
}

export interface LetterDraft {
  kind: LetterKindKey;
  label: string;
  source: "template" | "model";
  editable: boolean;
  template: string | null;
  subject: string;
  text: string;
  recipient: LetterRecipient;
  facts: LetterFact[];
  steps: string[];
  deadline_note: string | null;
  warning: LetterWarning | null;
  checks: LetterCheck[];
  counts: LetterCounts;
  blocked: boolean;
  block_reasons: string[];
  issues: string[];
  lawyer_review: string[];
  passages: LetterPassage[];
  notes: string[];
  model: string | null;
  error: string | null;
  task_key: string | null;
  disclaimer: string;
}

export interface LetterOptions {
  kind: LetterKindKey;
  instruction?: string;
  original_confirmed?: boolean;
  delivered_on?: string | null;
  termination_date?: string | null;
  penalty_amount?: number | null;
}

/** Ciało żądania bez pustych pól (serwer ma `extra="forbid"`). */
export function letterBody(options: LetterOptions, text?: string): Record<string, unknown> {
  const body: Record<string, unknown> = { kind: options.kind };
  if (options.instruction?.trim()) body.instruction = options.instruction.trim();
  if (options.original_confirmed) body.original_confirmed = true;
  if (options.delivered_on) body.delivered_on = options.delivered_on;
  if (options.termination_date) body.termination_date = options.termination_date;
  if (options.penalty_amount && options.penalty_amount > 0) body.penalty_amount = options.penalty_amount;
  if (text !== undefined) body.text = text;
  return body;
}

const SLOW = { timeout: SLOW_ENDPOINT_TIMEOUT_MS };

export async function draftLetter(contractId: number, options: LetterOptions): Promise<LetterDraft> {
  const res = await api.post<LetterDraft>(`/api/contracts/${contractId}/legal-letter/draft`, letterBody(options), SLOW);
  return res.data;
}

export interface ApproveResult {
  approved: boolean;
  task_key: string | null;
  checks: LetterCheck[];
  counts: LetterCounts;
  text: string;
}

export async function approveLetter(contractId: number, options: LetterOptions, text: string): Promise<ApproveResult> {
  const res = await api.post<ApproveResult>(
    `/api/contracts/${contractId}/legal-letter/approve`,
    letterBody(options, text),
    SLOW,
  );
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

export function letterFilename(label: string, today: string): string {
  return `${label} — ${today}.docx`.replace(/[\\/:*?"<>|]/g, "-");
}

export async function letterDocx(contractId: number, options: LetterOptions, text: string): Promise<Blob> {
  try {
    const res = await api.post<Blob>(`/api/contracts/${contractId}/legal-letter/docx`, letterBody(options, text), {
      ...SLOW,
      responseType: "blob",
    });
    return res.data;
  } catch (err) {
    return withJsonErrorBody(err);
  }
}

/**
 * Pismo w Dokumentach to kopia do akt, nie obowiązująca umowa: bez folderu
 * plik z numerem umowy w nazwie stawałby się kartą „Obowiązuje teraz”
 * (ta sama przyczyna co folder „Poprawki asystenta” części D).
 */
export const LETTER_FOLDER_NAME = "Pisma asystenta";

export async function letterFolderId(contractId: number): Promise<number> {
  const listed = await contractsApi.documentFolders(contractId);
  const existing = listed.data.folders.find(
    (f) => f.name.trim().toLocaleLowerCase("pl") === LETTER_FOLDER_NAME.toLocaleLowerCase("pl"),
  );
  if (existing) return existing.id;
  const created = await contractsApi.createDocumentFolder(contractId, { name: LETTER_FOLDER_NAME });
  return created.data.folder.id;
}

export async function saveLetterToDocuments(contractId: number, blob: Blob, filename: string): Promise<void> {
  const fd = new FormData();
  fd.append("file", new File([blob], filename, { type: DOCX_MIME }));
  fd.append("doc_type", "other");
  fd.append("folder_id", String(await letterFolderId(contractId)));
  await contractsApi.uploadDocument(contractId, fd);
}

// ── stan panelu ─────────────────────────────────────────────────────────────

/** „3 z 4 cytatów sprawdzone · nic nie wysłano”. */
export function citationSummary(counts: LetterCounts): string {
  const total = counts.ok + counts.missing + counts.mismatch;
  const head = total === 0 ? "bez cytatów" : `${counts.ok} z ${total} ${total === 1 ? "cytatu" : "cytatów"} sprawdzone`;
  return `${head} · nic nie wysłano`;
}

export function countsOf(checks: readonly LetterCheck[]): LetterCounts {
  return {
    ok: checks.filter((c) => c.status === "ok").length,
    missing: checks.filter((c) => c.status === "missing").length,
    mismatch: checks.filter((c) => c.status === "mismatch").length,
  };
}

export interface ApprovalView {
  canApprove: boolean;
  reason: string | null;
}

/**
 * Czy „Zatwierdzam” jest aktywne. Po poprawce tekstu serwer sprawdzi cytaty
 * jeszcze raz przy zatwierdzeniu, więc blokada ze starych cytatów zostaje,
 * dopóki tekst się nie zmienił; pytanie o formę blokuje zawsze.
 */
export function approvalView(draft: LetterDraft, text: string, originalConfirmed: boolean): ApprovalView {
  if (!text.trim()) return { canApprove: false, reason: "Pismo nie ma treści." };
  if (draft.warning?.level === "question" && !originalConfirmed) {
    return { canApprove: false, reason: "Odpowiedz na pytanie o formę wypowiedzenia." };
  }
  const edited = draft.editable && text !== draft.text;
  if (edited) return { canApprove: true, reason: null };
  const reasons = draft.block_reasons.filter((r) => !r.includes("formę wypowiedzenia"));
  if (reasons.length > 0) return { canApprove: false, reason: reasons[0] };
  return { canApprove: true, reason: null };
}

export const CHECK_LABEL: Record<CitationStatus, string> = {
  ok: "zgodne ze źródłem",
  missing: "brak w źródłach",
  mismatch: "nie zgadza się ze źródłem",
};

/** Temat maila z tematu pisma: „Potwierdzenie wypowiedzenia umowy …”. */
export function mailSubject(subject: string): string {
  return subject ? subject[0].toLocaleUpperCase("pl") + subject.slice(1) : "Pismo";
}

/** Parametr adresu panelu pisma: `?pismo=<rodzaj>` (link z zadania, Jarvis). */
export const LETTER_PARAM = "pismo";

/** Adres strony kontraktu z panelem pisma (`kind`) albo bez niego (`null`); reszta parametrów zostaje. */
export function letterHref(pathname: string, search: string, kind: string | null): string {
  const params = new URLSearchParams(search);
  if (kind) params.set(LETTER_PARAM, kind);
  else params.delete(LETTER_PARAM);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

/** Rodzaj pisma z linku zadania (`/contracts/12?pismo=notice_reply`). */
export function letterKindFromHref(href: string): string | null {
  const query = href.split("?", 2)[1] ?? "";
  return new URLSearchParams(query.split("#", 1)[0]).get(LETTER_PARAM);
}

// ── zadania asystenta ───────────────────────────────────────────────────────

export interface LegalTask {
  key: string;
  kind: "notice_reply" | "client_fit_gap" | "template_review";
  severity: "info" | "warn" | "gap";
  title: string;
  detail: string;
  action_label: string;
  href: string;
  client_id: number | null;
  contract_id: number | null;
  created_at: string;
}

export async function fetchLegalTasks(contractId?: number): Promise<LegalTask[]> {
  const res = await api.get<{ items: LegalTask[] }>("/api/legal/tasks", {
    params: contractId ? { contract_id: contractId } : undefined,
  });
  return res.data.items;
}

export async function dismissLegalTask(key: string): Promise<void> {
  await api.post(`/api/legal/tasks/${encodeURIComponent(key)}/dismiss`);
}

export function legalTasksQueryKey(contractId?: number) {
  return ["legal-tasks", contractId ?? "all"] as const;
}
