"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { usePeople, usePerson, type HrConfig } from "@/lib/api/hr";
import {
  CASE_STATUS_LABELS,
  EXIT_INITIATOR_LABELS,
  EXIT_REASON_LABELS,
  HANDOVER_ERROR_LABELS,
  useCaseAction,
  useDeactivateNow,
  useCreateOffboarding,
  useLifecycleCase,
  useLifecycleTemplates,
  usePersonLifecycleSummary,
  useUpdateCase,
  type CaseStatus,
  type ExitInitiator,
  type ExitReason,
  type LifecycleCase,
  type TransferKind,
  type WorkRow,
} from "@/lib/api/hr-lifecycle";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { LifecycleTaskList } from "./LifecycleTaskList";
import {
  ACCOUNT_RESULT_LABELS,
  canDeactivateNow,
  formatDayShort,
  formatMoment,
  isLiveStatus,
  reportsSummary,
  warsawToday,
} from "./lifecycle-format";
import { ReceiverSelect } from "./ReceiverSelect";

const AUTO = "auto";
const NONE = "none";

const STATUS_TONE: Record<CaseStatus, StatusDotTone> = {
  draft: "neutral",
  active: "warning",
  done: "success",
  cancelled: "neutral",
};

function BackLink({ userId, name }: { userId: number; name: string }) {
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

/** Ekran odejścia: formularz (gdy nie ma sprawy) albo sprawa z przekazaniem pracy. */
export function OffboardingScreen({ userId, config }: { userId: number; config: HrConfig }) {
  const summary = usePersonLifecycleSummary(userId);
  const person = usePerson(userId);
  const state = resolveViewState({
    isLoading: summary.isLoading || person.isLoading,
    isError: summary.isError || person.isError,
    error: summary.error ?? person.error,
    isSuccess: summary.isSuccess && person.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>;
  }
  if (state !== "ready" || !summary.data || !person.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Nie ma takiej kartoteki albo moduł „Wejście i odejście” jest wyłączony."
            : undefined
        }
        onRetry={() => {
          void summary.refetch();
          void person.refetch();
        }}
      />
    );
  }
  const latest = summary.data.case;
  const showCase = latest && latest.kind === "offboarding" && latest.status !== "cancelled";
  if (showCase) {
    return <OffboardingCase caseId={latest.id} />;
  }
  const canManage = config.me.people_admin || config.me.is_admin;
  return (
    <div className="space-y-4">
      <BackLink userId={userId} name={person.data.name} />
      <h1 className="text-xl font-semibold text-foreground">
        Odejście · {person.data.name}
      </h1>
      {canManage ? (
        <OffboardingStartForm
          userId={userId}
          defaultManagerId={person.data.manager_user_id}
        />
      ) : (
        <Card className="p-4 text-sm text-muted-foreground">
          Ta osoba nie ma sprawy odejścia. Odejście zakładają Kadry.
        </Card>
      )}
    </div>
  );
}

function OffboardingStartForm({
  userId,
  defaultManagerId,
}: {
  userId: number;
  defaultManagerId: number | null;
}) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const directory = usePeople();
  const templates = useLifecycleTemplates("offboarding");
  const create = useCreateOffboarding();
  const [lastDay, setLastDay] = useState("");
  const [initiator, setInitiator] = useState<string>(NONE);
  const [reason, setReason] = useState<string>(NONE);
  const [note, setNote] = useState("");
  const [managerId, setManagerId] = useState(
    defaultManagerId == null ? NONE : String(defaultManagerId),
  );
  const [templateId, setTemplateId] = useState(AUTO);
  const [error, setError] = useState<string | null>(null);

  const managers = (directory.data?.items ?? []).filter((row) => row.user_id !== userId);
  const activeTemplates = (templates.data ?? []).filter((t) => t.is_active);

  const submit = async (start: boolean) => {
    setError(null);
    if (!lastDay) {
      setError("Podaj ostatni dzień pracy.");
      return;
    }
    if (start) {
      const ok = await askConfirm({
        title: "Rozpocząć odejście?",
        description: `Przełożony, Kadry, recepcja i IT dostaną zadania. Praca przejdzie na przejmujących ${formatDayShort(lastDay)} o 18:00, konto wyłączy się następnego dnia. Do tego czasu można cofnąć odejście.`,
        confirmLabel: "Rozpocznij",
      });
      if (!ok) return;
    }
    create.mutate(
      {
        user_id: userId,
        last_working_day: lastDay,
        exit_initiator: initiator === NONE ? null : (initiator as ExitInitiator),
        exit_reason: reason === NONE ? null : (reason as ExitReason),
        exit_note: note.trim() || null,
        manager_user_id: managerId === NONE ? null : Number(managerId),
        template_id: templateId === AUTO ? null : Number(templateId),
        start,
      },
      {
        onSuccess: () =>
          showToast(start ? "Odejście rozpoczęte" : "Szkic odejścia zapisany", "success"),
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się założyć sprawy odejścia.")),
      },
    );
  };

  return (
    <Card className="max-w-3xl space-y-4 p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Ostatni dzień pracy" htmlFor="off-last-day" required>
          <Input
            id="off-last-day"
            type="date"
            value={lastDay}
            onChange={(event) => setLastDay(event.target.value)}
          />
        </FormField>
        <FormField label="Przełożony" htmlFor="off-manager" description="Domyślnie przejmuje pracę.">
          <Select value={managerId} onValueChange={setManagerId}>
            <SelectTrigger id="off-manager">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Bez przełożonego</SelectItem>
              {managers.map((row) => (
                <SelectItem key={row.user_id} value={String(row.user_id)}>
                  {row.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Kto zakończył współpracę" htmlFor="off-initiator">
          <Select value={initiator} onValueChange={setInitiator}>
            <SelectTrigger id="off-initiator">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nie podano</SelectItem>
              {(Object.keys(EXIT_INITIATOR_LABELS) as ExitInitiator[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {EXIT_INITIATOR_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Powód" htmlFor="off-reason">
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger id="off-reason">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nie podano</SelectItem>
              {(Object.keys(EXIT_REASON_LABELS) as ExitReason[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {EXIT_REASON_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Lista zadań" htmlFor="off-template">
          <Select value={templateId} onValueChange={setTemplateId}>
            <SelectTrigger id="off-template">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO}>Dobierz do formy i działu</SelectItem>
              {activeTemplates.map((t) => (
                <SelectItem key={t.id} value={String(t.id)}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label="Notatka"
          htmlFor="off-note"
          description="Widzą ją Kadry i przełożony. Bez informacji o zdrowiu."
          className="sm:col-span-2"
        >
          <Textarea
            id="off-note"
            rows={2}
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" disabled={create.isPending} onClick={() => void submit(false)}>
          Zapisz szkic
        </Button>
        <Button disabled={create.isPending} onClick={() => void submit(true)}>
          Rozpocznij odejście
        </Button>
      </div>
      {confirmDialog}
    </Card>
  );
}

function WorkTable({ data }: { data: LifecycleCase }) {
  const rows = data.work ?? [];
  const editable = data.can_manage && isLiveStatus(data.status) && !data.handover_executed_at;
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className={CALM_ROW}>
            <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Co {data.person_name} ma w NEXUSIE</th>
            <th className={`${CALM_HEAD} px-3 py-2 text-right`}>Ile</th>
            <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Przekaż do</th>
            <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Uwagi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.kind} className={CALM_ROW}>
              <td className="px-3 py-2 font-medium text-foreground">{row.label}</td>
              <td className={`${CALM_AMOUNT} px-3 py-2`}>{row.count ?? "—"}</td>
              <td className="px-3 py-2">
                <ReceiverCell caseId={data.id} row={row} editable={editable} />
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {row.note}
                <HandoverOutcome row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Podwładni odchodzącej osoby — kto zostanie ich przełożonym (D5, etap 2). */
function ReportsNote({ data }: { data: LifecycleCase }) {
  const text = reportsSummary(data.work ?? []);
  if (!text) return null;
  return (
    <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-foreground">
      {text}
    </p>
  );
}

function ReceiverCell({
  caseId,
  row,
  editable,
}: {
  caseId: number;
  row: WorkRow;
  editable: boolean;
}) {
  if (!row.transferable) {
    return <span className="text-muted-foreground">idzie z rekrutacjami</span>;
  }
  if (editable && row.status !== "done") {
    return (
      <ReceiverSelect
        caseId={caseId}
        kind={row.kind as TransferKind}
        receiverId={row.receiver_user_id}
        receiverName={row.receiver_name}
        label={row.label}
      />
    );
  }
  return <span>{row.receiver_name ?? "—"}</span>;
}

function HandoverOutcome({ row }: { row: WorkRow }) {
  if (row.status === "done") {
    const moved = row.result
      ? Object.values(row.result).reduce((sum, value) => Math.max(sum, value), 0)
      : 0;
    return <span className={CALM_SUBLINE}>Przekazane · {moved}</span>;
  }
  if (row.status === "failed") {
    return (
      <span className={`${CALM_SUBLINE} text-destructive`}>
        {HANDOVER_ERROR_LABELS[row.error ?? "error"] ?? HANDOVER_ERROR_LABELS.error}
      </span>
    );
  }
  return null;
}

function Timeline({ data }: { data: LifecycleCase }) {
  return (
    <Card className="space-y-3 p-4">
      <h2 className="text-sm font-semibold text-foreground">Kiedy co się stanie</h2>
      <div className="flex items-start gap-3 text-sm">
        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums">
          {formatMoment(data.handover_at)}
        </span>
        <div>
          <p className="font-medium text-foreground">
            {data.handover_executed_at ? "Praca przekazana" : "Przekazanie pracy"}
          </p>
          <p className="text-xs text-muted-foreground">
            {data.handover_executed_at
              ? `Wykonane ${formatMoment(data.handover_executed_at)}.`
              : "Do tej chwili osoba pracuje normalnie."}
          </p>
        </div>
      </div>
      <div className="flex items-start gap-3 text-sm">
        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums">
          {formatDayShort(data.deactivate_on)}
        </span>
        <div>
          <p className="font-medium text-foreground">
            {data.account_close_result
              ? ACCOUNT_RESULT_LABELS[data.account_close_result]
              : "Konto wyłączone"}
          </p>
          <p className="text-xs text-muted-foreground">
            Także dostęp do Akademii w Compassie (lista osób z NEXUSA).
          </p>
        </div>
      </div>
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

function OffboardingCase({ caseId }: { caseId: number }) {
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
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">Ludzie · {data.person_name}</p>
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold text-foreground">
            Odejście · ostatni dzień {formatDayShort(data.last_working_day)}
            <StatusDot tone={STATUS_TONE[data.status]}>{CASE_STATUS_LABELS[data.status]}</StatusDot>
          </h1>
          {data.exit_initiator || data.exit_reason ? (
            <p className="mt-0.5 text-sm text-muted-foreground">
              {[
                data.exit_initiator ? EXIT_INITIATOR_LABELS[data.exit_initiator] : null,
                data.exit_reason ? EXIT_REASON_LABELS[data.exit_reason] : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              {data.exit_note ? ` — ${data.exit_note}` : ""}
            </p>
          ) : null}
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
          Odejście cofnięte {formatDate(data.cancelled_at)}.
        </p>
      ) : null}
      <ReportsNote data={data} />
      <WorkTable data={data} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Timeline data={data} />
        <Card className="space-y-2 p-4">
          <h2 className="text-sm font-semibold text-foreground">
            Zadania · {data.progress.done}/{data.progress.total}
          </h2>
          <LifecycleTaskList tasks={data.tasks} editable={data.status === "active"} />
        </Card>
      </div>
      {changingDay ? (
        <ChangeLastDayDialog data={data} open={changingDay} onOpenChange={setChangingDay} />
      ) : null}
      {confirmDialog}
    </div>
  );
}
