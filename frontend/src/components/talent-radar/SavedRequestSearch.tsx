"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { jobsApi, extractErrorMsg } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ds";
import { useCapability } from "@/hooks/useCapability";
import { useAuthStore } from "@/store/auth";
import { useFullCandidateSearch } from "@/hooks/useFullCandidateSearch";
import { SavedRequestRequirements } from "./SavedRequestRequirements";
import { FullCandidateSearchResults } from "./FullCandidateSearchResults";

type JobRef = { id: number; title: string; client_name?: string | null };

function RequestResults({ job }: { job: JobRef }) {
  const actorId = useAuthStore(s => s.user?.id);
  const canEdit = useCapability("job.update");
  const canOpenProfile = useCapability("nav.candidates");
  const search = useFullCandidateSearch({ storageKey: actorId ? `nexus-full-job:${actorId}:${job.id}` : undefined });
  return <div className="space-y-4">
    <p className="font-medium">{job.title}{job.client_name ? ` · ${job.client_name}` : ""}</p>
    <p className="text-sm text-muted-foreground">Klient, hiring manager, budżet, lokalizacja i wymagania pochodzą z zapisanej rekrutacji.</p>
    <SavedRequestRequirements jobId={job.id} canEdit={canEdit} onSaved={search.clear} />
    <Button disabled={search.running} onClick={() => void search.start({ job_id: job.id })}>{search.running ? "Przegląd trwa…" : "Szukaj w całej bazie"}</Button>
    <FullCandidateSearchResults data={search.data} error={search.error} loading={search.loading} fetching={search.fetching} offset={search.offset} onPage={search.setOffset} canOpenProfile={canOpenProfile} onRetry={() => { if (search.runId) void search.refresh(); else void search.start({ job_id: job.id }); }} />
  </div>;
}

export function SavedRequestSearch() {
  const actorId = useAuthStore(s => s.user?.id);
  const [text, setText] = useState("");
  const [queryText, setQueryText] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<JobRef | null>(null);
  useEffect(() => {
    if (!actorId) return;
    try { const saved = JSON.parse(sessionStorage.getItem(`nexus-radar-request:${actorId}`) ?? "null"); if (saved && Number.isInteger(saved.id) && typeof saved.title === "string") setSelected(saved); } catch {}
  }, [actorId]);
  const jobs = useQuery({ queryKey: ["radar-request-picker", queryText, page], queryFn: () => jobsApi.list({ q: queryText || undefined, page, page_size: 20 }).then(r => r.data as { items: JobRef[]; total: number }) });
  const choose = (job: JobRef) => {
    const ref = { id: job.id, title: job.title, client_name: job.client_name };
    setSelected(ref);
    if (actorId) { try { sessionStorage.setItem(`nexus-radar-request:${actorId}`, JSON.stringify(ref)); } catch {} }
  };
  return <div className="space-y-4">
    <PageHeader title="Talent Radar" description="Wybierz tę samą rekrutację co w pipeline, aby użyć wspólnego requestu i rankingu." />
    <form className="flex gap-2" onSubmit={e => { e.preventDefault(); setQueryText(text.trim()); setPage(1); }}>
      <Input aria-label="Nazwa rekrutacji" value={text} onChange={e => setText(e.target.value)} placeholder="Szukaj rekrutacji po nazwie" />
      <Button type="submit">Znajdź rekrutację</Button>
    </form>
    {jobs.error ? <p role="alert">{extractErrorMsg(jobs.error)}</p> : jobs.isPending ? <p role="status">Wczytuję rekrutacje…</p> : <>
      <ul className="grid gap-2 md:grid-cols-2">{jobs.data?.items.map(job => <li key={job.id}><button className="w-full rounded-md border p-3 text-left hover:bg-accent" onClick={() => choose(job)} aria-pressed={selected?.id === job.id}>{job.title}{job.client_name ? ` · ${job.client_name}` : ""}</button></li>)}</ul>
      <div className="flex gap-3"><Button variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>Poprzednie rekrutacje</Button><Button variant="outline" disabled={page * 20 >= (jobs.data?.total ?? 0)} onClick={() => setPage(page + 1)}>Następne rekrutacje</Button></div>
    </>}
    {selected && <RequestResults key={selected.id} job={selected} />}
  </div>;
}
