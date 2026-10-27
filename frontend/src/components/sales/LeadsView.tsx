"use client";

import { useRouter } from "next/navigation";
import { Inbox, Plus } from "lucide-react";
import { useState } from "react";

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

function LeadRow({ lead, canEdit }: { lead: Lead; canEdit: boolean }) {
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
        <p className="text-xs text-muted-foreground">
          {LEAD_SOURCE_LABELS[lead.source]}
          {lead.signal_at ? ` · ${formatIsoDatePl(lead.signal_at)}` : ""}
          {lead.score ? ` · ocena ${lead.score}` : ""}
          {lead.dismissed_reason ? ` · ${lead.dismissed_reason}` : ""}
          {lead.url && (
            <>
              {" · "}
              <a href={lead.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
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
export function LeadsView() {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const [status, setStatus] = useState<LeadStatus>("new");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const leads = useLeads({ status, q });
  const items = leads.data?.items ?? [];
  const state = resolveViewState({
    isLoading: leads.isLoading,
    error: leads.error,
    isSuccess: leads.isSuccess,
    isEmpty: items.length === 0,
  });
  return (
    <div className="space-y-3">
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
            <LeadRow key={lead.id} lead={lead} canEdit={canEdit} />
          ))}
        </ul>
      )}
      {creating && <NewLeadDialog open={creating} onOpenChange={setCreating} />}
    </div>
  );
}
