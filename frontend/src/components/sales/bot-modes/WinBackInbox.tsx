"use client";

import { RotateCcw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { EmptyState } from "@/components/ds/EmptyState";
import { FormRow } from "@/components/ds/FormGroup";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import {
  signalPayload,
  useCreateActivity,
  useLatestSignalRun,
  useLeads,
  useTakeOverLead,
  useUpdateLead,
  type Lead,
} from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { dueAtMorning, plusDays } from "../CallLogDialogs";
import { LeadDossier } from "../LeadDossier";
import { Block, BotConclusion, INBOX_LAYOUT, InboxRow, NotNow, Panel, RunLine, SourceLink } from "./kit";

export type WinBackFilter = "check" | "planned" | "rejected";

const FILTERS: { value: WinBackFilter; label: string }[] = [
  { value: "check", label: "Do sprawdzenia" },
  { value: "planned", label: "Zaplanowane" },
  { value: "rejected", label: "Odrzucone" },
];

const EMPTY: Record<WinBackFilter, string> = {
  check: "Nie ma przegranych, do których bot znalazł powód, żeby wrócić.",
  planned: "Nic jeszcze nie zaplanowano.",
  rejected: "Nic jeszcze nie odrzucono.",
};

const RETURN_IN_DAYS = 7;
const FORM_ROW = "sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3 sm:py-2";

/** Przegrana szansa zapisana przez serwer w `payload` leada „Warto wrócić”. */
export interface WinBackPayload {
  lostOpportunityId: number | null;
  lostTitle: string;
  lostReason: string;
  lostAt: string | null;
}

export function winBackPayload(lead: Pick<Lead, "payload">): WinBackPayload {
  const raw = lead.payload ?? {};
  const text = (key: string) => (typeof raw[key] === "string" ? (raw[key] as string) : "");
  const id = raw.lost_opportunity_id;
  return {
    lostOpportunityId: typeof id === "number" ? id : null,
    lostTitle: text("lost_opportunity_title"),
    lostReason: text("lost_reason"),
    lostAt: text("lost_at") || null,
  };
}

export function groupWinBack(leads: readonly Lead[]): Record<WinBackFilter, Lead[]> {
  return {
    check: leads.filter((lead) => lead.status === "new"),
    planned: leads.filter((lead) => lead.status === "contacted" || lead.status === "converted"),
    rejected: leads.filter((lead) => lead.status === "dismissed"),
  };
}

interface ReturnDialogProps {
  lead: Lead;
  /** Lead bez osoby w Sprzedaży: najpierw „Przejmij”, potem zadanie u klikającego. */
  takeOver: boolean;
  onClose: () => void;
}

/** Zwykłe zadanie przy firmie u osoby z leada; lead przechodzi na „W kontakcie”. */
function ReturnDialog({ lead, takeOver, onClose }: ReturnDialogProps) {
  const signal = signalPayload(lead);
  const take = useTakeOverLead();
  const create = useCreateActivity();
  const update = useUpdateLead();
  const { showError, showSuccess } = useToast();
  const [what, setWhat] = useState(`Powrót: ${lead.title}`.slice(0, 500));
  const [date, setDate] = useState(plusDays(RETURN_IN_DAYS));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!lead.company_id) return;
    setSaving(true);
    try {
      let assignee = lead.assignee?.id ?? null;
      if (takeOver) {
        assignee = (await take.mutateAsync(lead.id)).assignee?.id ?? null;
      }
      await create.mutateAsync({
        kind: "task",
        company_id: lead.company_id,
        subject: what.trim(),
        body: [signal.why_now, lead.url].filter(Boolean).join("\n") || null,
        due_at: dueAtMorning(date),
        assignee_user_id: assignee,
      });
      await update.mutateAsync({ id: lead.id, status: "contacted" });
      showSuccess(takeOver ? "Przejęto i zaplanowano powrót." : "Zaplanowano powrót.");
      onClose();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zaplanować powrotu."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title={takeOver ? "Przejmij i zaplanuj powrót" : "Zaplanuj powrót"}
      description={
        takeOver
          ? `${lead.company_name ?? "Firma"}: zadanie trafi do Ciebie.`
          : `${lead.company_name ?? "Firma"}: zadanie dla ${lead.assignee?.name ?? "opiekuna"}.`
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!what.trim() || !date || !lead.company_id} loading={saving} onClick={() => void save()}>
            Zapisz zadanie
          </Button>
        </>
      }
    >
      <FormRow label="Co zrobić" htmlFor="sales-winback-what" className={FORM_ROW}>
        <Input id="sales-winback-what" value={what} maxLength={500} onChange={(event) => setWhat(event.target.value)} />
      </FormRow>
      <FormRow label="Kiedy" htmlFor="sales-winback-date" className={FORM_ROW}>
        <Input
          id="sales-winback-date"
          type="date"
          value={date}
          min={plusDays(0)}
          onChange={(event) => setDate(event.target.value)}
        />
      </FormRow>
    </AppModal>
  );
}

function WinBackActions({ lead, reasons }: { lead: Lead; reasons?: readonly string[] }) {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const update = useUpdateLead();
  const { showError, showSuccess } = useToast();
  const [planning, setPlanning] = useState(false);
  if (!canEdit) return null;
  if (lead.status === "dismissed") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Odrzucone{lead.dismissed_reason ? `: ${lead.dismissed_reason}` : ""}</span>
        <Button
          size="sm"
          variant="quiet"
          loading={update.isPending}
          onClick={() =>
            update.mutate(
              { id: lead.id, status: "new" },
              { onError: (error) => showError(apiErrorMessage(error, "Nie udało się przywrócić.")) },
            )
          }
        >
          Przywróć
        </Button>
      </div>
    );
  }
  if (lead.status !== "new") {
    return (
      <p className="text-xs text-muted-foreground">
        Powrót zaplanowany{lead.assignee ? ` u ${lead.assignee.name}` : ""}. Zadanie jest na liście Zadania.
      </p>
    );
  }
  const takeOver = !lead.assignee_in_sales;
  return (
    <div className="flex flex-wrap gap-2" data-tour="sales.leads.winback.actions">
      <Button size="sm" onClick={() => setPlanning(true)} disabled={!lead.company_id}>
        {takeOver ? "Przejmij i zaplanuj" : "Zaplanuj powrót"}
      </Button>
      <NotNow
        reasons={reasons}
        pending={update.isPending}
        onReject={(reason) =>
          update.mutate(
            { id: lead.id, status: "dismissed", dismissed_reason: reason },
            {
              onSuccess: () => showSuccess("Odrzucono. Powód trafi do bota przy następnym biegu."),
              onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać decyzji.")),
            },
          )
        }
      />
      {planning && <ReturnDialog lead={lead} takeOver={takeOver} onClose={() => setPlanning(false)} />}
    </div>
  );
}

function WinBackPanel({ lead, reasons }: { lead: Lead; reasons?: readonly string[] }) {
  const signal = signalPayload(lead);
  const lost = winBackPayload(lead);
  return (
    <Panel>
      <div className="space-y-0.5">
        <p className="text-xs text-muted-foreground">Przegrana szansa</p>
        {lost.lostOpportunityId ? (
          <Link
            href={`/sales/opportunities/${lost.lostOpportunityId}`}
            className="text-sm font-semibold text-foreground hover:underline"
          >
            {lead.company_name ?? "—"}
          </Link>
        ) : (
          <p className="text-sm font-semibold text-foreground">{lead.company_name ?? "—"}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {[lost.lostTitle, lost.lostAt ? `przegrana ${formatIsoDatePl(lost.lostAt)}` : null]
            .filter(Boolean)
            .join(" · ")}
          {lost.lostReason ? `, powód: „${lost.lostReason}”` : ""}
        </p>
      </div>
      <Block label="Co się zmieniło">
        <p className="text-sm text-foreground">{lead.title}</p>
        {lead.summary && <p className="text-xs text-muted-foreground">{lead.summary}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <SourceLink url={lead.url} />
          {signal.published && (
            <span className="text-xs text-muted-foreground">{formatIsoDatePl(signal.published)}</span>
          )}
        </div>
      </Block>
      <LeadDossier dossier={lead.dossier} />
      {signal.why_now && (
        <Block label={<BotConclusion>Dlaczego teraz</BotConclusion>}>
          <p className="text-xs text-muted-foreground">{signal.why_now}</p>
        </Block>
      )}
      <Block label="Kto wraca">
        <p className="text-xs text-muted-foreground">
          {lead.assignee && lead.assignee_in_sales
            ? lead.assignee.name
            : lead.assignee
              ? `${lead.assignee.name} nie pracuje już w Sprzedaży: przejmij, żeby zaplanować powrót.`
              : "Nikt ze Sprzedaży: przejmij, żeby zaplanować powrót."}
        </p>
      </Block>
      <WinBackActions lead={lead} reasons={reasons} />
    </Panel>
  );
}

/** G-E „Warto wrócić”: przegrane z powodem „wróć później” i nowa informacja z bota. */
export function WinBackInbox() {
  const [filter, setFilter] = useState<WinBackFilter>("check");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const latest = useLatestSignalRun("winback");
  const query = useLeads({ status: "new", source: "research", origin: "winback", all_statuses: true, limit: 500 });
  const groups = useMemo(() => groupWinBack(query.data?.items ?? []), [query.data]);
  const items = groups[filter];
  const selected = items.find((lead) => lead.id === selectedId) ?? items[0];
  const run = latest.data?.run ?? null;
  const reasons = latest.data?.reject_reasons?.length ? latest.data.reject_reasons : undefined;
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: items.length === 0,
  });

  return (
    <div className="space-y-2">
      <RunLine>
        {latest.isError ? (
          "Nie udało się pobrać raportu bota."
        ) : run ? (
          <>
            <span className="font-medium text-foreground">Warto wrócić, {formatIsoDatePl(run.started_at)}:</span>{" "}
            {run.status === "received"
              ? `bot sprawdził ${run.report.sent_firms ?? run.company_count} firm z przegraną w ostatnich 14 miesiącach, ${run.report.leads ?? 0} z nową informacją.`
              : run.status === "started"
                ? "bot jeszcze sprawdza firmy."
                : "bieg nie dostał raportu od bota."}
          </>
        ) : latest.isSuccess ? (
          "Bot sprawdza przegrane raz w miesiącu, w pierwszy poniedziałek. Pierwszego biegu jeszcze nie było."
        ) : null}
      </RunLine>
      <SegmentedRadio
        size="sm"
        label="Filtr: warto wrócić"
        options={FILTERS.map(({ value, label }) => ({
          value,
          label: query.isSuccess ? `${label} (${groups[value].length})` : label,
        }))}
        value={filter}
        onChange={setFilter}
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description="Nie udało się pobrać listy. Pozycje mogą istnieć, spróbuj ponownie za chwilę."
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className={INBOX_LAYOUT}>
          <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
            {state === "empty" ? (
              <EmptyState icon={RotateCcw} title="Pusto" description={EMPTY[filter]} />
            ) : (
              <ul className="divide-y divide-border">
                {items.map((lead) => {
                  const lost = winBackPayload(lead);
                  const signal = signalPayload(lead);
                  return (
                    <InboxRow
                      key={lead.id}
                      selected={lead.id === selected?.id}
                      onSelect={() => setSelectedId(lead.id)}
                      title={
                        <>
                          <span className="font-medium">{lead.company_name ?? "—"}</span>{" "}
                          <span className="text-muted-foreground">{lead.title}</span>
                        </>
                      }
                      sub={[
                        lost.lostAt ? `przegrana ${formatIsoDatePl(lost.lostAt)}` : null,
                        lost.lostReason ? `„${lost.lostReason}”` : null,
                        lead.assignee_in_sales && lead.assignee ? lead.assignee.name : "bez opiekuna w Sprzedaży",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      right={signal.published ? formatIsoDatePl(signal.published) : ""}
                    />
                  );
                })}
              </ul>
            )}
          </div>
          {selected && <WinBackPanel key={selected.id} lead={selected} reasons={reasons} />}
        </div>
      )}
    </div>
  );
}
