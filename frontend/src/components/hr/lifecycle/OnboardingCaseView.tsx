"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { EMPLOYMENT_TYPE_LABELS, LOCATION_LABELS } from "@/lib/api/hr";
import {
  CASE_STATUS_LABELS,
  useCaseAction,
  useLifecycleCase,
} from "@/lib/api/hr-lifecycle";
import { resolveViewState } from "@/lib/view-state";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { LifecycleTaskList } from "./LifecycleTaskList";
import { CASE_STATUS_TONE, isLiveStatus, progressLabel } from "./lifecycle-format";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

/** Sprawa wejścia (`/people/new/[caseId]`): szkic do rozpoczęcia albo zadania w toku. */
export function OnboardingCaseView({ caseId }: { caseId: number }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useLifecycleCase(caseId);
  const action = useCaseAction(caseId);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie sprawy…</p>;
  }
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (data.kind !== "onboarding") {
    return (
      <QueryStateNotice state="not_found" description="To nie jest sprawa wejścia." />
    );
  }
  const values = data.profile_values ?? {};
  const run = (kind: "start" | "cancel" | "complete", done: string) =>
    action.mutate(kind, {
      onSuccess: () => showToast(done, "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się."), "error"),
    });
  const cancel = async () => {
    const ok = await askConfirm({
      title: "Anulować wejście?",
      description: "Zadania przestaną obowiązywać. Kartoteka zostaje do decyzji Kadr.",
      confirmLabel: "Anuluj wejście",
      variant: "destructive",
    });
    if (ok) run("cancel", "Wejście anulowane");
  };

  return (
    <div className="space-y-4">
      <Link
        href={data.user_id ? `/people/${data.user_id}` : "/people"}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {data.user_id ? data.person_name : "Ludzie"}
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">Ludzie · Wejście</p>
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold text-foreground">
            {data.person_name}
            {values.job_title ? ` · ${values.job_title}` : ""} · start{" "}
            {formatWeekdayDayPl(data.start_date)}
            <StatusDot tone={CASE_STATUS_TONE[data.status]}>{CASE_STATUS_LABELS[data.status]}</StatusDot>
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">{progressLabel(data.progress)}</p>
        </div>
        {data.can_manage && isLiveStatus(data.status) ? (
          <div className="flex flex-wrap gap-2">
            {data.can_cancel ? (
              <Button variant="outline" disabled={action.isPending} onClick={() => void cancel()}>
                Anuluj wejście
              </Button>
            ) : null}
            {data.status === "draft" ? (
              <Button disabled={action.isPending} onClick={() => run("start", "Wejście rozpoczęte")}>
                Rozpocznij
              </Button>
            ) : (
              <Button disabled={action.isPending} onClick={() => run("complete", "Wejście zakończone")}>
                Zakończ wejście
              </Button>
            )}
          </div>
        ) : null}
      </header>
      {data.status === "draft" && data.user_id == null ? (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Konta {data.pending_email ? `z adresem ${data.pending_email} ` : ""}jeszcze nie ma.
          Zakłada je admin w Ustawieniach → Użytkownicy albo powstaje przy pierwszym
          logowaniu przez Microsoft — potem „Rozpocznij”.
        </p>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold text-foreground">Zatrudnienie</h2>
          <Fact label="Start">{formatWeekdayDayPl(data.start_date)}</Fact>
          <Fact label="Koordynator">{data.manager_name ?? "—"}</Fact>
          <Fact label="Forma">
            {values.employment_type ? EMPLOYMENT_TYPE_LABELS[values.employment_type] : "—"}
          </Fact>
          <Fact label="Dział">{values.department ?? "—"}</Fact>
          <Fact label="Domyślnie pracuje">
            {values.default_location ? LOCATION_LABELS[values.default_location] : "—"}
          </Fact>
          <Fact label="Lista zadań">{data.template_name ?? "—"}</Fact>
        </Card>
        <Card className="space-y-2 p-4 lg:col-span-2">
          <h2 className="text-sm font-semibold text-foreground">
            Zadania · {data.progress.done}/{data.progress.total}
          </h2>
          <LifecycleTaskList tasks={data.tasks} editable={data.status === "active"} />
        </Card>
      </div>
      {confirmDialog}
    </div>
  );
}
