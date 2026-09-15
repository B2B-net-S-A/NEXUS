"use client";

import { useState, type MouseEvent } from "react";
import { api, extractErrorMsg, EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { CHAMPION_SECTIONS, type ChampionSectionId } from "@/lib/champion-section-state";

export type ChampionIssue = { code: string; path: string; message: string; severity: "error" | "warning"; blocked_operations: string[]; source?: string | null };
export type ChampionValidation = { status: string; issues: ChampionIssue[]; blocked_operations: string[] };
export type ChampionPreview = { champion_profile: ChampionProfile; validation?: ChampionValidation };
export function championErrorValidation(error: unknown): ChampionValidation | undefined {
  return (error as { response?: { data?: { detail?: { validation?: ChampionValidation } } } } | null)?.response?.data?.detail?.validation;
}
const fields = [
  ["basics.role_name", "Nazwa roli"], ["basics.seniority_min_years", "Doświadczenie łącznie w IT (lata)"],
  ["basics.rate_value", "Maksymalna stawka PLN/h"], ["basics.work_mode", "Tryb pracy: zdalnie / hybrydowo / stacjonarnie"],
  ["basics.onsite_days_per_week", "Dni w biurze (0–7; puste = brak danych)"], ["basics.candidate_location_pref", "Lokalizacja biura"],
  ["basics.language", "Język pracy"], ["basics.start_date", "Start (RRRR-MM-DD)"], ["basics.deadline", "Termin na kandydatów (RRRR-MM-DD)"],
  ["basics.contract_length", "Długość kontraktu"], ["search.keywords", "Kluczowe słowa do wyszukiwania"],
  ["search.target_companies", "Firmy docelowe"], ["search.disqualifiers", "Kogo odrzucamy"], ["search.notes", "Uwagi / plan DL"],
  ["stack.must", "MUST — jeden wpis na wiersz; alternatywy: A lub B"], ["stack.nice", "NICE — opcjonalne"], ["stack.notes", "Uwagi / niuanse"],
  ["project.about", "O projekcie"], ["project.responsibilities", "Obowiązki"], ["client.selling_points", "Co przekona kandydata"],
  ["client.consultant_insight", "Insight konsultanta"], ["client.historical_questions", "Historyczne pytania klienta"], ["client.priority_rules", "Uwagi / standardy"],
] as const;
const rubrics = ["rate_value", "work_mode", "onsite_days_per_week", "candidate_location_pref", "must", "nice"];
// Wartość pola REKRUTACJI w dopisku „(obecnie: …)”. Tryb pracy przychodzi jako
// enum z kolumny `jobs.work_mode` — surowe „remote” w polskim oknie było
// zgłoszeniem UAT M04-B06; listy (must/nice) jako wpisy po przecinku.
const JOB_WORK_MODE_LABEL: Record<string, string> = { remote: "zdalnie", hybrid: "hybrydowo", onsite: "stacjonarnie" };
export function formatJobFieldValue(key: string, value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(v => (v && typeof v === "object" && "name" in v ? String((v as { name: unknown }).name) : String(v))).join(", ") : "—";
  if (key === "work_mode" && typeof value === "string") return JOB_WORK_MODE_LABEL[value] ?? value;
  return String(value);
}
type Values = Record<string, string>;
function readValues(profile: ChampionProfile): Values {
  const obj = profile as unknown as Record<string, Record<string, unknown>>;
  return Object.fromEntries(fields.map(([path]) => {
    const [section, key] = path.split(".");
    const value = obj[section]?.[key];
    const canonical = Array.isArray(value) ? value.map(v => typeof v === "object" ? v.name : v).join("\n") : String(value ?? "");
    const unresolved = profile.intake?.unresolved?.[path];
    return [path, Array.isArray(value) && unresolved ? [canonical, unresolved].filter(Boolean).join("\n") : unresolved ?? canonical];
  }));
}
function withValues(base: ChampionProfile, values: Values): ChampionProfile {
  const result = structuredClone({ ...EMPTY_CHAMPION_PROFILE, ...base });
  const obj = result as unknown as Record<string, Record<string, unknown>>;
  for (const [path, value] of Object.entries(values)) {
    const [section, key] = path.split(".");
    obj[section] = { ...obj[section], [key]: section === "basics" ? value || null : value };
  }
  // The server normalizes these editable strings. Explicit empty input discards
  // the old ambiguous fragment; it cannot silently revive on the next save.
  result.basics.rate_raw = null;
  result.intake = { ...base.intake, policy_version: 1, unresolved: {} };
  return result;
}

/** Sekcja edytora, w której leży pole ze ścieżki ostrzeżenia (`basics.rate_value` → `basics`). */
export function championIssueSectionId(path: string): ChampionSectionId | null {
  const head = path.split(".")[0];
  if (head === "screening_questions") return "screening_questions";
  return CHAMPION_SECTIONS.some((s) => s.id === head) ? (head as ChampionSectionId) : null;
}

/**
 * Cel odnośnika ostrzeżenia, szukany W CHWILI KLIKNIĘCIA: najpierw pole
 * (`#champion-field-*` — istnieje tylko w oknie importu), potem pole głównego
 * edytora (`[data-champion-field]`), w ich braku sekcja
 * (`#champion-section-*` — kotwice głównego edytora). Kotwica liczona przy
 * renderze prowadziła w edytorze donikąd: zmieniał się fragment adresu, fokus
 * zostawał na linku (audyt B47).
 */
export function resolveChampionIssueTarget(path: string): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const field = document.getElementById(`champion-field-${path}`);
  if (field) return field;
  // Główny edytor znaczy kontrolki pól `data-champion-field` — bez tego fokus
  // lądował na PIERWSZYM polu sekcji („Nazwa roli”), nie na polu z ostrzeżenia.
  const editorField = document.querySelector<HTMLElement>(
    `[data-champion-field="${path.replace(/["\\]/g, "\\$&")}"]`,
  );
  if (editorField) return editorField;
  const sectionId = championIssueSectionId(path);
  const anchor = CHAMPION_SECTIONS.find((s) => s.id === sectionId)?.anchor;
  return anchor ? document.getElementById(anchor) : null;
}

function focusChampionIssueTarget(target: HTMLElement): void {
  target.scrollIntoView?.({ block: "start", behavior: "smooth" });
  const control = target.querySelector<HTMLElement>("textarea:not([disabled]), input:not([disabled]), select:not([disabled])");
  const focusable = control ?? target;
  if (!control && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  focusable.focus({ preventScroll: true });
}

export function ChampionValidationPanel({ validation, onNavigate }: {
  validation?: ChampionValidation;
  /** Wołane PRZED szukaniem celu — edytor rozwija zwiniętą grupę sekcji (2·4·5). */
  onNavigate?: (sectionId: ChampionSectionId | null) => void;
}) {
  if (!validation?.issues.length) return null;
  const go = (event: MouseEvent<HTMLAnchorElement>, path: string) => {
    event.preventDefault();
    onNavigate?.(championIssueSectionId(path));
    // Po `setState` w `onNavigate` sekcja pojawia się dopiero w następnym
    // renderze — cel szukamy po nim, nie w tym samym obiegu.
    window.setTimeout(() => {
      const target = resolveChampionIssueTarget(path);
      if (target) focusChampionIssueTarget(target);
    }, 0);
  };
  return <div className="rounded-md border p-3 text-sm space-y-2" aria-live="polite">
    <p className="font-medium">{validation.blocked_operations.length ? "Szkic — uzupełnij dane przed użyciem" : "Uwagi do profilu"}</p>
    <p>Możesz zachować szkic. Blokady dotyczą wskazanych operacji.</p>
    {validation.issues.map((issue, i) => <div key={`${issue.path}-${i}`} className={issue.severity === "error" ? "text-destructive" : "text-muted-foreground"}>
      <a href={`#champion-field-${issue.path}`} onClick={e => go(e, issue.path)} className="underline">{fields.find(([p]) => p === issue.path)?.[1] ?? (issue.path.startsWith("screening_questions") ? "Pytania screeningowe" : issue.path)}</a>: {issue.message}
      {issue.blocked_operations.length > 0 && <span> Blokuje: {issue.blocked_operations.map(op => ({ search: "wyszukiwanie", handoff: "przekazanie", cv: "dopasowane CV" })[op] ?? op).join(", ")}.</span>}
      {issue.source && <p className="whitespace-pre-wrap">Wpis z dokumentu: {issue.source}</p>}
    </div>)}
  </div>;
}

export function ChampionTemplateDownload() {
  const [error, setError] = useState("");
  async function download() {
    try {
      const { data } = await api.get("/api/champion/template", { responseType: "blob" });
      const url = URL.createObjectURL(data); const a = document.createElement("a");
      a.href = url; a.download = "Profil_Championa_v4.0.docx"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(extractErrorMsg(e)); }
  }
  return <span><Button type="button" variant="outline" size="sm" onClick={download}>Pobierz wzór Championa</Button>{error && <span role="alert">{error}</span>}</span>;
}

export function ChampionImportReview({ initial, current, jobId, fingerprint, jobValues, sourceIsDocument = false, onApply, onClose }: {
  initial: ChampionPreview; current?: ChampionProfile; jobId?: number; fingerprint?: string; jobValues?: Record<string, unknown>;
  /** `initial` was just read from a DOCUMENT (preview), not built from a stored profile. */
  sourceIsDocument?: boolean;
  onApply: (profile: ChampionProfile, validation?: ChampionValidation) => void; onClose: () => void;
}) {
  const [source, setSource] = useState(initial);
  const [values, setValues] = useState(() => readValues(initial.champion_profile));
  const [existing, setExisting] = useState(current);
  const [expected, setExpected] = useState(fingerprint);
  const [currentJobValues, setCurrentJobValues] = useState(jobValues);
  const old = existing ? readValues(existing) : {};
  const [selected, setSelected] = useState<Record<string, boolean>>(() => Object.fromEntries(fields.map(([path]) => [path, !current || !readValues(current)[path]])));
  const [questions, setQuestions] = useState(initial.champion_profile.screening_questions ?? []);
  const [useQuestions, setUseQuestions] = useState(!current?.screening_questions?.length);
  const [sync, setSync] = useState<string[]>([]);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function apply(save: boolean) {
    setBusy(true); setError("");
    try {
      const final = withValues(existing ?? source.champion_profile, Object.fromEntries(fields.map(([path]) => [path, selected[path] ? values[path] : old[path] ?? ""])));
      // `withValues` drops `rate_raw`, so an EDITED rate cannot revive an old
      // ambiguous fragment. The text goes back ONLY with a rate freshly read
      // from a document and applied exactly as read: the server reads the
      // budget from "120–140 zł/h" (its upper bound) and warns it was a range.
      // A rate taken from a stored profile — kept in an import, or shown by the
      // reconcile dialog over the stored draft — goes back as a bare number:
      // the server keeps the stored text of an unchanged rate, and re-sending
      // that text made it re-read a budget nobody had touched.
      const ratePath = "basics.rate_value";
      if (sourceIsDocument && selected[ratePath] && values[ratePath] === readValues(source.champion_profile)[ratePath]) {
        final.basics.rate_raw = source.champion_profile.basics.rate_raw ?? null;
      }
      final.intake = { ...final.intake, policy_version: 1, unresolved: {}, template_version: source.champion_profile.intake?.template_version, document_context: source.champion_profile.intake?.document_context };
      final.screening_questions = useQuestions ? questions : existing?.screening_questions ?? [];
      const { data: checked } = await api.post<ChampionPreview>("/api/champion/validate", { profile: final });
      setSource(checked);
      if (save) {
        if (jobId) {
          const { data } = await api.post(`/api/jobs/${jobId}/champion-profile/apply-import`, { profile: checked.champion_profile, expected_fingerprint: expected, sync_fields: sync });
          onApply(data.champion_profile, data.validation);
        } else { onApply(checked.champion_profile, checked.validation); }
        onClose();
      }
    } catch (e) {
      setError(extractErrorMsg(e));
      const response = (e as { response?: { status: number; data?: { detail?: { champion_profile: ChampionProfile; fingerprint: string; job_values?: Record<string, unknown> } } } }).response;
      if (response?.status === 409 && response.data?.detail) {
        setExisting(response.data.detail.champion_profile); setExpected(response.data.detail.fingerprint); setCurrentJobValues(response.data.detail.job_values);
        setSelected({}); setUseQuestions(false); setSync([]);
      }
    } finally { setBusy(false); }
  }
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent aria-describedby={undefined} className="max-w-5xl max-h-[90vh] overflow-y-auto space-y-4">
      {/* Ten sam dialog służy importowi dokumentu i „Uzgodnij profil i pola
          rekrutacji” (bez dokumentu) — tytuł i wstęp mówią, która to akcja. */}
      <DialogTitle>{sourceIsDocument ? "Podgląd importu Championa" : "Uzgodnij profil i pola rekrutacji"}</DialogTitle>
      <p className="text-sm">{sourceIsDocument ? "Popraw odczytane dane. Istniejące niepuste wartości są zachowane; zaznacz pola, które chcesz zastąpić." : "Popraw dane profilu i zaznacz pola rekrutacji, które mają przyjąć wartość z profilu."}</p>
      {Object.values(source.champion_profile.intake?.document_context ?? {}).some(v => v != null && String(v).trim() !== "") && <div className="rounded border p-3 text-sm space-y-1"><p className="font-medium">Informacje z dokumentu — sprawdź zgodność z wybraną rekrutacją</p>{Object.entries(source.champion_profile.intake?.document_context ?? {}).filter(([, value]) => value != null && String(value).trim() !== "").map(([key, value]) => <p key={key} className="whitespace-pre-wrap">{({ client_name: "Klient", delivery_lead: "Delivery Lead", profile_revision: "Data i wersja profilu", source_conversations: "Rozmowy źródłowe", prep_owner: "Za prep odpowiada", last_change: "Ostatnia zmiana" } as Record<string, string>)[key] ?? key}: {value}</p>)}</div>}
      <ChampionValidationPanel validation={source.validation} />
      {fields.map(([path, label]) => <div id={`champion-field-${path}`} key={path} className="border-b pb-3 space-y-1">
        <label className="font-medium text-sm" htmlFor={`input-${path}`}>{label}</label>
        {existing && <><p className="text-xs whitespace-pre-wrap">Obecnie: {old[path] || "—"}</p><label className="text-sm flex gap-2"><input type="checkbox" checked={!!selected[path]} onChange={e => setSelected(s => ({ ...s, [path]: e.target.checked }))} />Użyj wartości z dokumentu</label></>}
        <textarea id={`input-${path}`} className="w-full rounded border bg-background p-2 text-sm" rows={path.startsWith("basics.") ? 1 : 3} value={values[path]} onChange={e => { setValues(v => ({ ...v, [path]: e.target.value })); setSelected(s => ({ ...s, [path]: true })); }} />
        {existing && <p className="text-xs whitespace-pre-wrap">Wartość końcowa: {(selected[path] ? values[path] : old[path]) || "—"}</p>}
        {jobId && rubrics.includes(path.split(".")[1]) && <label className="text-xs flex gap-2"><input type="checkbox" checked={sync.includes(path.split(".")[1])} onChange={e => setSync(s => e.target.checked ? [...s, path.split(".")[1]] : s.filter(k => k !== path.split(".")[1]))} />Uzgodnij też pole rekrutacji (obecnie: {formatJobFieldValue(path.split(".")[1], currentJobValues?.[path.split(".")[1]])})</label>}
      </div>)}
      <h3 id="champion-field-screening_questions" className="font-medium">Pytania screeningowe</h3>
      {existing && <><p className="text-sm whitespace-pre-wrap">Obecnie: {existing.screening_questions.map(q => `${q.question}\n${q.ideal_answer}\n${q.deal_breaker}`).join("\n\n") || "—"}</p><label><input type="checkbox" checked={useQuestions} onChange={e => setUseQuestions(e.target.checked)} /> Zastąp pytania odczytanymi</label></>}
      {questions.map((q, i) => <div key={q.id} className="border rounded p-2 space-y-2">{(["question", "ideal_answer", "deal_breaker"] as const).map((key, j) => <label key={key} className="block text-sm">{["Pytanie", "Idealna odpowiedź", "Deal breaker"][j]}<textarea className="w-full border rounded bg-background p-2" value={q[key]} onChange={e => { setQuestions(qs => qs.map((v, n) => n === i ? { ...v, [key]: e.target.value } : v)); setUseQuestions(true); }} /></label>)}<Button variant="outline" onClick={() => { setQuestions(qs => qs.filter((_, n) => n !== i)); setUseQuestions(true); }}>Usuń pytanie</Button></div>)}
      <Button variant="outline" onClick={() => { setQuestions(qs => [...qs, { id: `q${Date.now()}`, question: "", ideal_answer: "", deal_breaker: "" }]); setUseQuestions(true); }}>Dodaj pytanie</Button>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2 sticky bottom-0 bg-background py-3"><Button disabled={busy} onClick={() => apply(true)}>Zastosuj / zapisz szkic</Button><Button variant="outline" disabled={busy} onClick={() => apply(false)}>Sprawdź poprawki</Button><Button variant="ghost" onClick={onClose}>Anuluj</Button></div>
    </DialogContent>
  </Dialog>;
}

export function ChampionImportButton({ current, jobId, fingerprint, jobValues, onApply }: { current?: ChampionProfile; jobId?: number; fingerprint?: string; jobValues?: Record<string, unknown>; onApply: (profile: ChampionProfile, validation?: ChampionValidation) => void }) {
  const [preview, setPreview] = useState<ChampionPreview | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  return <><label className="inline-flex border rounded px-3 py-2 text-sm cursor-pointer">{busy ? "Odczytuję…" : "Importuj Word / PDF"}<input className="sr-only" type="file" accept=".docx,.pdf" disabled={busy} onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; setBusy(true); setError(""); try { const form = new FormData(); form.append("file", file); const { data } = await api.post<ChampionPreview>("/api/champion/preview", form, { headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000 }); setPreview(data); } catch (err) { setError(extractErrorMsg(err)); } finally { setBusy(false); } }} /></label>{error && <p role="alert">{error}</p>}{preview && <ChampionImportReview initial={preview} current={current} jobId={jobId} fingerprint={fingerprint} jobValues={jobValues} sourceIsDocument onApply={onApply} onClose={() => setPreview(null)} />}</>;
}
