"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { extractErrorMsg } from "@/lib/api";
import { matchingRequirementsApi, requirementDraft, requirementLevels, reviewedRequirements, type MatchingRequirements } from "@/lib/matching-requirements";

const labels = { must: "Obowiązkowe", nice: "Dodatkowe", excluded: "Niewymagane", uncertain: "Do rozstrzygnięcia" };

function Editor({ jobId, contract, canEdit, onSaved }: { jobId: number; contract: MatchingRequirements; canEdit: boolean; onSaved: () => void }) {
  const [draft, setDraft] = useState(() => requirementDraft(contract));
  const [policy, setPolicy] = useState(contract.missing_evidence_policy);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const queryClient = useQueryClient();
  async function save() {
    setSaving(true); setError(null);
    try {
      const reviewed = reviewedRequirements(draft, contract, policy);
      await matchingRequirementsApi.save(jobId, reviewed);
      queryClient.setQueryData(["matching-requirements", jobId], reviewed);
      void queryClient.invalidateQueries({ queryKey: ["job"] });
      onSaved();
    } catch (e) { setError(e); }
    finally { setSaving(false); }
  }
  return <div className="space-y-3 pt-3">
    <p className="text-sm text-muted-foreground">Te same wymagania obowiązują w Radarze i pipeline. Oddziel grupy przecinkami. Wpis „Python lub Java” oznacza jedną alternatywę; wszystkie grupy obowiązkowe muszą być spełnione.</p>
    {!contract.reviewed && <p className="text-sm text-amber-700">Wymagania nie zostały jeszcze sprawdzone.</p>}
    {requirementLevels.map(level => <label key={level} className="block space-y-1 text-sm">
      <span>{labels[level]}</span>
      <Textarea aria-label={labels[level]} value={draft[level]} disabled={!canEdit || saving} onChange={e => setDraft({ ...draft, [level]: e.target.value })} rows={2} />
    </label>)}
    <label className="block space-y-1 text-sm">
      <span>Brak potwierdzenia wymaganej technologii</span>
      <select className="block w-full rounded-md border bg-background p-2" value={policy} disabled={!canEdit || saving} onChange={e => setPolicy(e.target.value as typeof policy)}>
        <option value="review">Pokaż do weryfikacji</option>
        <option value="exclude">Wyklucz z wyników</option>
      </select>
    </label>
    {error != null && <p role="alert">{extractErrorMsg(error)}</p>}
    {canEdit && <Button disabled={saving} onClick={() => void save()}>{saving ? "Zapisuję…" : "Zapisz sprawdzone wymagania"}</Button>}
  </div>;
}

export function SavedRequestRequirements({ jobId, canEdit, onSaved }: { jobId: number; canEdit: boolean; onSaved: () => void }) {
  const query = useQuery({ queryKey: ["matching-requirements", jobId], queryFn: () => matchingRequirementsApi.get(jobId) });
  return <details className="rounded-lg border bg-card p-4">
    <summary className="cursor-pointer font-medium">Wymagania wyszukiwania</summary>
    {query.isPending ? <p role="status">Wczytuję wymagania…</p> : query.error ? <p role="alert">{extractErrorMsg(query.error)}</p> : query.data &&
      <Editor key={`${jobId}:${JSON.stringify(query.data)}`} jobId={jobId} contract={query.data} canEdit={canEdit} onSaved={onSaved} />}
  </details>;
}
