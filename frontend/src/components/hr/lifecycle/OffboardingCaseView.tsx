"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { personInitials } from "@/components/hr/people/hr-format";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CASE_STATUS_LABELS,
  EXIT_INITIATOR_LABELS,
  EXIT_REASON_LABELS,
  useCaseAction,
  useDeactivateNow,
  useLifecycleCase,
  useUpdateCase,
  type LifecycleCase,
} from "@/lib/api/hr-lifecycle";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { formatWeekdayDayPl, formatIsoDatePl } from "@/lib/date-pl";

import { LifecycleTaskList } from "./LifecycleTaskList";
import {
  CASE_STATUS_TONE,
  ACCOUNT_RESULT_LABELS,
  canDeactivateNow,
  daysFromToday,
  formatMoment,
  isLiveStatus,
  offboardingMilestones,
} from "./lifecycle-format";
import { ReportsNote, WorkTable } from "./OffboardingWorkTable";

export function BackLink({ userId, name }: { userId: number; name: string }) {
  return (
    <Link
      href={`/people/${userId}`}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" aria-hidden />
      {name}
    </Link>
  );
}

/** Data albo chwila kamienia: „30.11, 18:00” dla chwili, „pon 30.11” dla dnia. */
function milestoneWhen(on: string | null): string | null {
  if (!on) return null;
  return on.length > 10 ? formatMoment(on) : formatWeekdayDayPl(on);
}

/**
 * Oś odejścia (makieta 19.10.2026): zgłoszone → rozmowa wyjściowa →
 * przekazanie pracy → konto wyłączone → sprzęt zwrócony. Zrobione z „✓”,
 * bieżący krok obwiedziony.
 */
function Milestones({ data }: { data: LifecycleCase }) {
  const steps = offboardingMilestones(data);
  const done = steps.filter((step) => step.state === "done").length;
  const fill = steps.length > 1 ? Math.min(done, steps.length - 1) / (steps.length - 1) : 0;
  return (
    <Card className="px-5 py-4">
      <ol className="relative flex flex-wrap gap-2" aria-label="Kiedy co się stanie">
        <span
          aria-hidden
          className="absolute left-[10%] right-[10%] top-3.5 hidden h-0.5 bg-border sm:block"
        >
          <span className="block h-full bg-primary" style={{ width: `${fill * 100}%` }} />
        </span>
        {steps.map((step, index) => {
          const when = milestoneWhen(step.on);
          return (
            <li
              key={step.key}
              aria-current={step.state === "current" ? "step" : undefined}
              className="relative flex min-w-28 flex-1 flex-col items-center gap-1 text-center"
            >
              <span
                className={cn(
                  "grid h-7 w-7 place-items-center rounded-full text-xs font-semibold",
                  step.state === "done"
                    ? "bg-primary text-primary-foreground"
                    : step.state === "current"
                      ? "border-2 border-primary bg-card text-primary"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {step.state === "done" ? <Check className="h-3.5 w-3.5" aria-label="zrobione" /> : index + 1}
              </span>
              <span className="text-[13px] font-semibold">{step.label}</span>
              <span className="text-xs text-muted-foreground">
                {[step.who, when].filter(Boolean).join(" · ") || "—"}
                {step.key === "account" && !data.account_closed_at ? " · też Akademia" : ""}
              </span>
            </li>
          );
        })}
      </ol>
      {data.account_close_result && data.account_close_result !== "deactivated" ? (
        <p className="mt-2 text-xs text-muted-foreground">
          {ACCOUNT_RESULT_LABELS[data.account_close_result]}
        </p>
      ) : null}
    </Card>
  );
}

function ChangeLastDayDialog({
  data,
  open,
  onOpenChange,
}: {
  data: LifecycleCase;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showToast } = useToast();
  const update = useUpdateCase(data.id);
  const [value, setValue] = useState(data.last_working_day ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = () => {
    setError(null);
    update.mutate(
      { last_working_day: value },
      {
        onSuccess: () => {
          showToast("Ostatni dzień zmieniony", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zmienić daty.")),
      },
    );
  };
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zmień ostatni dzień pracy"
      description="Terminy zadań z listy przeliczą się w dniach roboczych."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button disabled={!value || update.isPending} onClick={save}>
            Zapisz
          </Button>
        </>
      }
    >
      <FormField label="Ostatni dzień pracy" htmlFor="off-change-day">
        <Input
          id="off-change-day"
          type="date"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </FormField>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

export function OffboardingCase({ caseId }: { caseId: number }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useLifecycleCase(caseId);
  const action = useCaseAction(caseId);
  const deactivateNow = useDeactivateNow(caseId);
  const [changingDay, setChangingDay] = useState(false);

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
  const live = isLiveStatus(data.status);
  const lastDayIn = live ? daysFromToday(data.last_working_day, warsawToday()) : null;
  const run = (kind: "start" | "cancel" | "complete", done: string) =>
    action.mutate(kind, {
      onSuccess: () => showToast(done, "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się."), "error"),
    });

  const cancel = async () => {
    const ok = await askConfirm({
      title: "Cofnąć odejście?",
      description: `${data.person_name} zostaje u nas: kartoteka wraca do statusu „Aktywny”, przekazanie pracy i wyłączenie konta nie nastąpią. Zadania zostają w zamkniętej sprawie.`,
      confirmLabel: "Cofnij odejście",
      variant: "destructive",
    });
    if (ok) run("cancel", "Odejście cofnięte");
  };
  const start = async () => {
    const ok = await askConfirm({
      title: "Rozpocząć odejście?",
      description: "Wykonawcy dostaną zadania, a pętla przekaże pracę o 18:00 ostatniego dnia.",
      confirmLabel: "Rozpocznij",
    });
    if (ok) run("start", "Odejście rozpoczęte");
  };
  const deactivate = async () => {
    const ok = await askConfirm({
      title: "Wyłączyć konto teraz?",
      description: `Konto ${data.person_name} przestanie działać od razu, sesje wygasną. Admin może je włączyć w Ustawieniach → Użytkownicy.`,
      confirmLabel: "Wyłącz konto",
      variant: "destructive",
    });
    if (!ok) return;
    deactivateNow.mutate(false, {
      onSuccess: () => showToast("Konto wyłączone", "success"),
      onError: async (err) => {
        const status = (err as { response?: { status?: number } }).response?.status;
        if (status !== 409) {
          showToast(apiErrorMessage(err, "Nie udało się wyłączyć konta."), "error");
          return;
        }
        // Praca nie jest przekazana — wyłączenie mimo to jest jawną decyzją Kadr.
        const despite = await askConfirm({
          title: "Praca nie jest przekazana",
          description: `${apiErrorMessage(err, "Część pracy nie ma przejmującego.")} Wyłączyć konto mimo to? Nieprzekazana praca zostanie przy wyłączonym koncie.`,
          confirmLabel: "Wyłącz mimo to",
          variant: "destructive",
        });
        if (!despite) return;
        deactivateNow.mutate(true, {
          onSuccess: () => showToast("Konto wyłączone mimo nieprzekazanej pracy", "success"),
          onError: (again) =>
            showToast(apiErrorMessage(again, "Nie udało się wyłączyć konta."), "error"),
        });
      },
    });
  };

  return (
    <div className="space-y-4">
      {data.user_id ? <BackLink userId={data.user_id} name={data.person_name} /> : null}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-primary/10 text-base font-semibold text-primary"
          >
            {personInitials(data.person_name)}
          </span>
          <div>
            <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold text-foreground">
              Odejście · {data.person_name}
              <StatusDot tone={CASE_STATUS_TONE[data.status]}>{CASE_STATUS_LABELS[data.status]}</StatusDot>
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {[
                data.exit_initiator ? EXIT_INITIATOR_LABELS[data.exit_initiator] : null,
                data.exit_reason ? EXIT_REASON_LABELS[data.exit_reason] : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              {data.exit_initiator || data.exit_reason ? " · " : ""}
              ostatni dzień{" "}
              <span className="font-semibold text-foreground">
                {formatWeekdayDayPl(data.last_working_day)}
              </span>
              {lastDayIn ? ` (${lastDayIn})` : ""}
              {data.exit_note ? ` — ${data.exit_note}` : ""}
            </p>
          </div>
        </div>
        {data.can_manage ? (
          <div className="flex flex-wrap gap-2">
            {live && !data.handover_executed_at ? (
              <Button variant="ghost" onClick={() => setChangingDay(true)}>
                Zmień ostatni dzień
              </Button>
            ) : null}
            {data.can_cancel ? (
              <Button variant="outline" disabled={action.isPending} onClick={() => void cancel()}>
                Cofnij odejście
              </Button>
            ) : null}
            {data.status === "draft" ? (
              <Button disabled={action.isPending} onClick={() => void start()}>
                Rozpocznij
              </Button>
            ) : null}
            {canDeactivateNow(
              data.deactivate_on,
              data.account_closed_at,
              data.status,
              warsawToday(),
            ) ? (
              <Button variant="destructive" disabled={action.isPending} onClick={() => void deactivate()}>
                Wyłącz konto teraz
              </Button>
            ) : null}
            {data.status === "active" && data.account_closed_at ? (
              <Button disabled={action.isPending} onClick={() => run("complete", "Sprawa zamknięta")}>
                Zamknij sprawę
              </Button>
            ) : null}
          </div>
        ) : null}
      </header>
      {data.status === "draft" ? (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Szkic — zadania, przekazanie pracy i wyłączenie konta ruszą po „Rozpocznij”.
        </p>
      ) : null}
      {data.status === "cancelled" ? (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Odejście cofnięte {formatIsoDatePl(data.cancelled_at)}.
        </p>
      ) : null}
      <Milestones data={data} />
      <ReportsNote data={data} />
      <div className="flex flex-wrap items-start gap-4">
        <WorkTable data={data} />
        <Card className="flex-[1_1_360px] space-y-2 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Zadania</h2>
            <span className="text-sm">
              <span className="font-bold">{data.progress.done}</span>{" "}
              <span className="text-muted-foreground">z {data.progress.total}</span>
            </span>
          </div>
          <Progress
            value={data.progress.total ? (data.progress.done / data.progress.total) * 100 : 0}
            aria-label={`Zadania: ${data.progress.done} z ${data.progress.total}`}
            className="h-1.5 bg-border"
          />
          <LifecycleTaskList tasks={data.tasks} editable={data.status === "active"} grouped />
        </Card>
      </div>
      {changingDay ? (
        <ChangeLastDayDialog data={data} open={changingDay} onOpenChange={setChangingDay} />
      ) : null}
      {confirmDialog}
    </div>
  );
}
