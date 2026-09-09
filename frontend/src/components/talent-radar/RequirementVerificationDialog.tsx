"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { extractErrorMsg } from "@/lib/api";
import { requirementVerificationsApi, type RequirementVerificationData, type VerificationStatus } from "@/lib/requirement-verifications-api";

import { useCapability } from "@/hooks/useCapability";
import { useAuthStore } from "@/store/auth";
import { hasSectionAccess } from "@/lib/section-access";

export function useCanVerifyRequirements() {
  const canWrite = useCapability("candidate.requirement.verify");
  const user = useAuthStore(state => state.user);
  return canWrite && hasSectionAccess(user, "pipeline", "write");
}

const statusLabels = { met: "Spełnione", not_met: "Niespełnione", unknown: "Do weryfikacji / wycofaj potwierdzenie" };
function localNow() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function Editor({ jobId, candidateId, onSaved, onBusy }: { jobId: number; candidateId: number; onSaved: () => void; onBusy: (busy: boolean) => void }) {
  const [data, setData] = useState<RequirementVerificationData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [index, setIndex] = useState("");
  const [status, setStatus] = useState<VerificationStatus>("unknown");
  const [evidence, setEvidence] = useState("");
  const [context, setContext] = useState("");
  const [date, setDate] = useState(localNow);
  const generation = useRef(0);

  async function load() {
    const attempt = ++generation.current;
    setLoading(true); setError(null);
    try {
      const fresh = await requirementVerificationsApi.read(jobId, candidateId);
      if (generation.current !== attempt) return;
      setData(fresh); setIndex(""); setConflict(false);
    } catch (e) { if (generation.current === attempt) setError(e); }
    finally { if (generation.current === attempt) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { generation.current += 1; }; }, [jobId, candidateId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!data || index === "" || conflict || loading || saving) return;
    const parsedDate = new Date(date);
    if (!Number.isFinite(parsedDate.getTime()) || parsedDate.getTime() > Date.now()) {
      setError(new Error("Podaj prawidłową datę weryfikacji, nie późniejszą niż teraz.")); return;
    }
    setSaving(true); onBusy(true); setError(null); setSaved(false);
    try {
      await requirementVerificationsApi.save(jobId, candidateId, {
        requirement_index: Number(index), requirements_fingerprint: data.requirements_fingerprint,
        candidate_version: data.candidate_version, status, evidence: evidence.trim(),
        usage_context: context.trim(), verified_at: parsedDate.toISOString(),
      });
      setSaved(true); setEvidence(""); setContext(""); setStatus("unknown");
      onSaved();
      await load();
    } catch (e) {
      setError(e);
      if ((e as { response?: { status?: number } }).response?.status === 409) setConflict(true);
    } finally { setSaving(false); onBusy(false); }
  }

  return <div className="space-y-4">
    {loading && <p role="status">Wczytuję wymagania i zapisane weryfikacje…</p>}
    {saved && <p role="status" className="text-sm text-green-700">Weryfikacja zapisana. Uruchom ponownie wyszukiwanie, aby przeliczyć ranking.</p>}
    {error != null && <div role="alert" className="space-y-2 text-sm text-destructive">
      <p>{extractErrorMsg(error)}</p>
      <Button variant="outline" disabled={saving || loading} onClick={() => void load()}>Odśwież dane</Button>
      {conflict && <p>Treść dowodu pozostaje w formularzu. Po odświeżeniu wybierz ponownie wymaganie.</p>}
    </div>}
    {data && <>
      {data.verifications.length > 0 && <ul className="space-y-2 text-sm">
        {data.verifications.map(v => <li key={v.id} className="rounded border p-2">
          <p>{v.requirement.any_of.join(" lub ")}: {statusLabels[v.status]}{!v.current && " — nieaktualne"}</p>
          <p className="text-muted-foreground">{new Date(v.verified_at).toLocaleString("pl-PL")} · autor #{v.reviewer_id}</p>
          <p>{v.evidence}</p><p>{v.usage_context}</p>
        </li>)}
      </ul>}
      {!data.requirements.all_of.some(r => r.level === "must" || r.level === "nice") && <p className="text-sm text-muted-foreground">Najpierw uzupełnij wymagania obowiązkowe lub dodatkowe w rekrutacji.</p>}
      <form className="space-y-3" onSubmit={save}>
        <label className="block space-y-1 text-sm">Wymaganie
          <select aria-label="Wymaganie" className="w-full rounded border bg-background p-2" value={index} onChange={e => setIndex(e.target.value)} disabled={loading || saving} required>
            <option value="">Wybierz wymaganie</option>
            {data.requirements.all_of.map((r, i) => r.level === "must" || r.level === "nice" ? <option key={i} value={i}>{r.any_of.join(" lub ")} ({r.level === "must" ? "obowiązkowe" : "dodatkowe"})</option> : null)}
          </select>
        </label>
        <label className="block space-y-1 text-sm">Wynik weryfikacji
          <select aria-label="Wynik weryfikacji" className="w-full rounded border bg-background p-2" value={status} disabled={saving} onChange={e => setStatus(e.target.value as VerificationStatus)}>
            {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <p className="text-xs text-muted-foreground">Dla „lub” wystarczy potwierdzenie jednego wariantu. „Niespełnione” oznacza, że żaden wariant nie spełnia wymaganego poziomu. Brak danych oznacz jako „Do weryfikacji”.</p>
        <label className="block space-y-1 text-sm">Dowód / uzasadnienie<Textarea aria-label="Dowód / uzasadnienie" value={evidence} onChange={e => setEvidence(e.target.value)} maxLength={4000} required disabled={saving} /></label>
        <label className="block space-y-1 text-sm">Kontekst i wymagany poziom<Textarea aria-label="Kontekst i wymagany poziom" value={context} onChange={e => setContext(e.target.value)} maxLength={2000} required disabled={saving} /></label>
        <label className="block space-y-1 text-sm">Data weryfikacji<Input aria-label="Data weryfikacji" type="datetime-local" value={date} onChange={e => setDate(e.target.value)} required disabled={saving} /></label>
        <Button type="submit" disabled={saving || loading || conflict || !index || !evidence.trim() || !context.trim() || !date}>{saving ? "Zapisuję…" : "Zapisz weryfikację"}</Button>
      </form>
    </>}
  </div>;
}

export function RequirementVerificationDialog({ jobId, candidateId, candidateName, onSaved }: { jobId: number; candidateId: number; candidateName: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }}>
    <Button size="sm" variant="outline" onClick={event => { event.stopPropagation(); setOpen(true); }}>Zweryfikuj wymaganie</Button>
    {open && <DialogContent className="max-h-[85vh] overflow-y-auto" onClick={event => event.stopPropagation()}>
      <DialogHeader><DialogTitle>Weryfikacja: {candidateName}</DialogTitle><DialogDescription>Zapisujesz ocenę dla tej rekrutacji. Dowód pozostaje oddzielony od automatycznej ekstrakcji profilu.</DialogDescription></DialogHeader>
      <Editor key={`${jobId}:${candidateId}`} jobId={jobId} candidateId={candidateId} onSaved={onSaved} onBusy={setBusy} />
    </DialogContent>}
  </Dialog>;
}
