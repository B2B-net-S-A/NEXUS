"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRightLeft } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  REDEPLOY_REASON_LABELS,
  REDEPLOY_STATUS_LABELS,
  useRedeployQueue,
  useUpdateRedeploy,
  type RedeployRow,
  type RedeployStatus,
} from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn, formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

function NoteDialog({ row, onClose }: { row: RedeployRow; onClose: () => void }) {
  const { showToast } = useToast();
  const update = useUpdateRedeploy();
  const [note, setNote] = useState(row.note ?? "");
  const [error, setError] = useState<string | null>(null);
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Notatka · ${row.candidate_name ?? "konsultant"}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                { itemId: row.id, note: note.trim() || null },
                {
                  onSuccess: () => {
                    showToast("Notatka zapisana", "success");
                    onClose();
                  },
                  onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać notatki.")),
                },
              )
            }
          >
            Zapisz
          </Button>
        </>
      }
    >
      <FormField label="Notatka" htmlFor="care-redeploy-note">
        <Textarea
          id="care-redeploy-note"
          rows={4}
          maxLength={4000}
          value={note}
          placeholder="np. rozmowa o projekcie u innego klienta umówiona na piątek"
          onChange={(event) => setNote(event.target.value)}
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

/** „Do przepięcia” — koniec projektu < 60 dni, chęć zmiany, ryzyko odejścia. */
export function RedeployPanel() {
  const { showToast } = useToast();
  const [state, setState] = useState<"active" | "closed">("active");
  const query = useRedeployQueue(state);
  const update = useUpdateRedeploy();
  const [noteFor, setNoteFor] = useState<RedeployRow | null>(null);
  const rows = query.data?.items ?? [];
  const view = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  const canEdit = query.data?.can_edit ?? false;

  const changeStatus = (row: RedeployRow, status: RedeployStatus) =>
    update.mutate(
      { itemId: row.id, status },
      {
        onSuccess: () => showToast("Status zmieniony", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić statusu."), "error"),
      },
    );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1" role="group" aria-label="Stan kolejki">
        {(
          [
            ["active", "Do zrobienia"],
            ["closed", "Zamknięte"],
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            size="sm"
            variant={state === value ? "secondary" : "ghost"}
            aria-pressed={state === value}
            onClick={() => setState(value)}
          >
            {label}
          </Button>
        ))}
      </div>
      {view === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : view === "forbidden" || view === "not_found" || view === "error" ? (
        <QueryStateNotice state={view} onRetry={() => query.refetch()} />
      ) : view === "empty" ? (
        <EmptyState
          icon={ArrowRightLeft}
          title={state === "active" ? "Nikt nie czeka na przepięcie" : "Brak zamkniętych wpisów"}
          description={
            state === "active"
              ? "Wpis powstaje sam, gdy projekt kończy się za mniej niż 60 dni albo rozmowa zgłosi chęć zmiany lub ryzyko odejścia."
              : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Powód</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Status</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Dalej</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={CALM_ROW}>
                  <td className="px-3 py-1.5">
                    <Link href={`/contracts/${row.contract_id}?tab=care`} className="font-medium hover:underline">
                      {row.candidate_name ?? "Konsultant"}
                    </Link>
                    <span className={CALM_SUBLINE}>
                      {row.owner ? `opiekun: ${row.owner.name}` : "bez opiekuna"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    {row.client_name}
                    {row.job_title ? <span className={CALM_SUBLINE}>{row.job_title}</span> : null}
                  </td>
                  <td className="px-3 py-1.5">
                    {REDEPLOY_REASON_LABELS[row.reason]}
                    <span className={CALM_SUBLINE}>
                      {row.due_on ? `koniec ${formatDate(row.due_on)}` : `od ${formatDate(row.created_at)}`}
                      {row.note ? ` · ${row.note}` : ""}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    {canEdit ? (
                      <Select
                        value={row.status}
                        disabled={update.isPending}
                        onValueChange={(value) => changeStatus(row, value as RedeployStatus)}
                      >
                        <SelectTrigger aria-label={`Status: ${row.candidate_name ?? "konsultant"}`} className="h-8 w-36">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(REDEPLOY_STATUS_LABELS) as RedeployStatus[]).map((key) => (
                            <SelectItem key={key} value={key}>
                              {REDEPLOY_STATUS_LABELS[key]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      REDEPLOY_STATUS_LABELS[row.status]
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
                      {row.candidate_id ? (
                        <Link href={`/candidates/${row.candidate_id}`} className="text-primary hover:underline">
                          Profil
                        </Link>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                      <Link href="/jobs" className="text-primary hover:underline">
                        Szukaj projektu
                      </Link>
                      <Link href="/jobs/new" className="text-primary hover:underline">
                        Nowa rekrutacja
                      </Link>
                      {canEdit ? (
                        <button type="button" className="text-primary hover:underline" onClick={() => setNoteFor(row)}>
                          Notatka
                        </button>
                      ) : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {noteFor ? <NoteDialog row={noteFor} onClose={() => setNoteFor(null)} /> : null}
    </div>
  );
}
