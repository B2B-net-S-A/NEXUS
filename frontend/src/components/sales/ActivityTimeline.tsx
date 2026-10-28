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
import { hasRole, useAuthStore } from "@/store/auth";

import { ActivityBody } from "./ActivityBody";
import { ActivityEditDialog } from "./ActivityEditDialog";

const COMPOSER_KINDS: ActivityKind[] = ["note", "call", "meeting", "email", "task"];
const PAGE = 100;

interface ActivityTimelineProps {
  companyId?: number;
  opportunityId?: number;
  /** Na szansie: pokaż też maile i spotkania jej firmy z Outlooka (jak Atlas). */
  withCompanyMail?: boolean;
}

/** Datetime z pola `datetime-local` (czas lokalny) jako ISO; puste → null. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function inDays(days: number, now = new Date()): string {
  const date = new Date(now);
  date.setDate(date.getDate() + days);
  date.setHours(9, 0, 0, 0);
  return date.toISOString();
}

export function followUpSteps(now = new Date()): { subject: string; due_at: string }[] {
  return [
    { subject: "Wyślij podsumowanie mailowe ze spotkania", due_at: inDays(0, now) },
    { subject: "Przygotuj ofertę", due_at: inDays(6, now) },
    { subject: "Umów drugie spotkanie", due_at: inDays(14, now) },
  ];
}

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
  const create = useCreateActivity();
  const complete = useCompleteActivity();
  const remove = useDeleteActivity();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const isAdmin = hasRole(user, "admin");
  const [kind, setKind] = useState<ActivityKind>("note");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [due, setDue] = useState("");
  // Po spotkaniu przy szansie: trzy następne kroki jak w Atlasie
  // (`meeting_followup_seeder.py`): podsumowanie mailem dziś, oferta za 7 dni,
  // drugie spotkanie za 14 dni.
  const [withFollowUps, setWithFollowUps] = useState(true);

  const items = activities.data ?? [];
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
        due_at: kind === "task" || kind === "call" ? localInputToIso(due) : null,
      },
      {
        onSuccess: () => {
          setSubject("");
          setBody("");
          setDue("");
          if (kind === "meeting" && opportunityId && withFollowUps) {
            for (const step of followUpSteps()) {
              create.mutate({ kind: "task", opportunity_id: opportunityId, company_id: null, ...step, body: null });
            }
            showSuccess("Zapisano spotkanie i trzy następne kroki w zadaniach.");
            return;
          }
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
          {(kind === "task" || kind === "call") && (
            <Input
              aria-label={kind === "call" ? "Termin telefonu (puste = już był)" : "Termin"}
              type="datetime-local"
              value={due}
              onChange={(event) => setDue(event.target.value)}
            />
          )}
          {kind !== "task" && (
            <Textarea
              aria-label="Treść"
              rows={3}
              placeholder="Co ustaliliście?"
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          )}
          <div className="flex flex-wrap items-center justify-end gap-3">
            {kind === "meeting" && opportunityId && (
              <label className="mr-auto flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={withFollowUps}
                  onChange={(event) => setWithFollowUps(event.target.checked)}
                />
                Dodaj następne kroki: podsumowanie mailem, oferta (7 dni), drugie spotkanie (14 dni)
              </label>
            )}
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
