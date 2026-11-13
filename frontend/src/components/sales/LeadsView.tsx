"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Inbox, Plus } from "lucide-react";
import { useState, type ReactNode } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  LEAD_SOURCE_LABELS,
  LEAD_STATUS_LABELS,
  useConvertLead,
  useCreateLead,
  useLeads,
  useUpdateLead,
  type Lead,
  type LeadStatus,
} from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { NewFirmsInbox } from "./bot-modes/NewFirmsInbox";
import { LeadDossier, firstLeadOfCompany } from "./LeadDossier";
import { WinBackInbox } from "./bot-modes/WinBackInbox";
import { safeHref } from "./format";
import { ResearchImport } from "./research-import/ResearchImport";
import { SignalsInbox } from "./signals/SignalsInbox";

const STATUSES: LeadStatus[] = ["new", "contacted", "converted", "dismissed"];

function NewLeadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [summary, setSummary] = useState("");
  const [url, setUrl] = useState("");
  const create = useCreateLead();
  const { showError, showSuccess } = useToast();
  const save = () => {
    if (!title.trim() || !company.trim()) {
      showError("Podaj firmę i to, co się dzieje.");
      return;
    }
    create.mutate(
      { title: title.trim(), company_name: company.trim(), summary: summary.trim() || null, url: url.trim() || null },
      {
        onSuccess: () => {
          showSuccess("Dodano lead.");
          onOpenChange(false);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać leada.")),
      },
    );
  };
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Nowy lead"
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={save} loading={create.isPending}>
            Dodaj
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="sales-lead-company">Firma</Label>
          <Input id="sales-lead-company" value={company} onChange={(e) => setCompany(e.target.value)} autoFocus />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-lead-title">Co się dzieje</Label>
          <Input
            id="sales-lead-title"
            value={title}
            placeholder="np. budują zespół data w Krakowie"
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-lead-url">Link</Label>
          <Input id="sales-lead-url" value={url} onChange={(e) => setUrl(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-lead-summary">Szczegóły</Label>
          <Textarea id="sales-lead-summary" rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} />
        </div>
      </div>
    </AppModal>
  );
}

interface LeadRowProps {
  lead: Lead;
  canEdit: boolean;
  /** Teczka firmy tylko przy pierwszym leadzie tej firmy na liście. */
  showDossier: boolean;
}

function LeadRow({ lead, canEdit, showDossier }: LeadRowProps) {
  const router = useRouter();
  const convert = useConvertLead();
  const update = useUpdateLead();
  const { showError } = useToast();
  const onError = (error: unknown) => showError(apiErrorMessage(error, "Nie udało się zmienić leada."));
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0 text-sm">
        <p className="font-medium text-foreground">
          {lead.company_name ?? "—"} <span className="text-muted-foreground">· {lead.title}</span>
        </p>
        {lead.summary && <p className="line-clamp-2 text-muted-foreground">{lead.summary}</p>}
        {showDossier && <LeadDossier dossier={lead.dossier} />}
        <LeadPayloadLine payload={lead.payload} />
        <p className="text-xs text-muted-foreground">
          {/* Lead z „Oferta ogólna wysłana” w Dzwonieniu (13.11.2026): źródło `manual` bez migracji. */}
          {lead.payload?.origin === "calling" ? "Dzwonienie" : LEAD_SOURCE_LABELS[lead.source]}
          {lead.signal_at ? ` · ${formatIsoDatePl(lead.signal_at)}` : ""}
          {lead.score && lead.source !== "research" ? ` · ocena ${lead.score}` : ""}
          {lead.dismissed_reason ? ` · ${lead.dismissed_reason}` : ""}
          {safeHref(lead.url) && (
            <>
              {" · "}
              <a href={safeHref(lead.url)} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                źródło
              </a>
            </>
          )}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {lead.status === "converted" && lead.opportunity_id ? (
          <Button size="sm" variant="outline" onClick={() => router.push(`/sales/opportunities/${lead.opportunity_id}`)}>
            Otwórz szansę
          </Button>
        ) : canEdit ? (
          <>
            {lead.status !== "dismissed" && (
              <Button
                size="sm"
                variant="quiet"
                onClick={() => update.mutate({ id: lead.id, status: "dismissed", dismissed_reason: "To nie lead" }, { onError })}
              >
                To nie lead
              </Button>
            )}
            {lead.status === "new" && (
              <Button size="sm" variant="outline" onClick={() => update.mutate({ id: lead.id, status: "contacted" }, { onError })}>
                W kontakcie
              </Button>
            )}
            {lead.status === "dismissed" && (
              <Button size="sm" variant="outline" onClick={() => update.mutate({ id: lead.id, status: "new" }, { onError })}>
                Przywróć
              </Button>
            )}
            <Button
              size="sm"
              loading={convert.isPending}
              onClick={() =>
                convert.mutate(lead.id, {
                  onSuccess: (result) => router.push(`/sales/opportunities/${result.opportunity_id}`),
                  onError,
                })
              }
            >
              Utwórz szansę
            </Button>
          </>
        ) : null}
      </div>
    </li>
  );
}

/** Leady (M4): sygnały z importu Atlasa i wpisów ręcznych — bez skanu (decyzja 27.10.2026). */
/** Osoba i punktacja z Atlasa (LinkedIn), trigger dla sygnałów — wcześniej import je gubił. */
function LeadPayloadLine({ payload }: { payload: Record<string, unknown> | undefined }) {
  if (!payload) return null;
  const person = (payload.person ?? null) as { name?: string; title?: string; company?: string } | null;
  const breakdown = (payload.score_breakdown ?? null) as Record<string, unknown> | null;
  const parts = [
    person?.name ? [person.name, person.title].filter(Boolean).join(", ") : null,
    breakdown
      ? Object.entries(breakdown)
          .filter(([, value]) => typeof value === "number")
          .slice(0, 4)
          .map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`)
          .join(" · ")
      : null,
  ].filter(Boolean);
  if (!parts.length) return null;
  return <p className="text-xs text-muted-foreground">{parts.join(" — ")}</p>;
}

type LeadsMode = "signals" | "winback" | "new-firms" | "leads" | "research";

/**
 * Przy włączonym kanale sygnałów Leady otwierają się na skrzynce sygnałów (G1).
 * „Warto wrócić” (G-E) i „Nowe centra IT” (G-D) są widoczne przy włączonych zadaniach
 * bota. „Lista z researchu” (import osób do map Fabryk IT) jest dla kont z edycją Sprzedaży.
 */
export function LeadsView() {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  // `?osoby=<id>` z plakietki „Osoby od bota”: od razu przegląd tego wyniku.
  const botParam = Number(useSearchParams()?.get("osoby") ?? "");
  const botResultId = Number.isInteger(botParam) && botParam > 0 ? botParam : null;
  const [picked, setPicked] = useState<LeadsMode | null>(botResultId !== null ? "research" : null);
  const probe = useLeads({ status: "new", limit: 1 });
  const signalsOn = probe.data?.signals_enabled === true;
  const botTasksOn = probe.data?.bot_tasks_enabled === true;
  const options: { value: LeadsMode; label: ReactNode }[] = [
    ...(signalsOn ? [{ value: "signals" as const, label: "Sygnały bota" }] : []),
    ...(botTasksOn
      ? [
          { value: "winback" as const, label: <span data-tour="sales.leads.mode.winback">Warto wrócić</span> },
          { value: "new-firms" as const, label: <span data-tour="sales.leads.mode.new-firms">Nowe centra IT</span> },
        ]
      : []),
    { value: "leads", label: "Wszystkie leady" },
    ...(canEdit ? [{ value: "research" as const, label: "Lista z researchu" }] : []),
  ];
  const fallback: LeadsMode = signalsOn ? "signals" : "leads";
  const mode = picked && options.some((option) => option.value === picked) ? picked : fallback;
  const switcher =
    options.length > 1 ? (
      <div data-tour="sales.leads.mode">
        <SegmentedRadio size="sm" label="Widok leadów" options={options} value={mode} onChange={setPicked} />
      </div>
    ) : null;
  if (mode !== "leads") {
    return (
      <div className="space-y-3">
        {switcher}
        {mode === "signals" ? (
          <SignalsInbox />
        ) : mode === "winback" ? (
          <WinBackInbox />
        ) : mode === "new-firms" ? (
          <NewFirmsInbox />
        ) : (
          <ResearchImport botResultId={botResultId} />
        )}
      </div>
    );
  }
  return <LeadsList switcher={switcher} />;
}

function LeadsList({ switcher }: { switcher: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const [status, setStatus] = useState<LeadStatus>("new");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const leads = useLeads({ status, q });
  const items = leads.data?.items ?? [];
  const withDossier = firstLeadOfCompany(items);
  const state = resolveViewState({
    isLoading: leads.isLoading,
    error: leads.error,
    isSuccess: leads.isSuccess,
    isEmpty: items.length === 0,
  });
  return (
    <div className="space-y-3">
      {switcher}
      <FilterBar
        search={{ value: q, onChange: setQ, placeholder: "Szukaj firmy albo sygnału…", ariaLabel: "Szukaj leada" }}
        filters={
          <SegmentedRadio
            size="sm"
            label="Status leadów"
            options={STATUSES.map((value) => ({
              value,
              label: `${LEAD_STATUS_LABELS[value]}${leads.data ? ` (${leads.data.counts[value] ?? 0})` : ""}`,
            }))}
            value={status}
            onChange={setStatus}
          />
        }
        actions={
          canEdit ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="mr-1 h-4 w-4" aria-hidden /> Lead
            </Button>
          ) : null
        }
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie leadów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void leads.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={Inbox}
          title={status === "new" ? "Brak nowych leadów" : "Pusto"}
          description="Leady przychodzą z importu Atlasa albo dodajesz je ręcznie."
        />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {items.map((lead) => (
            <LeadRow key={lead.id} lead={lead} canEdit={canEdit} showDossier={withDossier.has(lead.id)} />
          ))}
        </ul>
      )}
      {creating && <NewLeadDialog open={creating} onOpenChange={setCreating} />}
    </div>
  );
}
