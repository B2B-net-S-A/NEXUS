"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Laptop } from "lucide-react";

import { PREVIEW_PATH } from "@/components/phone-preview/access";
import { Block, Loaded, count } from "@/components/phone-preview/ui";
import { api } from "@/lib/api";
import { jobDisplayTitle } from "@/lib/job-names";

interface KanbanColumn {
  stage_def_id: number;
  name: string;
  count: number;
  category: string;
}

export default function PhonePreviewRecruitmentPage() {
  const { id } = useParams<{ id: string }>();
  const job = useQuery({
    queryKey: ["phone-preview", "job", id],
    queryFn: () => api.get<{ title?: string | null; working_title?: string | null; client_name?: string | null }>(`/api/jobs/${id}`).then((r) => r.data),
  });
  const board = useQuery({
    queryKey: ["phone-preview", "kanban", id],
    queryFn: () => api.get<{ columns: KanbanColumn[] }>(`/api/pipeline/kanban/${id}`).then((r) => r.data),
  });
  return (
    <div className="pb-6">
      <header className="sticky top-0 z-10 flex items-center gap-1 border-b bg-card px-2 py-2">
        <Link href={`${PREVIEW_PATH}/rekrutacje`} aria-label="Wróć do rekrutacji" className="flex h-11 w-11 shrink-0 items-center justify-center">
          <ChevronLeft className="h-5 w-5" />
        </Link>
        <div className="min-w-0">
          <h1 className="truncate font-semibold">{job.data ? jobDisplayTitle(job.data) : "Rekrutacja"}</h1>
          <p className="truncate text-xs text-muted-foreground">{job.data?.client_name}</p>
        </div>
      </header>
      <Block title="Etapy">
        <Loaded query={board} height="h-48">
          {(b) => {
            const active = b.columns.filter((c) => c.category !== "terminal" && c.count > 0);
            const out = b.columns.filter((c) => c.category === "terminal" && c.count > 0);
            const max = Math.max(...active.map((c) => c.count), 1);
            return (
              <>
                {active.length === 0 ? (
                  <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Nikogo w procesie.</p>
                ) : (
                  <div className="space-y-3 rounded-xl border bg-card p-3">
                    {active.map((c) => (
                      <div key={c.stage_def_id} className="text-sm">
                        <div className="flex justify-between gap-3"><span className="min-w-0 truncate">{c.name}</span><b className="tabular-nums">{c.count}</b></div>
                        <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${(c.count / max) * 100}%` }} /></div>
                      </div>
                    ))}
                  </div>
                )}
                {out.length ? <p className="pt-3 text-sm text-muted-foreground">Poza procesem: {out.map((c) => `${c.name} ${count(c.count)}`).join(" · ")}</p> : null}
              </>
            );
          }}
        </Loaded>
      </Block>
      <p className="mx-4 mt-4 flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
        <Laptop className="h-4 w-4 shrink-0" />Praca na kartach i szczegóły osób są na laptopie.
      </p>
    </div>
  );
}
