"use client";

/**
 * Rekrutacje → „Pytania z rozmów”. Dawny Excel z pytaniami
 * z rozmów, tylko że dopisuje się sam: każdy debrief dokłada pytania klienta,
 * a stanowisko i manager przychodzą z rekrutacji. Archiwum z Excela (0383) jest
 * w tej samej tabeli z oznaczeniem źródła. Filtry: klient, stanowisko, manager,
 * treść; „Kopiuj” daje listę pod prep kandydata.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { Copy, MessageSquareText } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useQuestionBank } from "@/lib/api/interviewCycle";
import {
  EMPTY_FILTERS,
  clientOptions,
  filterQuestions,
  managerOptions,
  questionsAsText,
  roleLabel,
  type QuestionBankFilters,
} from "@/lib/question-bank";
import { cn } from "@/lib/utils";

const PAGE = 50;
const DATE = new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Warsaw" });
const CONTROL =
  "h-9 rounded-md border border-border bg-card px-3 text-sm text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

export function InterviewQuestionBank() {
  const query = useQuestionBank();
  const { showSuccess, showError } = useToast();
  const [filters, setFilters] = useState<QuestionBankFilters>(EMPTY_FILTERS);
  const [limit, setLimit] = useState(PAGE);
  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const visible = useMemo(() => filterQuestions(items, filters), [items, filters]);
  const clients = useMemo(() => clientOptions(items), [items]);
  const managers = useMemo(() => managerOptions(items, filters.clientId), [items, filters.clientId]);
  const fromDebriefs = items.filter((q) => q.source === "debrief").length;
  const withManager = items.filter((q) => q.managers.length > 0).length;

  const set = (patch: Partial<QuestionBankFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setLimit(PAGE);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(questionsAsText(visible));
      showSuccess(`Skopiowano ${visible.length} pytań, pogrupowanych po stanowisku.`);
    } catch {
      showError("Przeglądarka nie pozwoliła skopiować. Zaznacz pytania w tabeli ręcznie.");
    }
  };

  if (query.isPending) {
    return <div className="rounded-2xl border border-border bg-card p-8 text-sm text-muted-foreground">Ładowanie pytań…</div>;
  }
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Pytania z rozmów nie wczytały się — to nie znaczy, że ich nie ma."
        onRetry={() => query.refetch()}
      />
    );
  }

  return (
    <section className="space-y-3" data-testid="question-bank">
      <p className="text-sm text-muted-foreground tabular-nums">
        {items.length.toLocaleString("pl-PL")} pytań · {fromDebriefs.toLocaleString("pl-PL")} z debriefów ·{" "}
        {(items.length - fromDebriefs).toLocaleString("pl-PL")} z archiwum (Excel) · manager znany przy{" "}
        {withManager.toLocaleString("pl-PL")}
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Klient
          <select
            aria-label="Klient"
            value={filters.clientId ?? ""}
            onChange={(e) => set({ clientId: e.target.value ? Number(e.target.value) : null, manager: null })}
            className={cn(CONTROL, "w-52")}
          >
            <option value="">Wszyscy ({items.length})</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.count})
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Stanowisko
          <input
            aria-label="Stanowisko"
            value={filters.role}
            onChange={(e) => set({ role: e.target.value })}
            placeholder="np. Data Analyst albo numer"
            className={cn(CONTROL, "w-56")}
          />
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Manager
          <select
            aria-label="Manager"
            data-tour="jobs.question-bank.manager"
            value={filters.manager ?? ""}
            onChange={(e) => set({ manager: e.target.value || null })}
            className={cn(CONTROL, "w-48")}
          >
            <option value="">Wszyscy</option>
            {managers.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          W treści
          <input
            aria-label="Szukaj w treści pytania"
            value={filters.text}
            onChange={(e) => set({ text: e.target.value })}
            placeholder="np. RLS, Excel"
            className={cn(CONTROL, "w-40")}
          />
        </label>
        <div role="radiogroup" aria-label="Źródło" className="flex h-9 items-center rounded-md bg-muted p-0.5">
          {(
            [
              ["all", "Wszystkie"],
              ["debrief", "Z debriefów"],
              ["archive", "Z Excela"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={filters.source === value}
              onClick={() => set({ source: value })}
              className={cn(
                "h-8 rounded px-2.5 text-sm",
                filters.source === value ? "bg-card font-semibold text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <Button size="sm" variant="outline" className="ml-auto h-9" onClick={copy} disabled={visible.length === 0}>
          <Copy className="h-4 w-4" aria-hidden /> Kopiuj pytania ({visible.length})
        </Button>
      </div>

      {visible.length === 0 ? (
        <EmptyState
          icon={MessageSquareText}
          title="Brak pytań dla tych filtrów"
          description="Zmień stanowisko albo managera. Nowe pytania dopisują się same z każdego debriefu."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full min-w-[56rem] text-sm">
            <thead className="bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Pytanie</th>
                <th className="px-3 py-2">Stanowisko</th>
                <th className="px-3 py-2">Klient</th>
                <th className="px-3 py-2">Manager</th>
                <th className="px-3 py-2 text-right">Padło</th>
                <th className="px-3 py-2">Ostatnio</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.slice(0, limit).map((q) => {
                const role = q.roles[0];
                return (
                  <tr key={q.id} className="align-top" data-testid="question-row">
                    <td className="max-w-[26rem] px-3 py-2 text-foreground">{q.text}</td>
                    <td className="max-w-[16rem] px-3 py-2">
                      {role ? (
                        <Link href={`/jobs/${role.job_id}`} className="text-primary hover:underline">
                          {roleLabel(role)}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">z Excela, bez rekrutacji</span>
                      )}
                      {q.roles.length > 1 ? (
                        <span className="ml-1 text-xs text-muted-foreground" title={q.roles.slice(1).map(roleLabel).join("\n")}>
                          +{q.roles.length - 1}
                        </span>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-foreground">{q.client_name}</td>
                    <td className="px-3 py-2">
                      {q.managers.length > 0 ? (
                        <span className="text-foreground">{q.managers.join(", ")}</span>
                      ) : role ? (
                        <Link href={`/jobs/${role.job_id}?tab=champion`} className="text-xs text-muted-foreground hover:text-primary hover:underline">
                          brak w rekrutacji — uzupełnij
                        </Link>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                      {q.source === "archive" && q.asked_count === 0 ? (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">Excel</span>
                      ) : (
                        `${q.asked_count}×`
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 tabular-nums text-muted-foreground">
                      {q.last_asked_at ? DATE.format(new Date(q.last_asked_at)) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {visible.length > limit ? (
            <div className="border-t border-border p-2 text-center">
              <Button size="sm" variant="ghost" onClick={() => setLimit((n) => n + PAGE)}>
                Pokaż kolejne {Math.min(PAGE, visible.length - limit)} z {visible.length - limit}
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
