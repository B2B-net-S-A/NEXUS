"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ACTIVITY_KIND_LABELS,
  useCompleteActivity,
  useCreateActivity,
  useDeleteActivity,
  useSalesActivities,
  type Activity,
  type ActivityKind,
} from "@/lib/api/sales";
import { formatDateTimePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { ActivityBody } from "./mockups/ActivityBody";

const COMPOSER_KINDS: ActivityKind[] = ["note", "call", "meeting", "email", "task"];

interface ActivityTimelineProps {
  companyId?: number;
  opportunityId?: number;
  /** MAKIETA: firma szansy — jej maile i spotkania w historii szansy. */
  mailCompanyId?: number;
}

/** Datetime z pola `datetime-local` (czas lokalny) jako ISO; puste → null. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function when(activity: Activity): string {
  if (activity.kind === "task") {
    if (activity.done_at) return `zrobione ${formatDateTimePl(activity.done_at)}`;
    return activity.due_at ? `termin ${formatDateTimePl(activity.due_at)}` : "bez terminu";
  }
  return formatDateTimePl(activity.occurred_at ?? activity.created_at);
}

/** Historia firmy albo szansy i szybki wpis: notatka, telefon, spotkanie, mail, zadanie. */
export function ActivityTimeline({ companyId, opportunityId, mailCompanyId }: ActivityTimelineProps) {
  const scope = opportunityId ? { opportunity_id: opportunityId } : { company_id: companyId };
  const activities = useSalesActivities(scope);
  const create = useCreateActivity();
  const complete = useCompleteActivity();
  const remove = useDeleteActivity();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const [kind, setKind] = useState<ActivityKind>("note");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [due, setDue] = useState("");

  // MAKIETA: na szansie dokładamy maile i spotkania firmy (w Atlasie: msgraph-* z firmy).
  const companyMail = useSalesActivities({ company_id: mailCompanyId ?? 0 });
  const [withCompanyMail, setWithCompanyMail] = useState(true);
  const mailItems = (mailCompanyId ? companyMail.data ?? [] : []).filter(
    (activity) => activity.opportunity === null && (activity.kind === "email" || activity.kind === "meeting"),
  );
  const items = [...(activities.data ?? []), ...(withCompanyMail ? mailItems : [])].sort((a, b) =>
    (b.occurred_at ?? b.created_at).localeCompare(a.occurred_at ?? a.created_at),
  );
  const state = resolveViewState({
    isLoading: activities.isLoading,
    error: activities.error,
    isSuccess: activities.isSuccess,
    isEmpty: items.length === 0,
  });

  const submit = () => {
    if (kind === "task" ? !subject.trim() : !(subject.trim() || body.trim())) {
      showError(kind === "task" ? "Wpisz, co jest do zrobienia." : "Wpisz temat albo treść.");
      return;
    }
    create.mutate(
      {
        kind,
        company_id: opportunityId ? null : (companyId ?? null),
        opportunity_id: opportunityId ?? null,
        subject: subject.trim() || null,
        body: body.trim() || null,
        due_at: kind === "task" ? localInputToIso(due) : null,
      },
      {
        onSuccess: () => {
          setSubject("");
          setBody("");
          setDue("");
          showSuccess(kind === "task" ? "Dodano zadanie." : "Zapisano wpis.");
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać wpisu.")),
      },
    );
  };

  const onDelete = async (activity: Activity) => {
    const ok = await askConfirm({
      title: "Usunąć ten wpis?",
      description: "Wpis zniknie z historii firmy i szansy.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(activity.id, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się usunąć wpisu.")),
    });
  };

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Aktywności</h2>
        {mailCompanyId ? (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={withCompanyMail}
              onChange={(event) => setWithCompanyMail(event.target.checked)}
            />
            Pokaż maile i spotkania firmy ({mailItems.length})
          </label>
        ) : null}
      </div>
      {canEdit && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <TabbedNav
            dense
            ariaLabel="Rodzaj wpisu"
            tabs={COMPOSER_KINDS.map((value) => ({ value, label: ACTIVITY_KIND_LABELS[value] }))}
            value={kind}
            onValueChange={(value) => setKind(value as ActivityKind)}
          />
          <Input
            aria-label={kind === "task" ? "Co jest do zrobienia" : "Temat"}
            placeholder={kind === "task" ? "Co jest do zrobienia?" : "Temat"}
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          />
          {kind === "task" ? (
            <Input
              aria-label="Termin"
              type="datetime-local"
              value={due}
              onChange={(event) => setDue(event.target.value)}
            />
          ) : (
            <Textarea
              aria-label="Treść"
              rows={3}
              placeholder="Co ustaliliście?"
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          )}
          <div className="flex justify-end">
            <Button size="sm" onClick={submit} loading={create.isPending}>
              Zapisz
            </Button>
          </div>
        </div>
      )}
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie historii…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void activities.refetch()} />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze żadnych wpisów.</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((activity) => (
            <li key={activity.id} className="group flex items-start justify-between gap-3 py-2">
              <div className="min-w-0 text-sm">
                <p className="text-foreground">
                  <span className="font-medium">{ACTIVITY_KIND_LABELS[activity.kind]}</span>
                  {activity.subject ? ` · ${activity.subject}` : ""}
                </p>
                {activity.body && <ActivityBody body={activity.body} markdown={activity.kind === "note"} />}
                {activity.opportunity === null && opportunityId && (
                  <p className="text-xs text-info">z historii firmy</p>
                )}
                <p className={`text-xs ${activity.overdue ? "text-destructive" : "text-muted-foreground"}`}>
                  {when(activity)}
                  {activity.author ? ` · ${activity.author.name}` : ""}
                  {!opportunityId && activity.opportunity && (
                    <>
                      {" · "}
                      <Link href={`/sales/opportunities/${activity.opportunity.id}`} className="text-primary hover:underline">
                        {activity.opportunity.name}
                      </Link>
                    </>
                  )}
                </p>
              </div>
              {canEdit && (
                <div className="flex shrink-0 gap-1 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100">
                  {activity.kind === "task" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        complete.mutate(
                          { id: activity.id, reopen: Boolean(activity.done_at) },
                          {
                            onError: (error) =>
                              showError(apiErrorMessage(error, "Nie udało się zmienić zadania.")),
                          },
                        )
                      }
                    >
                      {activity.done_at ? "Przywróć" : "Zrobione"}
                    </Button>
                  )}
                  {activity.author?.id === user?.id && (
                    <Button size="sm" variant="quiet" onClick={() => void onDelete(activity)}>
                      Usuń
                    </Button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {confirmDialog}
    </Card>
  );
}
