"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Flag, MoreHorizontal } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useTraineeDecision,
  useTraineeOverview,
  useUpdateTraineeProgram,
  type TraineeDecisionBody,
  type TraineeOverview,
  type TraineeOverviewRow,
} from "@/lib/api/trainee";
import {
  TRAINEE_STATE_LABEL,
  daysCompletedLabel,
  decisionSummary,
  lowAnswerNote,
  pctLabel,
  poolWorkdays,
  qualityLabel,
  traineeState,
  type TraineeState,
} from "@/lib/trainee-panel";
import { cn } from "@/lib/utils";

import { QualitySampleDialog } from "./QualitySampleDialog";

const STATE_CLASS: Record<TraineeState, string> = {
  decision: "border border-primary/30 bg-primary/10 text-primary",
  check: "border border-warning/25 bg-warning-muted text-warning-muted-foreground",
  below_norm: "border border-destructive/20 bg-destructive-muted text-destructive-muted-foreground",
  ok: "border border-success/20 bg-success-muted text-success-muted-foreground",
  not_started: "bg-muted text-muted-foreground",
  ended: "bg-muted text-muted-foreground",
};

const NUMBER = new Intl.NumberFormat("pl-PL");

// ── Okna ─────────────────────────────────────────────────────────────────────

function ProgramEditDialog({
  row,
  onClose,
}: {
  row: TraineeOverviewRow | null;
  onClose: () => void;
}) {
  const update = useUpdateTraineeProgram();
  const [start, setStart] = useState("");
  const [workdays, setWorkdays] = useState("40");
  const [listSize, setListSize] = useState("70");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!row) return;
    setStart(row.program?.start_date ?? "");
    setWorkdays(String(row.program?.workdays ?? 40));
    setListSize(String(row.program?.daily_list_size ?? 70));
    setError(null);
  }, [row]);

  const submit = () => {
    if (!row) return;
    const days = Number(workdays);
    const size = Number(listSize);
    if (!Number.isInteger(days) || days < 1 || !Number.isInteger(size) || size < 1) {
      setError("Długość i liczba pozycji muszą być dodatnimi liczbami całkowitymi.");
      return;
    }
    update.mutate(
      {
        userId: row.user_id,
        body: { ...(start ? { start_date: start } : {}), workdays: days, daily_list_size: size },
      },
      {
        onSuccess: onClose,
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać programu.")),
      },
    );
  };

  const field = "h-11 rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:border-primary focus:outline-hidden";
  return (
    <AppModal
      open={row != null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Program wdrożenia — ${row?.name ?? ""}`}
      description="Koniec programu liczymy w polskich dniach roboczych. Na 5 dni przed końcem dostaniesz powiadomienie o decyzji."
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={update.isPending}>
            Anuluj
          </Button>
          <Button onClick={submit} loading={update.isPending} disabled={update.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
          Start
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={field} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
          Długość (dni robocze)
          <input
            type="number"
            min={1}
            inputMode="numeric"
            value={workdays}
            onChange={(e) => setWorkdays(e.target.value)}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
          Pozycji na liście dziennie
          <input
            type="number"
            min={1}
            inputMode="numeric"
            value={listSize}
            onChange={(e) => setListSize(e.target.value)}
            className={field}
          />
        </label>
      </div>
      {row?.program?.end_date ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Obecny koniec programu: {row.program.end_date.split("-").reverse().join(".")}.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

type PendingDecision =
  | { kind: "promote"; row: TraineeOverviewRow; role: "sourcer" | "recruiter" }
  | { kind: "end"; row: TraineeOverviewRow };

function DecisionDialog({
  pending,
  onClose,
  onDone,
}: {
  pending: PendingDecision | null;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const decision = useTraineeDecision();
  const [addToMyPeople, setAddToMyPeople] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setAddToMyPeople(true);
    setError(null);
  }, [pending]);
  if (!pending) {
    return null;
  }
  const roleLabel = pending.kind === "promote" && pending.role === "recruiter" ? "rekrutera" : "sourcera";
  const submit = () => {
    const body: TraineeDecisionBody =
      pending.kind === "promote"
        ? { action: "promote", role: pending.role, add_to_my_people: addToMyPeople }
        : { action: "end" };
    decision.mutate(
      { userId: pending.row.user_id, body },
      {
        onSuccess: () =>
          onDone(
            pending.kind === "promote"
              ? `${pending.row.name} ma od teraz rolę ${roleLabel}. Nowy widok zobaczy po odświeżeniu aplikacji.`
              : `Program ${pending.row.name} zakończony. Lista telefonów znika od jutra.`,
          ),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")),
      },
    );
  };
  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={
        pending.kind === "promote"
          ? `Zmienić rolę ${pending.row.name} na ${roleLabel}?`
          : `Zakończyć program ${pending.row.name}?`
      }
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={decision.isPending}>
            Anuluj
          </Button>
          <Button
            variant={pending.kind === "end" ? "destructive" : "primary"}
            onClick={submit}
            loading={decision.isPending}
            disabled={decision.isPending}
          >
            {pending.kind === "promote" ? `Zmień rolę na ${roleLabel}` : "Zakończ program"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-sm text-foreground">
        {pending.kind === "promote" ? (
          <>
            <ul className="list-disc space-y-1 pl-5">
              <li>program się kończy, lista telefonów znika,</li>
              <li>historia rozmów zostaje w profilach kandydatów,</li>
              <li>od następnego dnia osoba działa jak pozostali w tej roli.</li>
            </ul>
            <label className="flex items-start gap-3 rounded-lg border border-border px-3 py-2.5">
              <input
                type="checkbox"
                checked={addToMyPeople}
                onChange={(e) => setAddToMyPeople(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-border accent-[hsl(var(--primary))]"
              />
              <span>
                <span className="font-medium">
                  Dodaj rozmówców do jej/jego „Moich ludzi”
                </span>
                <span className="block text-xs text-muted-foreground">
                  Kandydaci z jej/jego rozmów, którzy szukają projektu.
                  Pomijamy tych, którzy są już na liście innego rekrutera.
                </span>
              </span>
            </label>
          </>
        ) : (
          <p>
            Lista telefonów znika, historia rozmów zostaje w profilach kandydatów. Rolę konta
            zmienisz potem w Ustawieniach → Osoby i role.
          </p>
        )}
        {error ? (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

// ── Sekcje ───────────────────────────────────────────────────────────────────

function DecisionBanner({
  row,
  onPromote,
  onExtend,
  onEnd,
  extending,
}: {
  row: TraineeOverviewRow;
  onPromote: (role: "sourcer" | "recruiter") => void;
  onExtend: () => void;
  onEnd: () => void;
  extending: boolean;
}) {
  return (
    <section
      aria-label={`Decyzja: ${row.name}`}
      className="flex flex-col gap-3 rounded-xl border border-primary/30 bg-primary/5 p-4 lg:flex-row lg:items-center"
    >
      <Flag className="hidden h-5 w-5 shrink-0 text-primary lg:block" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          {row.name} kończy {row.program?.total_days ?? 40} dni programu. Czas na decyzję.
        </p>
        <p className="text-xs text-muted-foreground">{decisionSummary(row)}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="lg" className="min-h-11" onClick={() => onPromote("sourcer")}>
          Zmień rolę na sourcera
        </Button>
        <Button size="lg" variant="outline" className="min-h-11" onClick={() => onPromote("recruiter")}>
          Zmień rolę na rekrutera
        </Button>
        <Button
          size="lg"
          variant="outline"
          className="min-h-11"
          onClick={onExtend}
          loading={extending}
          disabled={extending}
        >
          Przedłuż o 20 dni
        </Button>
        <Button size="lg" variant="ghost" className="min-h-11" onClick={onEnd}>
          Zakończ program
        </Button>
      </div>
    </section>
  );
}

function TraineesTable({
  overview,
  onEdit,
  onSample,
}: {
  overview: TraineeOverview;
  onEdit: (row: TraineeOverviewRow) => void;
  onSample: (row: TraineeOverviewRow) => void;
}) {
  const head = "px-3 py-2 text-left text-xs font-semibold text-muted-foreground";
  const cell = "px-3 py-2.5 align-top text-sm tabular-nums text-foreground";
  return (
    <section aria-label="Lista praktykantów" className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] border-collapse">
          <thead className="bg-muted">
            <tr>
              <th scope="col" className={cn(head, "sticky left-0 z-10 bg-muted")}>Osoba</th>
              <th scope="col" className={head}>Dzień programu</th>
              <th scope="col" className={head}>Dni zaliczone</th>
              <th scope="col" className={head}>Rozmowy / dzień</th>
              <th scope="col" className={head}>Odebrane</th>
              <th scope="col" className={head}>Pełne profile</th>
              <th scope="col" className={head}>Przekazani → w procesie</th>
              <th scope="col" className={head}>Próbka jakości</th>
              <th scope="col" className={head}>Stan</th>
              <th scope="col" className={head}>
                <span className="sr-only">Akcje</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {overview.trainees.map((row) => {
              const state = traineeState(row);
              const days = daysCompletedLabel(row);
              return [
                <tr key={row.user_id} className="border-t border-border">
                  <th scope="row" className={cn(cell, "sticky left-0 z-10 bg-card text-left font-semibold")}>
                    {row.name}
                    {!row.is_active ? (
                      <span className="ml-1 text-xs font-normal text-muted-foreground">(konto wyłączone)</span>
                    ) : null}
                  </th>
                  <td className={cell}>
                    {row.program ? `${row.program.day} / ${row.program.total_days}` : "—"}
                  </td>
                  <td className={cell}>
                    {days.main}{" "}
                    {days.pct ? <span className="text-xs text-muted-foreground">{days.pct}</span> : null}
                  </td>
                  <td className={cell}>
                    {row.calls_per_day == null ? "—" : Math.round(row.calls_per_day)}
                  </td>
                  <td className={cell}>
                    {row.flag_low_answer ? (
                      <span className="inline-flex items-center gap-1 font-semibold text-warning-muted-foreground">
                        <AlertTriangle className="h-4 w-4" aria-hidden />
                        {pctLabel(row.answered_pct)}
                        <span className="text-xs font-normal">(nisko)</span>
                      </span>
                    ) : (
                      pctLabel(row.answered_pct)
                    )}
                  </td>
                  <td className={cell}>{pctLabel(row.complete_profiles_pct)}</td>
                  <td className={cell}>
                    {row.handed_over === 0 ? "0" : `${row.handed_over} → ${row.handed_in_process}`}
                  </td>
                  <td className={cell}>{qualityLabel(row.quality)}</td>
                  <td className={cell}>
                    <span className={cn("inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", STATE_CLASS[state])}>
                      {TRAINEE_STATE_LABEL[state]}
                    </span>
                  </td>
                  <td className={cn(cell, "text-right")}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label={`Więcej: ${row.name}`}>
                          <MoreHorizontal className="h-4 w-4" aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => onEdit(row)}>Edytuj program</DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => onSample(row)}>Otwórz próbkę jakości</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>,
                row.flag_low_answer ? (
                  <tr key={`${row.user_id}-note`} className="bg-warning-muted/40">
                    <td colSpan={10} className="px-3 py-2 text-sm text-foreground">
                      {lowAnswerNote(row, overview.team_answered_pct)}
                    </td>
                  </tr>
                ) : null,
              ];
            })}
          </tbody>
        </table>
      </div>
      {overview.trainees.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          Nie ma jeszcze praktykantów. Nadaj osobie rolę „Praktykant” w Ustawieniach → Osoby i role.
        </p>
      ) : null}
    </section>
  );
}

// ── Panel ────────────────────────────────────────────────────────────────────

/** Panel „Praktykanci” (makieta „PanelHoR”) — Head of Recruitment i admin. */
export function TraineesPanel() {
  const overview = useTraineeOverview();
  const extend = useTraineeDecision();
  const [editRow, setEditRow] = useState<TraineeOverviewRow | null>(null);
  const [sampleRow, setSampleRow] = useState<TraineeOverviewRow | null>(null);
  const [pending, setPending] = useState<PendingDecision | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [extendError, setExtendError] = useState<string | null>(null);

  if (overview.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać panelu praktykantów. Dane istnieją — spróbuj ponownie."
        onRetry={() => overview.refetch()}
      />
    );
  }
  if (!overview.isSuccess) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground" role="status">
        Wczytuję panel praktykantów…
      </p>
    );
  }

  const data = overview.data;
  const due = data.trainees.filter((row) => row.program?.decision_due);
  const workdays = poolWorkdays(data.pool, data.trainees);
  const activeCount = data.trainees.filter(
    (r) => r.is_active && r.program && traineeState(r) !== "ended",
  ).length;
  const sampleCandidates = data.trainees.filter((r) => r.is_active && r.quality.checked > 0);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <PageHeader
        title="Praktykanci"
        description="Nowe osoby przez pierwsze dni programu dzwonią tylko do kandydatów z listy. Norma: wszystkie pozycje z listy zamknięte każdego dnia."
        actions={
          <Button asChild variant="outline">
            <Link href="/settings/trainee-rules">
              Reguły listy
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </Button>
        }
      />

      {message ? (
        <p role="status" className="rounded-lg border border-success/20 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
          {message}
        </p>
      ) : null}
      {extendError ? (
        <p role="alert" className="rounded-lg border border-destructive/20 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground">
          {extendError}
        </p>
      ) : null}

      {due.map((row) => (
        <DecisionBanner
          key={row.user_id}
          row={row}
          extending={extend.isPending && extend.variables?.userId === row.user_id}
          onPromote={(role) => setPending({ kind: "promote", row, role })}
          onEnd={() => setPending({ kind: "end", row })}
          onExtend={() => {
            setExtendError(null);
            extend.mutate(
              { userId: row.user_id, body: { action: "extend", extend_days: 20 } },
              {
                onSuccess: () => setMessage(`Program ${row.name} przedłużony o 20 dni roboczych.`),
                onError: (err) =>
                  setExtendError(apiErrorMessage(err, "Nie udało się przedłużyć programu.")),
              },
            );
          }}
        />
      ))}

      <TraineesTable overview={data} onEdit={setEditRow} onSample={setSampleRow} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold text-foreground">Pula do dzwonienia</h2>
          <span className="text-2xl font-bold tabular-nums text-foreground">
            {NUMBER.format(data.pool.size)} osób
          </span>
          <span className="text-sm text-muted-foreground">
            spełnia dziś reguły listy, {NUMBER.format(data.pool.open_fit)} z nich pasuje do
            otwartych rekrutacji.
            {workdays != null
              ? ` Przy ${activeCount} ${activeCount === 1 ? "praktykancie" : "praktykantach"} wystarczy na ok. ${workdays} dni roboczych, zanim zacznie się odnawiać.`
              : " Dziś nikt nie dzwoni z listy."}
          </span>
          {data.pool.by_category.length > 0 ? (
            <ul className="mt-1 space-y-1 text-sm">
              {data.pool.by_category.map((c) => (
                <li key={c.name} className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{c.name}</span>
                  <span className="tabular-nums text-foreground">{NUMBER.format(c.count)}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <Link
            href="/settings/trainee-rules"
            className="mt-auto inline-flex min-h-10 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Zmień reguły
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </section>

        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold text-foreground">Co dały telefony w tym miesiącu</h2>
          <dl className="space-y-2 text-sm">
            {(
              [
                ["Zweryfikowane stawki", data.month.verified_rates],
                ["Przekazani rekruterom", data.month.handed_over],
                ["…z nich w procesie", data.month.in_process],
              ] as Array<[string, number]>
            ).map(([label, value]) => (
              <div key={label} className="flex justify-between gap-2">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-semibold tabular-nums text-foreground">{NUMBER.format(value)}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold text-foreground">Próbka jakości</h2>
          <span className="text-sm text-muted-foreground">
            Co tydzień 5 losowych rozmów każdej osoby. Zadzwoń do kandydata i potwierdź, że dane
            w profilu się zgadzają. Nie mamy nagrań rozmów — to jedyna kontrola.
          </span>
          <div className="mt-auto flex flex-wrap gap-2">
            {(sampleCandidates.length ? sampleCandidates : data.trainees.filter((r) => r.is_active)).map((row) => (
              <Button key={row.user_id} variant="outline" className="min-h-10" onClick={() => setSampleRow(row)}>
                Otwórz próbkę: {row.name}
              </Button>
            ))}
          </div>
        </section>
      </div>

      <ProgramEditDialog row={editRow} onClose={() => setEditRow(null)} />
      <QualitySampleDialog
        userId={sampleRow?.user_id ?? null}
        name={sampleRow?.name ?? ""}
        onClose={() => setSampleRow(null)}
      />
      <DecisionDialog
        pending={pending}
        onClose={() => setPending(null)}
        onDone={(text) => {
          setPending(null);
          setMessage(text);
        }}
      />
    </div>
  );
}
