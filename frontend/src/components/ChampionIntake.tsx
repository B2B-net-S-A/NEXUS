"use client";

import { useState } from "react";
import { api, extractErrorMsg, EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

export type ChampionIssue = { code: string; path: string; message: string; severity: "error" | "warning"; blocked_operations: string[]; source?: string | null };
export type ChampionValidation = { status: string; issues: ChampionIssue[]; blocked_operations: string[] };
export type ChampionPreview = { champion_profile: ChampionProfile; validation?: ChampionValidation };
export function championErrorValidation(error: unknown): ChampionValidation | undefined {
  return (error as { response?: { data?: { detail?: { validation?: ChampionValidation } } } } | null)?.response?.data?.detail?.validation;
}
const fields = [
  ["basics.role_name", "Nazwa roli"], ["basics.seniority_min_years", "Doświadczenie łącznie w IT (lata)"],
  ["basics.rate_value", "Maksymalna stawka PLN/h"], ["basics.work_mode", "Tryb pracy: zdalnie / hybrydowo / stacjonarnie"],
  ["basics.onsite_days_per_week", "Dni w biurze (0–7; puste = brak danych)"], ["basics.candidate_location_pref", "Miasto biura"],
  ["basics.language", "Język pracy"], ["basics.start_date", "Start (RRRR-MM-DD)"], ["basics.deadline", "Termin na kandydatów (RRRR-MM-DD)"],
  ["basics.contract_length", "Długość kontraktu"], ["search.keywords", "Kluczowe słowa do wyszukiwania"],
  ["search.target_companies", "Firmy docelowe"], ["search.disqualifiers", "Kogo odrzucamy"], ["search.notes", "Uwagi / plan DL"],
  ["stack.must", "MUST — jeden wpis na wiersz; alternatywy: A lub B"], ["stack.nice", "NICE — opcjonalne"], ["stack.notes", "Uwagi / niuanse"],
  ["project.about", "O projekcie"], ["project.responsibilities", "Obowiązki"], ["client.selling_points", "Co przekona kandydata"],
  ["client.consultant_insight", "Insight konsultanta"], ["client.historical_questions", "Historyczne pytania klienta"], ["client.priority_rules", "Uwagi / standardy"],
] as const;
const rubrics = ["rate_value", "work_mode", "onsite_days_per_week", "candidate_location_pref", "must", "nice"];
type Values = Record<string, string>;
function readValues(profile: ChampionProfile): Values {
  const obj = profile as unknown as Record<string, Record<string, unknown>>;
  return Object.fromEntries(fields.map(([path]) => {
    const [section, key] = path.split(".");
    const value = obj[section]?.[key];
    return [path, profile.intake?.unresolved?.[path] ?? (Array.isArray(value) ? value.map(v => typeof v === "object" ? v.name : v).join("\n") : String(value ?? ""))];
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

export function ChampionValidationPanel({ validation }: { validation?: ChampionValidation }) {
  if (!validation?.issues.length) return null;
  return <div className="rounded-md border p-3 text-sm space-y-2" aria-live="polite">
    <p className="font-medium">{validation.blocked_operations.length ? "Szkic — uzupełnij dane przed użyciem" : "Uwagi do profilu"}</p>
    <p>Możesz zachować szkic. Blokady dotyczą wskazanych operacji.</p>
    {validation.issues.map((issue, i) => <div key={`${issue.path}-${i}`} className={issue.severity === "error" ? "text-destructive" : "text-muted-foreground"}>
      <a href={`#champion-field-${issue.path}`} className="underline">{fields.find(([p]) => p === issue.path)?.[1] ?? (issue.path.startsWith("screening_questions") ? "Pytania screeningowe" : issue.path)}</a>: {issue.message}
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

export function ChampionImportReview({ initial, current, jobId, fingerprint, jobValues, onApply, onClose }: {
  initial: ChampionPreview; current?: ChampionProfile; jobId?: number; fingerprint?: string; jobValues?: Record<string, unknown>;
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
      <DialogTitle>Podgląd importu Championa</DialogTitle>
      <p className="text-sm">Popraw odczytane dane. Istniejące niepuste wartości są zachowane; zaznacz pola, które chcesz zastąpić.</p>
      {source.champion_profile.intake?.document_context && <div className="rounded border p-3 text-sm space-y-1"><p className="font-medium">Informacje z dokumentu — sprawdź zgodność z wybraną rekrutacją</p>{Object.entries(source.champion_profile.intake.document_context).map(([key, value]) => <p key={key} className="whitespace-pre-wrap">{({ client_name: "Klient", delivery_lead: "Delivery Lead", profile_revision: "Data i wersja profilu", source_conversations: "Rozmowy źródłowe", prep_owner: "Za prep odpowiada", last_change: "Ostatnia zmiana" } as Record<string, string>)[key] ?? key}: {value}</p>)}</div>}
      <ChampionValidationPanel validation={source.validation} />
      {fields.map(([path, label]) => <div id={`champion-field-${path}`} key={path} className="border-b pb-3 space-y-1">
        <label className="font-medium text-sm" htmlFor={`input-${path}`}>{label}</label>
        {existing && <><p className="text-xs whitespace-pre-wrap">Obecnie: {old[path] || "—"}</p><label className="text-sm flex gap-2"><input type="checkbox" checked={!!selected[path]} onChange={e => setSelected(s => ({ ...s, [path]: e.target.checked }))} />Użyj wartości z dokumentu</label></>}
        <textarea id={`input-${path}`} className="w-full rounded border bg-background p-2 text-sm" rows={path.startsWith("basics.") ? 1 : 3} value={values[path]} onChange={e => { setValues(v => ({ ...v, [path]: e.target.value })); setSelected(s => ({ ...s, [path]: true })); }} />
        {existing && <p className="text-xs whitespace-pre-wrap">Wartość końcowa: {(selected[path] ? values[path] : old[path]) || "—"}</p>}
        {jobId && rubrics.includes(path.split(".")[1]) && <label className="text-xs flex gap-2"><input type="checkbox" checked={sync.includes(path.split(".")[1])} onChange={e => setSync(s => e.target.checked ? [...s, path.split(".")[1]] : s.filter(k => k !== path.split(".")[1]))} />Uzgodnij też pole rekrutacji (obecnie: {String(currentJobValues?.[path.split(".")[1]] ?? "—")})</label>}
      </div>)}
      <h3 id="champion-field-screening_questions" className="font-medium">Pytania screeningowe</h3>
      {existing && <><p className="text-sm whitespace-pre-wrap">Obecnie: {existing.screening_questions.map(q => `${q.question}\n${q.ideal_answer}\n${q.deal_breaker}`).join("\n\n") || "—"}</p><label><input type="checkbox" checked={useQuestions} onChange={e => setUseQuestions(e.target.checked)} /> Zastąp pytania odczytanymi</label></>}
      {questions.map((q, i) => <div key={q.id} className="border rounded p-2 space-y-2">{(["question", "ideal_answer", "deal_breaker"] as const).map((key, j) => <label key={key} className="block text-sm">{["Pytanie", "Idealna odpowiedź", "Deal breaker"][j]}<textarea className="w-full border rounded bg-background p-2" value={q[key]} onChange={e => { setQuestions(qs => qs.map((v, n) => n === i ? { ...v, [key]: e.target.value } : v)); setUseQuestions(true); }} /></label>)}<Button variant="outline" onClick={() => setQuestions(qs => qs.filter((_, n) => n !== i))}>Usuń pytanie</Button></div>)}
      <Button variant="outline" onClick={() => { setQuestions(qs => [...qs, { id: `q${Date.now()}`, question: "", ideal_answer: "", deal_breaker: "" }]); setUseQuestions(true); }}>Dodaj pytanie</Button>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2 sticky bottom-0 bg-background py-3"><Button disabled={busy} onClick={() => apply(true)}>Zastosuj / zapisz szkic</Button><Button variant="outline" disabled={busy} onClick={() => apply(false)}>Sprawdź poprawki</Button><Button variant="ghost" onClick={onClose}>Anuluj</Button></div>
    </DialogContent>
  </Dialog>;
}

export function ChampionImportButton({ current, jobId, fingerprint, jobValues, onApply }: { current?: ChampionProfile; jobId?: number; fingerprint?: string; jobValues?: Record<string, unknown>; onApply: (profile: ChampionProfile, validation?: ChampionValidation) => void }) {
  const [preview, setPreview] = useState<ChampionPreview | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  return <><label className="inline-flex border rounded px-3 py-2 text-sm cursor-pointer">{busy ? "Odczytuję…" : "Importuj Word / PDF"}<input className="sr-only" type="file" accept=".docx,.pdf" disabled={busy} onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; setBusy(true); setError(""); try { const form = new FormData(); form.append("file", file); const { data } = await api.post<ChampionPreview>("/api/champion/preview", form, { headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000 }); setPreview(data); } catch (err) { setError(extractErrorMsg(err)); } finally { setBusy(false); } }} /></label>{error && <p role="alert">{error}</p>}{preview && <ChampionImportReview initial={preview} current={current} jobId={jobId} fingerprint={fingerprint} jobValues={jobValues} onApply={onApply} onClose={() => setPreview(null)} />}</>;
}
