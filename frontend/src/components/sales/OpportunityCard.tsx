"use client";

import Link from "next/link";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  SERVICE_LINE_LABELS,
  useArchiveOpportunity,
  useMoveOpportunity,
  useOpportunity,
  usePipelines,
  useSalesCompany,
  type OpportunityDetail,
  type Stage,
} from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { ActivityTimeline } from "./ActivityTimeline";
import { FilesSection } from "./FilesSection";
import { formatDealAmount } from "./format";
import { LinkClientDialog } from "./LinkClientDialog";
import { SalesSelect } from "./SalesSelect";
import { OpportunityContacts } from "./OpportunityContacts";
import { OpportunityFormDialog } from "./OpportunityFormDialog";
import { SalesShell } from "./SalesShell";
import { WhoWeKnowPanel } from "./WhoWeKnowPanel";
import { SalesMotionPanel } from "./mockups/SalesMotionPanel";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right text-foreground">{children || "—"}</dd>
    </div>
  );
}

function Details({ opportunity }: { opportunity: OpportunityDetail }) {
  return (
    <dl className="divide-y divide-border">
      <Row label="Wartość">{formatDealAmount(opportunity.value, opportunity.currency)}</Row>
      <Row label="Prognoza ważona">
        {opportunity.weighted_value
          ? `${formatDealAmount(opportunity.weighted_value, opportunity.currency)} (${opportunity.probability}%)`
          : null}
      </Row>
      {opportunity.mrr_value && (
        <Row label="Miesięcznie">{formatDealAmount(opportunity.mrr_value, opportunity.currency)}</Row>
      )}
      <Row label="Model">
        {opportunity.service_line ? SERVICE_LINE_LABELS[opportunity.service_line] : null}
      </Row>
      <Row label="Okres umowy">
        {opportunity.contract_months ? `${opportunity.contract_months} mies.` : null}
      </Row>
      <Row label="Role">
        {opportunity.roles.length
          ? opportunity.roles.map((role) => `${role.count} × ${role.title}`).join(", ")
          : null}
      </Row>
      <Row label="Planowane zamknięcie">{formatIsoDatePl(opportunity.expected_close_date)}</Row>
      <Row label="Opiekun">{opportunity.owner?.name}</Row>
      <Row label="Zakwalifikowana">{formatIsoDatePl(opportunity.qualified_at)}</Row>
      {opportunity.lost_reason && <Row label="Powód przegranej">{opportunity.lost_reason}</Row>}
    </dl>
  );
}

interface OpportunityCardProps {
  opportunityId: number;
}

/** Karta szansy (M1): etap, wygrana/przegrana, „Kogo znamy”, kontakty, historia. */
export function OpportunityCard({ opportunityId }: OpportunityCardProps) {
  const opportunity = useOpportunity(opportunityId);
  const pipelines = usePipelines();
  const move = useMoveOpportunity();
  const archive = useArchiveOpportunity(opportunityId);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [losing, setLosing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [linking, setLinking] = useState(false);
  const [reason, setReason] = useState("");
  const data = opportunity.data;
  const company = useSalesCompany(data?.company.id ?? 0);
  const needsClientLink = data?.status === "won" && company.isSuccess && !company.data.client;
  const stages: Stage[] =
    pipelines.data?.find((pipeline) => pipeline.id === data?.pipeline_id)?.stages ?? [];
  const wonStage = stages.find((stage) => stage.outcome === "won");
  const lostStage = stages.find((stage) => stage.outcome === "lost" && stage.key === "lost") ??
    stages.find((stage) => stage.outcome === "lost");

  const state = resolveViewState({
    isLoading: opportunity.isLoading,
    error: opportunity.error,
    isSuccess: opportunity.isSuccess,
  });

  const moveTo = (stageId: number, lostReason?: string) => {
    move.mutate(
      { id: opportunityId, stage_id: stageId, lost_reason: lostReason },
      {
        onSuccess: (moved) => showSuccess(`Szansa jest teraz na etapie „${moved.stage.name}”.`),
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić etapu.")),
      },
    );
  };

  const onArchive = async () => {
    if (!data) return;
    const restoring = Boolean(data.archived_at);
    if (!restoring) {
      const ok = await askConfirm({
        title: "Zarchiwizować szansę?",
        description: "Zniknie z tablicy i listy. Możesz ją później przywrócić.",
        confirmLabel: "Archiwizuj",
        variant: "destructive",
      });
      if (!ok) return;
    }
    archive.mutate(restoring, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić szansy.")),
    });
  };

  return (
    <SalesShell
      hideNav
      title={data ? `${data.company.name} · ${data.title}` : "Szansa"}
      description={data ? `${data.stage.name} · ${formatDealAmount(data.value, data.currency)}` : undefined}
      actions={
        data && canEdit ? (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="quiet" onClick={() => void onArchive()}>
              {data.archived_at ? "Przywróć" : "Archiwizuj"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              Edytuj
            </Button>
            {data.status === "open" && lostStage && (
              <Button size="sm" variant="outline" onClick={() => setLosing(true)}>
                Przegrana
              </Button>
            )}
            {data.status === "open" && wonStage && (
              <Button size="sm" onClick={() => moveTo(wonStage.id)} loading={move.isPending}>
                Wygrana
              </Button>
            )}
          </div>
        ) : null
      }
    >
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie szansy…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "not_found" ? "Nie ma takiej szansy." : undefined}
          onRetry={() => void opportunity.refetch()}
        />
      ) : data ? (
        <div className="space-y-4">
        {needsClientLink && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-success/40 bg-success/10 px-4 py-3 text-sm">
            <span>
              Wygrana. Powiąż {data.company.name} z klientem NEXUSA — wtedy szansa pokaże się
              w karcie klienta, a Delivery założy rekrutacje jak zwykle.
            </span>
            {canEdit && (
              <Button size="sm" variant="outline" onClick={() => setLinking(true)}>
                Powiąż z klientem
              </Button>
            )}
          </div>
        )}
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            <SalesMotionPanel opportunityId={data.id} />
            <WhoWeKnowPanel companyId={data.company.id} companyName={data.company.name} />
            <ActivityTimeline opportunityId={data.id} mailCompanyId={data.company.id} />
          </div>
          <div className="space-y-4">
            <Card className="space-y-3 p-4">
              <div className="space-y-1">
                <Label htmlFor="sales-opp-stage">Etap</Label>
                {canEdit && stages.length > 0 ? (
                  <SalesSelect
                    id="sales-opp-stage"
                    value={String(data.stage.id)}
                    onValueChange={(value) => {
                      const target = stages.find((stage) => String(stage.id) === value);
                      if (!target || target.id === data.stage.id) return;
                      if (target.outcome === "lost") {
                        setLosing(true);
                        return;
                      }
                      moveTo(target.id);
                    }}
                    options={stages.map((stage) => ({ value: String(stage.id), label: stage.name }))}
                    disabled={move.isPending}
                  />
                ) : (
                  <p id="sales-opp-stage" className="text-sm">{data.stage.name}</p>
                )}
              </div>
              {data.status !== "open" && (
                <StatusDot tone={data.status === "won" ? "success" : "neutral"}>
                  {data.status === "won"
                    ? `Wygrana ${formatIsoDatePl(data.won_at)}`
                    : `Przegrana ${formatIsoDatePl(data.lost_at)}`}
                </StatusDot>
              )}
              <Details opportunity={data} />
              <p className="text-xs text-muted-foreground">
                Firma:{" "}
                <Link href={`/sales/companies/${data.company.id}`} className="text-primary hover:underline">
                  {data.company.name}
                </Link>
              </p>
            </Card>
            <OpportunityContacts opportunity={data} canEdit={canEdit} />
            <FilesSection owner={{ opportunity_id: data.id }} />
            {data.description && (
              <Card className="p-4">
                <h2 className="text-base font-semibold text-foreground">Opis</h2>
                <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">{data.description}</p>
              </Card>
            )}
          </div>
        </div>
        </div>
      ) : null}
      {linking && data && company.data && (
        <LinkClientDialog
          open={linking}
          onOpenChange={setLinking}
          company={data.company}
          current={company.data.client}
        />
      )}
      {editing && data && (
        <OpportunityFormDialog open={editing} onOpenChange={setEditing} opportunity={data} />
      )}
      {losing && lostStage && (
        <AppModal
          open={losing}
          onOpenChange={setLosing}
          title="Przegrana szansa"
          size="sm"
          footer={
            <>
              <Button variant="outline" onClick={() => setLosing(false)}>
                Anuluj
              </Button>
              <Button
                loading={move.isPending}
                onClick={() => {
                  moveTo(lostStage.id, reason.trim() || undefined);
                  setLosing(false);
                  setReason("");
                }}
              >
                Zapisz
              </Button>
            </>
          }
        >
          <Label htmlFor="sales-lost-reason">Powód (opcjonalnie)</Label>
          <Textarea
            id="sales-lost-reason"
            rows={3}
            value={reason}
            placeholder="np. wybrali konkurencję, wstrzymany budżet"
            onChange={(event) => setReason(event.target.value)}
          />
        </AppModal>
      )}
      {confirmDialog}
    </SalesShell>
  );
}
