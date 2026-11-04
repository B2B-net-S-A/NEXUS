"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCloseQualityTask,
  useMyReview,
  usePortalStatus,
  useQualityReport,
  type QualityTask,
} from "@/lib/api/portal-staff";

import { formatDay } from "./board-model";
import {
  answeredShare,
  averageLabel,
  formatWhen,
  percentLabel,
  takeLabel,
} from "./portal-tabs-model";
import { ReasonDialog } from "./ReasonDialog";

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}

/** Przegląd osoby ocenianej: zbiorcze liczby za zamknięty miesiąc, bez pojedynczych ocen. */
function MyReviewPanel() {
  const review = useMyReview();
  if (review.isLoading) return <p className="text-sm text-muted-foreground">Wczytujemy przegląd…</p>;
  if (review.isError || !review.data) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(review.error, "Nie udało się wczytać przeglądu.")}
        onRetry={() => review.refetch()}
      />
    );
  }
  const data = review.data;
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Mój przegląd: {data.month_label}</h3>
      {data.enough ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Kpi label="Ocena średnia" value={averageLabel(data.average)} />
          <Kpi label="Liczba ocen" value={String(data.rated ?? 0)} />
          <Kpi label="Załatwione" value={percentLabel(data.resolved_share)} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Za mało ocen w tym miesiącu: przegląd pokazujemy od {data.min_for_review} ocen, żeby nie dało się
          odczytać pojedynczej.
        </p>
      )}
    </section>
  );
}

function TaskRow({ task }: { task: QualityTask }) {
  const { showToast } = useToast();
  const close = useCloseQualityTask();
  const [asking, setAsking] = useState(false);
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3 text-sm">
      <div className="min-w-0">
        <p className="font-medium">
          {task.consultant ?? "Konsultant"} <span className="font-normal text-muted-foreground">→ {task.host ?? "—"}</span>
        </p>
        <p className="text-xs text-muted-foreground">
          {formatWhen(task.start_at)} · ocena {task.score}/5
          {task.resolved === false ? " · sprawa niezałatwiona" : ""}
        </p>
        {task.comment ? <p className="mt-1">„{task.comment}”</p> : null}
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="warning" size="sm">
          Oddzwoń do {formatDay(task.due_on)}
        </Badge>
        <Button size="sm" variant="outline" disabled={close.isPending} onClick={() => setAsking(true)}>
          Załatwione
        </Button>
      </div>
      {asking ? (
        <ReasonDialog
          title="Zamknąć zadanie po ocenie?"
          label="Co ustaliłeś(-aś) z konsultantem"
          confirmLabel="Zamknij zadanie"
          required={false}
          busy={close.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={(note) =>
            close.mutate(
              { id: task.id, note },
              {
                onSuccess: () => setAsking(false),
                onError: (error) =>
                  showToast(apiErrorMessage(error, "Nie udało się zamknąć zadania."), "error"),
              },
            )
          }
        />
      ) : null}
    </li>
  );
}

function LeadPanel() {
  const report = useQualityReport(true);
  if (report.isLoading) return <p className="text-sm text-muted-foreground">Wczytujemy jakość…</p>;
  if (report.isError || !report.data) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(report.error, "Nie udało się wczytać jakości.")}
        onRetry={() => report.refetch()}
      />
    );
  }
  const data = report.data;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi
          label={`Ocena średnia (${data.days} dni)`}
          value={averageLabel(data.average)}
          note={`${data.meetings} rozmów · oceniło ${answeredShare(data.rated, data.meetings)}`}
        />
        <Kpi label="Załatwione w rozmowie" value={percentLabel(data.resolved_share)} note="z ocen konsultantów" />
        <Kpi label="Zadania po ocenach 1–2" value={String(data.tasks.length)} note="oddzwonić w 24 h" />
      </div>
      <section className="rounded-xl border bg-card">
        <header className="border-b px-4 py-3">
          <h3 className="text-sm font-semibold">Do oddzwonienia</h3>
        </header>
        {data.tasks.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">Nie ma otwartych zadań.</p>
        ) : (
          <ul className="divide-y px-4">
            {data.tasks.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </ul>
        )}
      </section>
      <section className="overflow-x-auto rounded-xl border bg-card">
        <header className="border-b px-4 py-3">
          <h3 className="text-sm font-semibold">Jakość per osoba</h3>
        </header>
        {data.people.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">Nie ma jeszcze rozmów ani ocen.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b">
                <th className="px-4 py-2 font-medium">Osoba</th>
                <th className="py-2 font-medium">Rozmowy</th>
                <th className="py-2 font-medium">Ocena</th>
                <th className="py-2 font-medium">Oceniło</th>
                <th className="py-2 font-medium">Oceny 1–2</th>
                <th className="px-4 py-2 font-medium">Czas do „Biorę”</th>
              </tr>
            </thead>
            <tbody>
              {data.people.map((person) => (
                <tr key={person.user_id} className="border-b last:border-0">
                  <td className="px-4 py-2.5 font-medium">{person.name}</td>
                  <td className="py-2.5 tabular-nums">{person.meetings}</td>
                  <td className="py-2.5 tabular-nums">{averageLabel(person.average)}</td>
                  <td className="py-2.5 tabular-nums text-muted-foreground">
                    {answeredShare(person.rated, person.meetings)}
                  </td>
                  <td className="py-2.5">
                    <Badge variant={person.low >= 3 ? "danger" : "neutral"} size="sm">
                      {person.low}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{takeLabel(person.median_take_minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

/** Zakładka „Jakość”: kierownik widzi całość, każdy swój zbiorczy przegląd miesięczny. */
export function QualityTab() {
  const status = usePortalStatus();
  if (status.isLoading) return <p className="text-sm text-muted-foreground">Wczytujemy…</p>;
  if (status.isError || !status.data) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(status.error, "Nie udało się wczytać zakładki.")}
        onRetry={() => status.refetch()}
      />
    );
  }
  return (
    <div className="space-y-6">
      <MyReviewPanel />
      {status.data.viewer.is_lead ? <LeadPanel /> : null}
    </div>
  );
}
