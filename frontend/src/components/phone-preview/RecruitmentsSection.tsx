"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { MY_RECRUITMENTS_PARAMS } from "@/components/v2/dashboard/custom/MyRecruitmentsTile";
import { api } from "@/lib/api";
import { jobDisplayTitle } from "@/lib/job-names";

import { PREVIEW_PATH } from "./access";
import { Block, Kpi, Loaded, Rows, count, plDate } from "./ui";

interface StageColumn {
  stage_def_id: number;
  name: string;
  count: number;
  terminal_type: string | null;
}
interface JobRow {
  id: number;
  title?: string | null;
  working_title?: string | null;
  client_name?: string | null;
  deadline?: string | null;
  stage_columns?: StageColumn[] | null;
}
interface QuickCounts {
  attention: { overdue: number; nobody_working: number; nobody_sent: number };
  attention_mine: { overdue: number; nobody_working: number; nobody_sent: number };
}
interface P0Jobs {
  items: Array<{ job_id: number; title: string; client_name: string | null }>;
}

const PAGE_SIZE = 10;

/** Stan rekrutacji: same liczby i etapy, bez osób. Ta sama lista co kafelek „Moje rekrutacje”. */
export function RecruitmentsSection({ all }: { all: boolean }) {
  const counts = useQuery({
    queryKey: ["jobs", "quick-counts"],
    queryFn: () => api.get<QuickCounts>("/api/jobs/quick-counts").then((r) => r.data),
  });
  const p0 = useQuery({ queryKey: ["p0-jobs"], queryFn: () => api.get<P0Jobs>("/api/p0-jobs").then((r) => r.data) });
  // `compact`: wąski wiersz z tytułem, klientem, terminem i etapami, bez opisów rekrutacji.
  const params = all
    ? { open_only: true, include_stage_counts: true, sort: "deadline", page: 1, page_size: PAGE_SIZE, compact: true }
    : { ...MY_RECRUITMENTS_PARAMS, page_size: PAGE_SIZE, compact: true };
  const jobs = useQuery({
    queryKey: ["phone-preview", "jobs", params],
    queryFn: () => api.get<{ items: JobRow[]; total: number }>("/api/jobs", { params }).then((r) => r.data),
  });
  return (
    <>
      <div className="px-4 pt-4">
        <Loaded query={counts} height="h-20">
          {(c) => {
            const a = all ? c.attention : c.attention_mine;
            return (
              <div className="grid grid-cols-3 gap-2">
                <Kpi label="Po terminie" value={count(a.overdue)} />
                <Kpi label="Bez rekrutera" value={count(a.nobody_working)} />
                <Kpi label="Bez wysyłki" value={count(a.nobody_sent)} />
              </div>
            );
          }}
        </Loaded>
      </div>
      {p0.isError || p0.data?.items.length ? (
        <Block title="Pilne (P0)">
          <Loaded query={p0}>
            {(p) => (
              <Rows>
                {p.items.map((j) => (
                  <Link key={j.job_id} href={`${PREVIEW_PATH}/rekrutacje/${j.job_id}`} className="block px-3 py-2.5">
                    <div className="truncate text-sm font-medium">{j.title}</div>
                    <div className="truncate text-xs text-muted-foreground">{j.client_name}</div>
                  </Link>
                ))}
              </Rows>
            )}
          </Loaded>
        </Block>
      ) : null}
      <Block title={all ? "Otwarte, najbliższy termin" : "Moje, najbliższy termin"} note={jobs.data ? `${count(jobs.data.total)} razem` : undefined}>
        <Loaded query={jobs} height="h-64">
          {(j) =>
            j.items.length === 0 ? (
              <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Brak otwartych rekrutacji.</p>
            ) : (
              <Rows>
                {j.items.map((row) => {
                  const stages = (row.stage_columns ?? []).filter((c) => !c.terminal_type && c.count > 0);
                  return (
                    <Link key={row.id} href={`${PREVIEW_PATH}/rekrutacje/${row.id}`} className="block px-3 py-2.5">
                      <div className="truncate text-sm font-medium">{jobDisplayTitle(row)}</div>
                      <div className="truncate text-xs text-muted-foreground">{row.client_name}{row.deadline ? ` · termin ${plDate(row.deadline)}` : ""}</div>
                      <div className="mt-1 truncate text-xs tabular-nums">
                        {stages.length ? stages.map((c) => `${c.name.split(" /")[0]} ${c.count}`).join(" · ") : "Nikogo w procesie"}
                      </div>
                    </Link>
                  );
                })}
              </Rows>
            )
          }
        </Loaded>
      </Block>
    </>
  );
}
