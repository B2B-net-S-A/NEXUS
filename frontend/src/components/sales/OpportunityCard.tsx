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
  useCreateActivity,
  useMoveOpportunity,
  useOpportunity,
  usePipelines,
  useSalesCompany,
  useSalesContacts,
  type CallOutcome,
  type OpportunityDetail,
  type DecisionMapEntry,
  type SalesContact,
  type Stage,
} from "@/lib/api/sales";
import { useOpportunityHandoff } from "@/lib/api/sales-handoffs";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

import { CallLogPanel } from "./CallLogPanel";
import { ChangeOwnerDialog, dueAtMorning, NextStepDialog, plusDays, type CallPerson } from "./CallLogDialogs";
import { FilesSection } from "./FilesSection";
import { formatDealAmount } from "./format";
import { LinkClientDialog } from "./LinkClientDialog";
import { SalesSelect } from "./SalesSelect";
import { OpportunityContacts } from "./OpportunityContacts";
import { BookMeetingDialog } from "./handoff/BookMeetingForm";
import { OpportunityHandoff } from "./handoff/OpportunityHandoff";
import { OpportunityFormDialog } from "./OpportunityFormDialog";
import { OpportunityHistory } from "./OpportunityHistory";
import { SalesShell } from "./SalesShell";
import { OpportunityStepBar } from "./OpportunityStepBar";
import { OpportunityTimelineCard } from "./OpportunityTimeline";
import { PurchasingProcessPanel } from "./PurchasingProcessPanel";
import { callQueue, outcomePreset } from "./step";
import { TalkingPoints } from "./signals/TalkingPoints";
import { WhoWeKnowPanel } from "./WhoWeKnowPanel";
import { SalesMotionPanel } from "./SalesMotionPanel";

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
      {opportunity.margin_pct && <Row label="Marża">{`${Number(opportunity.margin_pct)}%`}</Row>}
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

function personLabel(name: string, role?: string | null): string {
  const label = role ? `${name}, ${role}` : name;
  return label.length > 44 ? `${label.slice(0, 43).trimEnd()}…` : label;
}

/** Kogo można wybrać w zapisie rozmowy: mapa, kontakty szansy, reszta firmy, bez sprzeciwów. */
function callPeople(
  data: OpportunityDetail | undefined,
  map: readonly DecisionMapEntry[],
  company: readonly SalesContact[],
): CallPerson[] {
  if (!data) return [];
  const taken = new Set(map.map((entry) => entry.nexus_contact_id).filter(Boolean));
  const fromMap: CallPerson[] = map
    .filter((entry) => !entry.do_not_contact)
    .map((entry) => ({
      value: `map:${entry.key}`,
      label: personLabel(entry.name, entry.role_in_company),
      name: entry.name,
      person_key: entry.key,
    }));
  const contacts = [...data.contacts, ...company].filter((contact) => {
    if (taken.has(contact.id) || contact.do_not_contact_at) return false;
    taken.add(contact.id);
    return true;
  });
  return [
    ...fromMap,
    ...contacts.map((contact) => ({
      value: `contact:${contact.id}`,
      label: personLabel(contact.full_name, contact.title),
      name: contact.full_name,
      contact_id: contact.id,
    })),
  ];
}

interface OpportunityCardProps {
  opportunityId: number;
}

function cardDescription({ stage, value, currency }: OpportunityDetail): string {
  return Number(value ?? 0) > 0 ? `${stage.name} · ${formatDealAmount(value, currency)}` : stage.name;
}

function cardTitle({ company, title }: OpportunityDetail): string {
  return title.toLowerCase().startsWith(company.name.toLowerCase()) ? title : `${company.name} · ${title}`;
}

/** Etapy, z których szansę oddaje się prowadzącemu formularzem „Umów spotkanie”. */
const HANDOFF_STAGES = ["lead", "qualifying-meeting"];

/**
 * Makieta 11.11.2026: etap jako pasek pod paskiem kroku, zawsze widoczny. Klik w etap to `/move`
 * (jak przeciągnięcie na tablicy); zamknięcie zostaje przy „Wygrana” / „Przegrana”.
 */
function StageStrip({
  stages,
  current,
  disabled,
  onPick,
}: {
  stages: Stage[];
  current: Stage;
  disabled: boolean;
  onPick: (stage: Stage) => void;
}) {
  const open = stages.filter((stage) => stage.outcome === "open");
  const index = open.findIndex((stage) => stage.id === current.id);
  return (
    <div role="group" aria-label="Etap szansy" className="flex overflow-hidden rounded-lg border border-border bg-card">
      {open.map((stage, position) => {
        const active = stage.id === current.id;
        const passed = index >= 0 && position < index;
        return (
          <button
            key={stage.id}
            type="button"
            disabled={disabled || active}
            aria-current={active ? "step" : undefined}
            onClick={() => onPick(stage)}
            className={`min-w-0 flex-1 truncate border-r border-border px-2 py-1.5 text-xs last:border-r-0 ${
              active
                ? "bg-primary font-semibold text-primary-foreground"
                : passed
                  ? "bg-primary/10 text-foreground hover:bg-primary/20"
                  : "text-muted-foreground hover:bg-muted"
            }`}
            title={active ? `Obecny etap: ${stage.name}` : `Przenieś na „${stage.name}”`}
          >
            {passed && "✓ "}
            {stage.name}
          </button>
        );
      })}
    </div>
  );
}

/** Karta szansy w kolejności pracy: krok i zapis rozmowy na górze, oś firmy i szansy, potem reszta. */
export function OpportunityCard({ opportunityId }: OpportunityCardProps) {
  const opportunity = useOpportunity(opportunityId);
  const pipelines = usePipelines();
  const move = useMoveOpportunity();
  const createStep = useCreateActivity();
  const archive = useArchiveOpportunity(opportunityId);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [losingStage, setLosingStage] = useState<Stage | null>(null);
  const [editing, setEditing] = useState(false);
  const [linking, setLinking] = useState(false);
  const [reason, setReason] = useState("");
  const [logPerson, setLogPerson] = useState<string | null>(null);
  const [afterCall, setAfterCall] = useState<{ outcome: Exclude<CallOutcome, "do_not_contact">; person: string | null } | null>(null);
  const [planning, setPlanning] = useState(false);
  const [changingOwner, setChangingOwner] = useState(false);
  const [booking, setBooking] = useState(false);
  const [reached, setReached] = useState<readonly string[]>([]);
  const data = opportunity.data;
  const company = useSalesCompany(data?.company.id ?? 0);
  const logOpen = logPerson !== null;
  const companyContacts = useSalesContacts(data?.company.id ?? null, "", logOpen);
  const needsClientLink = data?.status === "won" && company.isSuccess && !company.data.client;
  const stages: Stage[] =
    pipelines.data?.find((pipeline) => pipeline.id === data?.pipeline_id)?.stages ?? [];
  const wonStage = stages.find((stage) => stage.outcome === "won");
  const lostStage = stages.find((stage) => stage.outcome === "lost" && stage.key === "lost") ??
    stages.find((stage) => stage.outcome === "lost");

  const map = data?.atlas_motion?.it_factory?.decision_map ?? [];
  const queue = callQueue(map).filter((entry) => !reached.includes(entry.key));
  const people = callPeople(data, map, companyContacts.data?.items ?? []);
  const openLog = (value?: string) => setLogPerson(value ?? (queue[0] ? `map:${queue[0].key}` : (people[0]?.value ?? "")));

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

  const canChangeOwner = data?.owner == null || data.owner.id === user?.id || hasRole(user, "admin");
  // Własny lead albo spotkanie bez przekazania: opiekun oddaje je prowadzącemu jednym formularzem.
  const handoff = useOpportunityHandoff(opportunityId);
  const canBook =
    canEdit &&
    canChangeOwner &&
    data?.status === "open" &&
    !data.archived_at &&
    HANDOFF_STAGES.includes(data.stage.key) &&
    pipelines.data?.find((pipeline) => pipeline.id === data.pipeline_id)?.key === "sales" &&
    handoff.isSuccess &&
    (handoff.data === null || handoff.data.verdict !== null);
  const contactsPanel = data ? (
    <OpportunityContacts
      opportunity={data}
      canEdit={canEdit}
      onCall={canEdit ? (contact) => openLog(`contact:${contact.id}`) : undefined}
    />
  ) : null;

  return (
    <SalesShell
      hideNav
      title={data ? cardTitle(data) : "Szansa"}
      description={data ? cardDescription(data) : undefined}
      actions={
        data && canEdit ? (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="quiet" onClick={() => void onArchive()}>
              {data.archived_at ? "Przywróć" : "Archiwizuj"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              Edytuj
            </Button>
            {canBook && (
              <Button size="sm" variant="outline" onClick={() => setBooking(true)}>
                Umów spotkanie
              </Button>
            )}
            {data.status === "open" && lostStage && (
              <Button size="sm" variant="outline" onClick={() => setLosingStage(lostStage)}>
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
        {/* Zapis rozmowy mieszka w przyklejonym obszarze, żeby był pod ręką także po przewinięciu. */}
        {data.status === "open" && (
          <div className="sticky top-0 z-20 space-y-2 bg-background">
            <OpportunityStepBar
              opportunity={data}
              queue={queue}
              canEdit={canEdit}
              canChangeOwner={canChangeOwner}
              onPlan={() => setPlanning(true)}
              onLog={() => openLog()}
              onOwner={() => setChangingOwner(true)}
            />
            {canEdit && stages.length > 0 && (
              <StageStrip
                stages={stages}
                current={data.stage}
                disabled={move.isPending}
                onPick={(target) => (target.outcome === "lost" ? setLosingStage(target) : moveTo(target.id))}
              />
            )}
            {logOpen && (
              <CallLogPanel
                key={logPerson}
                opportunityId={data.id}
                people={people}
                initialPerson={logPerson}
                onSaved={(outcome, person) => {
                  setLogPerson(null);
                  if (outcome === "do_not_contact") {
                    showSuccess("Zapisano sprzeciw przy tej osobie.");
                    return;
                  }
                  if (outcome !== "no_answer" && person?.person_key) {
                    const key = person.person_key;
                    setReached((current) => [...current, key]);
                  }
                  // Makieta 11.11: krok z podpowiedzi wyniku zapisuje się sam, bez okna „Co dalej”.
                  const preset = outcomePreset(outcome);
                  createStep.mutate(
                    {
                      kind: "task",
                      subject: preset.what,
                      due_at: dueAtMorning(plusDays(preset.days)),
                      opportunity_id: data.id,
                      company_id: null,
                    },
                    {
                      onSuccess: () => showSuccess(`Zapisano rozmowę. Krok: ${preset.what}, za ${preset.days} dni. Inny: „Zaplanuj”.`),
                      onError: () => setAfterCall({ outcome, person: person?.name ?? null }),
                    },
                  );
                }}
                onClose={() => setLogPerson(null)}
              />
            )}
          </div>
        )}
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_23.75rem]">
          <div className="min-w-0">
            <OpportunityTimelineCard opportunityId={data.id} canEdit={canEdit} />
          </div>
          <div className="min-w-0 space-y-4">
            <OpportunityHandoff opportunityId={data.id} canEdit={canEdit} />
            {/* Punkty do rozmowy z bota researchu; bez kanału albo bez punktów nic. */}
            <TalkingPoints companyId={data.company.id} className="rounded-lg border border-border bg-card px-3 py-2" />
            <SalesMotionPanel
              opportunityId={data.id}
              motion={data.atlas_motion}
              mapEnabled={data.decision_map_enabled}
              canEdit={canEdit}
              queue={queue}
              onCall={canEdit ? (entry) => openLog(`map:${entry.key}`) : undefined}
            />
            {map.length === 0 && contactsPanel}
            {/* Lista bywa długa (setki osób), a etap, pliki i historia są pod nią. */}
            <div className="max-h-[26rem] overflow-y-auto rounded-lg">
              <WhoWeKnowPanel companyId={data.company.id} companyName={data.company.name} />
            </div>
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
                        setLosingStage(target);
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
            {map.length > 0 && contactsPanel}
            <PurchasingProcessPanel motion={data.atlas_motion} />
            <FilesSection owner={{ opportunity_id: data.id }} />
            {data.description && (
              <Card className="p-4">
                <h2 className="text-base font-semibold text-foreground">Opis</h2>
                <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">{data.description}</p>
              </Card>
            )}
            <OpportunityHistory opportunityId={data.id} currency={data.currency} />
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
      {afterCall && data && (
        <NextStepDialog
          key={`${afterCall.outcome}-${afterCall.person}`}
          opportunityId={data.id}
          outcome={afterCall.outcome}
          personName={afterCall.person}
          onClose={() => setAfterCall(null)}
        />
      )}
      {planning && data && (
        <NextStepDialog opportunityId={data.id} outcome={null} personName={null} onClose={() => setPlanning(false)} />
      )}
      {changingOwner && data && (
        <ChangeOwnerDialog opportunityId={data.id} owner={data.owner} onClose={() => setChangingOwner(false)} />
      )}
      {editing && data && (
        <OpportunityFormDialog open={editing} onOpenChange={setEditing} opportunity={data} />
      )}
      {booking && data && (
        <BookMeetingDialog
          opportunity={{ id: data.id, name: data.title, company: data.company }}
          handoff={handoff.data ?? undefined}
          onClose={() => setBooking(false)}
        />
      )}
      {losingStage && (
        <AppModal
          open
          onOpenChange={(open) => {
            if (!open) setLosingStage(null);
          }}
          title={`Zamknij szansę: ${losingStage.name}`}
          size="sm"
          footer={
            <>
              <Button variant="outline" onClick={() => setLosingStage(null)}>
                Anuluj
              </Button>
              <Button
                loading={move.isPending}
                onClick={() => {
                  moveTo(losingStage.id, reason.trim() || undefined);
                  setLosingStage(null);
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
