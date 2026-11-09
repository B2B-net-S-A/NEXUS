"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ACTIVITY_KIND_LABELS,
  useCompleteActivity,
  useDeleteActivity,
  useOpportunityTimeline,
  type TimelineItem,
  type TimelineScope,
} from "@/lib/api/sales";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

import { ActivityBody } from "./ActivityBody";
import { ActivityComposer } from "./ActivityComposer";
import { ActivityEditDialog } from "./ActivityEditDialog";
import { isTodo } from "./ActivityTimeline";
import { MeetingClientMailDialog } from "./MeetingClientMailDialog";
import { MeetingTranscriptDialog } from "./MeetingTranscriptDialog";

const PAGE = 12;
const TITLE_CHARS = 240;

const SCOPE_LABEL: Record<TimelineScope, string> = {
  opportunity: "ta szansa",
  company: "firma",
  other_opportunity: "inna szansa",
};

const SOURCE_LABEL: Record<string, string> = {
  pipedrive_note: "z Pipedrive",
  pipedrive_activity: "z Pipedrive",
  atlas: "z Atlasa",
  "msgraph-mail": "z Outlooka",
  "msgraph-event": "z Outlooka",
  fireflies: "z Fireflies",
};

function kindLabel(item: TimelineItem): string {
  if (item.kind === "email" && item.direction === "in") return "Mail przychodzący";
  if (item.kind === "email" && item.direction === "out") return "Mail wychodzący";
  return ACTIVITY_KIND_LABELS[item.kind];
}

/** Jedna linia wpisu: bez znaczników Markdown i emoji z podsumowań Fireflies. */
export function entryTitle(item: Pick<TimelineItem, "subject" | "body">): string {
  return (item.subject || item.body || "")
    .replace(/[*#_`]+/g, "")
    .replace(/\p{Extended_Pictographic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, TITLE_CHARS);
}

function sourcesLabel(item: TimelineItem): string {
  return [...new Set(item.sources.map((source) => SOURCE_LABEL[source]).filter(Boolean))].join(" i ");
}

interface MeetingSummaryProps {
  item: TimelineItem;
  open: boolean;
  canEdit: boolean;
  onTranscript: (activityId: number) => void;
  onClientMail: (activityId: number) => void;
}

/** Spotkanie z transkryptem Teams: podsumowanie widać bez rozwijania wiersza. */
export function MeetingSummary({ item, open, canEdit, onTranscript, onClientMail }: MeetingSummaryProps) {
  const activityId = item.transcript_activity_id;
  if (!activityId) return null;
  return (
    <div className="mt-1 space-y-1 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm md:ml-[5.5rem]">
      {item.transcript_summary ? (
        <p className={open ? "whitespace-pre-line text-foreground" : "line-clamp-3 text-foreground"}>
          <span className="font-medium">Podsumowanie z Teams: </span>
          {item.transcript_summary}
        </p>
      ) : (
        <p className="text-muted-foreground">Transkrypt z Teams bez podsumowania.</p>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Button size="sm" variant="ghost" className="h-6 px-2" onClick={() => onTranscript(activityId)}>
          Transkrypt
        </Button>
        {canEdit && item.can_send_client_summary && (
          <Button size="sm" variant="outline" className="h-6 px-2" onClick={() => onClientMail(activityId)}>
            Podsumowanie dla klienta
          </Button>
        )}
        {item.client_mail_sent_at && (
          <span className="text-xs text-muted-foreground">
            wysłane klientowi {formatDateTimePl(item.client_mail_sent_at)}
          </span>
        )}
      </div>
    </div>
  );
}

interface RowProps {
  item: TimelineItem;
  canEdit: boolean;
  canManage: boolean;
  canDelete: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onTranscript: (activityId: number) => void;
  onClientMail: (activityId: number) => void;
}

function Row({
  item,
  canEdit,
  canManage,
  canDelete,
  onToggle,
  onEdit,
  onDelete,
  onTranscript,
  onClientMail,
}: RowProps) {
  const [open, setOpen] = useState(false);
  const todo = isTodo(item);
  const notDone = todo && !item.done_at;
  const title = entryTitle(item);
  return (
    <li className="py-2 text-sm">
      <div className="grid grid-cols-[4.75rem_minmax(0,1fr)_auto] items-start gap-3">
        <time className="pt-0.5 text-xs tabular-nums text-muted-foreground">
          {formatIsoDatePl(item.occurred_at ?? item.created_at)}
        </time>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="min-w-0 text-left hover:text-primary"
        >
          <span className={open ? "block" : "line-clamp-2"}>
            <span className="font-medium text-foreground">{kindLabel(item)}</span>
            {title && <span className="text-muted-foreground"> · {title}</span>}
            {notDone && (
              <span className={item.overdue ? "text-destructive" : "text-muted-foreground"}>
                {item.due_at ? ` · termin ${formatDateTimePl(item.due_at)}` : " · bez terminu"}
              </span>
            )}
          </span>
        </button>
        <span className="flex items-center gap-2">
          {canEdit && notDone && (
            <Button size="sm" variant="ghost" className="h-6 px-2" onClick={onToggle}>
              Zrobione
            </Button>
          )}
          <Badge
            variant={item.scope === "opportunity" ? "soft" : "outline"}
            size="sm"
            title={item.scope === "other_opportunity" ? item.opportunity?.name : undefined}
          >
            {SCOPE_LABEL[item.scope]}
          </Badge>
        </span>
      </div>
      <MeetingSummary
        item={item}
        open={open}
        canEdit={canEdit}
        onTranscript={onTranscript}
        onClientMail={onClientMail}
      />
      {open && (
        <div className="mt-1 space-y-1 pl-[5.5rem]">
          {item.body && <ActivityBody body={item.body} markdown={item.kind === "note"} />}
          <p className="text-xs text-muted-foreground">
            {[
              sourcesLabel(item),
              item.duration_minutes ? `${item.duration_minutes} min` : null,
              todo && item.done_at ? `zrobione ${formatDateTimePl(item.done_at)}` : null,
              item.author?.name,
            ]
              .filter(Boolean)
              .join(" · ")}
            {item.scope === "other_opportunity" && item.opportunity && (
              <>
                {" · "}
                <Link href={`/sales/opportunities/${item.opportunity.id}`} className="text-primary hover:underline">
                  {item.opportunity.name}
                </Link>
              </>
            )}
            {item.web_link && (
              <>
                {" · "}
                <a href={item.web_link} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  Otwórz w Outlooku
                </a>
              </>
            )}
          </p>
          {canEdit && (
            <div className="flex gap-1">
              {todo && item.done_at && (
                <Button size="sm" variant="ghost" onClick={onToggle}>
                  Przywróć
                </Button>
              )}
              {canManage && (
                <Button size="sm" variant="ghost" onClick={onEdit}>
                  Edytuj
                </Button>
              )}
              {canDelete && (
                <Button size="sm" variant="quiet" onClick={onDelete}>
                  Usuń
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

type Filter = "all" | TimelineScope;

interface OpportunityTimelineProps {
  opportunityId: number;
  canEdit: boolean;
}

/** Wspólna oś firmy i szansy: każdy wpis mówi, skąd jest, jedno zdarzenie w jednym wierszu. */
export function OpportunityTimelineCard({ opportunityId, canEdit }: OpportunityTimelineProps) {
  const timeline = useOpportunityTimeline(opportunityId);
  const complete = useCompleteActivity();
  const remove = useDeleteActivity();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError } = useToast();
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasRole(user, "admin") && hasPermission(user, "sales_edit");
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(PAGE);
  const [composing, setComposing] = useState(false);
  const [editing, setEditing] = useState<TimelineItem | null>(null);
  const [transcriptFor, setTranscriptFor] = useState<number | null>(null);
  const [mailFor, setMailFor] = useState<number | null>(null);

  const items = timeline.data?.items;
  const shown = useMemo(
    () => (items ?? []).filter((item) => filter === "all" || item.scope === filter),
    [items, filter],
  );
  const counts = timeline.data?.counts;
  const state = resolveViewState({
    isLoading: timeline.isLoading,
    error: timeline.error,
    isSuccess: timeline.isSuccess,
    isEmpty: (items ?? []).length === 0,
  });

  const onDelete = async (item: TimelineItem) => {
    const ok = await askConfirm({
      title: "Usunąć ten wpis?",
      description: "Wpis zniknie z historii firmy i szansy.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(item.id, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się usunąć wpisu.")),
    });
  };

  return (
    <Card className="space-y-1 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-base font-semibold text-foreground">Historia firmy i szansy</h2>
        {canEdit && (
          <Button size="sm" variant="outline" aria-expanded={composing} onClick={() => setComposing((value) => !value)}>
            {composing ? "Zwiń wpis" : "Dodaj wpis"}
          </Button>
        )}
        {counts && (
          <div className="w-full">
            <TabbedNav
              dense
              ariaLabel="Zakres historii"
              value={filter}
              onValueChange={(value) => {
                setFilter(value as Filter);
                setLimit(PAGE);
              }}
              tabs={[
                { value: "all", label: `Wszystko ${counts.all}` },
                { value: "opportunity", label: `Ta szansa ${counts.opportunity}` },
                { value: "company", label: `Firma ${counts.company}` },
                { value: "other_opportunity", label: `Inne szanse ${counts.other_opportunity}` },
              ]}
            />
          </div>
        )}
      </div>
      {composing && <ActivityComposer opportunityId={opportunityId} />}
      {state === "loading" ? (
        <p className="py-3 text-sm text-muted-foreground">Wczytywanie historii…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void timeline.refetch()} />
      ) : timeline.isSuccess && shown.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">Nie ma tu jeszcze żadnego wpisu.</p>
      ) : (
        <ul className="divide-y divide-border">
          {shown.slice(0, limit).map((item) => (
            <Row
              key={item.id}
              item={item}
              canEdit={canEdit}
              canManage={item.author?.id === user?.id || isAdmin}
              canDelete={item.author?.id === user?.id}
              onToggle={() =>
                complete.mutate(
                  { id: item.id, reopen: Boolean(item.done_at) },
                  { onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić zadania.")) },
                )
              }
              onEdit={() => setEditing(item)}
              onDelete={() => void onDelete(item)}
              onTranscript={setTranscriptFor}
              onClientMail={setMailFor}
            />
          ))}
        </ul>
      )}
      {shown.length > limit && (
        <div className="flex justify-center pt-1">
          <Button size="sm" variant="outline" onClick={() => setLimit((value) => value + PAGE)}>
            Pokaż starsze ({shown.length - limit})
          </Button>
        </div>
      )}
      {editing && <ActivityEditDialog activity={editing} onClose={() => setEditing(null)} />}
      {transcriptFor !== null && (
        <MeetingTranscriptDialog activityId={transcriptFor} onClose={() => setTranscriptFor(null)} />
      )}
      {mailFor !== null && (
        <MeetingClientMailDialog
          activityId={mailFor}
          opportunityId={opportunityId}
          onClose={() => setMailFor(null)}
        />
      )}
      {confirmDialog}
    </Card>
  );
}
