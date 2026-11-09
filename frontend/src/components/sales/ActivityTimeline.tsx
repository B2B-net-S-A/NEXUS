"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ACTIVITY_KIND_LABELS,
  useCompleteActivity,
  useDeleteActivity,
  useSalesActivities,
  type Activity,
} from "@/lib/api/sales";
import { formatDateTimePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

import { ActivityBody } from "./ActivityBody";
import { ActivityComposer } from "./ActivityComposer";
import { ActivityEditDialog } from "./ActivityEditDialog";

const PAGE = 100;

interface ActivityTimelineProps {
  companyId?: number;
  opportunityId?: number;
  /** Na szansie: pokaż też maile i spotkania jej firmy z Outlooka (jak Atlas). */
  withCompanyMail?: boolean;
}

export { followUpSteps, localInputToIso } from "./ActivityComposer";

/** Zadanie albo telefon z terminem — rzecz do zrobienia, nie sam wpis historii. */
export function isTodo(activity: Activity): boolean {
  return activity.kind === "task" || (activity.kind === "call" && Boolean(activity.due_at));
}

function when(activity: Activity): string {
  if (isTodo(activity)) {
    if (activity.done_at) return `zrobione ${formatDateTimePl(activity.done_at)}`;
    return activity.due_at ? `termin ${formatDateTimePl(activity.due_at)}` : "bez terminu";
  }
  return formatDateTimePl(activity.occurred_at ?? activity.created_at);
}

/** Historia firmy albo szansy i szybki wpis: notatka, telefon, spotkanie, mail, zadanie. */
export function ActivityTimeline({ companyId, opportunityId, withCompanyMail }: ActivityTimelineProps) {
  const [showCompanyMail, setShowCompanyMail] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  const scope = opportunityId
    ? { opportunity_id: opportunityId, with_company_mail: Boolean(withCompanyMail && showCompanyMail), limit }
    : { company_id: companyId, limit };
  const activities = useSalesActivities(scope);
  const [editing, setEditing] = useState<Activity | null>(null);
  const complete = useCompleteActivity();
  const remove = useDeleteActivity();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError } = useToast();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const isAdmin = hasRole(user, "admin");
  const items = activities.data ?? [];
  const state = resolveViewState({
    isLoading: activities.isLoading,
    error: activities.error,
    isSuccess: activities.isSuccess,
    isEmpty: items.length === 0,
  });

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
        {withCompanyMail ? (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={showCompanyMail}
              onChange={(event) => setShowCompanyMail(event.target.checked)}
            />
            Pokaż maile i spotkania firmy z Outlooka
          </label>
        ) : null}
      </div>
      {canEdit && <ActivityComposer companyId={companyId} opportunityId={opportunityId} />}
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
                {(activity.from_company || activity.direction || activity.duration_minutes || activity.web_link) && (
                  <p className="text-xs text-muted-foreground">
                    {[
                      activity.from_company ? "z historii firmy" : null,
                      activity.direction === "in" ? "przychodzący" : activity.direction === "out" ? "wychodzący" : null,
                      activity.duration_minutes ? `${activity.duration_minutes} min` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    {activity.web_link && (
                      <>
                        {" · "}
                        <a href={activity.web_link} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                          Otwórz w Outlooku
                        </a>
                      </>
                    )}
                  </p>
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
                  {isTodo(activity) && (
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
                  {(activity.author?.id === user?.id || isAdmin) && !activity.from_company && (
                    <Button size="sm" variant="ghost" onClick={() => setEditing(activity)}>
                      Edytuj
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
      {items.length >= limit && (
        <div className="flex justify-center">
          <Button size="sm" variant="outline" onClick={() => setLimit((value) => value + PAGE)}>
            Pokaż starsze
          </Button>
        </div>
      )}
      {editing && <ActivityEditDialog activity={editing} onClose={() => setEditing(null)} />}
      {confirmDialog}
    </Card>
  );
}
