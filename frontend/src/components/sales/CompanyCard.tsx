"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  COMPANY_STATUS_LABELS,
  LIFECYCLE_LABELS,
  TIER_LABELS,
  useArchiveSalesCompany,
  useOpportunities,
  useSalesCompany,
  type SalesCompany,
} from "@/lib/api/sales";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { ActivityTimeline } from "./ActivityTimeline";
import { CompanyFormDialog } from "./CompanyFormDialog";
import { ContactsSection } from "./ContactsSection";
import { formatDealAmount } from "./format";
import { OpportunityFormDialog } from "./OpportunityFormDialog";
import { SalesShell } from "./SalesShell";
import { WhoWeKnowPanel } from "./WhoWeKnowPanel";

type Tab = "overview" | "people" | "contacts" | "activities";
const TABS: { value: Tab; label: string }[] = [
  { value: "overview", label: "Przegląd" },
  { value: "people", label: "Kogo znamy" },
  { value: "contacts", label: "Kontakty" },
  { value: "activities", label: "Aktywności" },
];

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{children || "—"}</dd>
    </div>
  );
}

function CompanyFacts({ company }: { company: SalesCompany }) {
  return (
    <Card className="p-4">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Fact label="NIP">{company.nip}</Fact>
        <Fact label="Branża">{company.industry}</Fact>
        <Fact label="Miasto">{company.hq_city}</Fact>
        <Fact label="Wielkość">{company.tier ? TIER_LABELS[company.tier] : null}</Fact>
        <Fact label="Opiekun">{company.owner?.name}</Fact>
        <Fact label="Firma matka">
          {company.parent && (
            <Link href={`/sales/companies/${company.parent.id}`} className="text-primary hover:underline">
              {company.parent.name}
            </Link>
          )}
        </Fact>
        <Fact label="Klient w NEXUSIE">
          {company.client && (
            <Link href={`/clients/${company.client.id}`} className="text-primary hover:underline">
              {company.client.name}
            </Link>
          )}
        </Fact>
        <Fact label="Strona">
          {company.website_url && (
            <a href={company.website_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
              {company.domain ?? company.website_url}
            </a>
          )}
        </Fact>
      </dl>
      {company.description && (
        <p className="mt-3 whitespace-pre-line text-sm text-muted-foreground">{company.description}</p>
      )}
    </Card>
  );
}

function CompanyOpportunities({ companyId }: { companyId: number }) {
  const opportunities = useOpportunities({ company_id: companyId });
  const items = opportunities.data?.items ?? [];
  const state = resolveViewState({
    isLoading: opportunities.isLoading,
    error: opportunities.error,
    isSuccess: opportunities.isSuccess,
    isEmpty: items.length === 0,
  });
  return (
    <Card className="space-y-2 p-4">
      <h2 className="text-base font-semibold text-foreground">Szanse</h2>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie szans…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void opportunities.refetch()} />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Ta firma nie ma jeszcze szans.</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <Link href={`/sales/opportunities/${item.id}`} className="font-medium text-foreground hover:underline">
                {item.title}
              </Link>
              <span className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>{item.stage.name}</span>
                <span className="tabular-nums text-foreground">{formatDealAmount(item.value, item.currency)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

interface CompanyCardProps {
  companyId: number;
}

/** Karta firmy sprzedaży (M3): przegląd z szansami, „Kogo znamy”, kontakty, historia. */
export function CompanyCard({ companyId }: CompanyCardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const company = useSalesCompany(companyId);
  const archive = useArchiveSalesCompany(companyId);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const raw = searchParams?.get("tab");
  const tab: Tab = TABS.some((t) => t.value === raw) ? (raw as Tab) : "overview";

  const state = resolveViewState({
    isLoading: company.isLoading,
    error: company.error,
    isSuccess: company.isSuccess,
  });
  const data = company.data;

  const toggleArchive = async () => {
    if (!data) return;
    const restoring = Boolean(data.archived_at);
    if (!restoring) {
      const ok = await askConfirm({
        title: `Zarchiwizować ${data.name}?`,
        description: "Firma zniknie z listy i wyszukiwania. Możesz ją później przywrócić.",
        confirmLabel: "Archiwizuj",
        variant: "destructive",
      });
      if (!ok) return;
    }
    archive.mutate(restoring, {
      onSuccess: () => showSuccess(restoring ? "Przywrócono firmę." : "Zarchiwizowano firmę."),
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić firmy.")),
    });
  };

  return (
    <SalesShell
      hideNav
      title={data?.name ?? "Firma"}
      description={
        data
          ? [
              LIFECYCLE_LABELS[data.lifecycle_stage],
              data.status !== "active" ? COMPANY_STATUS_LABELS[data.status] : null,
              data.open_opportunities
                ? `${data.open_opportunities} otwartych szans · ${formatDealAmount(data.open_value)}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")
          : undefined
      }
      actions={
        data && canEdit ? (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="quiet" onClick={() => void toggleArchive()}>
              {data.archived_at ? "Przywróć" : "Archiwizuj"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              Edytuj
            </Button>
            <Button size="sm" onClick={() => setCreating(true)} disabled={Boolean(data.archived_at)}>
              Szansa
            </Button>
          </div>
        ) : null
      }
    >
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie firmy…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "not_found" ? "Nie ma takiej firmy w kartotece sprzedaży." : undefined}
          onRetry={() => void company.refetch()}
        />
      ) : data ? (
        <div className="space-y-4">
          {data.archived_at && (
            <StatusDot tone="warning">Firma jest w archiwum</StatusDot>
          )}
          <TabbedNav
            ariaLabel="Zakładki firmy"
            tabs={TABS}
            value={tab}
            onValueChange={(value) => {
              const params = new URLSearchParams(window.location.search);
              if (value === "overview") params.delete("tab");
              else params.set("tab", value);
              const qs = params.toString();
              replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
            }}
          />
          {tab === "overview" && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="space-y-4">
                <CompanyFacts company={data} />
                <CompanyOpportunities companyId={companyId} />
              </div>
              <WhoWeKnowPanel companyId={companyId} companyName={data.name} />
            </div>
          )}
          {tab === "people" && <WhoWeKnowPanel companyId={companyId} companyName={data.name} />}
          {tab === "contacts" && <ContactsSection companyId={companyId} />}
          {tab === "activities" && <ActivityTimeline companyId={companyId} />}
        </div>
      ) : null}
      {editing && data && (
        <CompanyFormDialog open={editing} onOpenChange={setEditing} company={data} />
      )}
      {creating && data && (
        <OpportunityFormDialog
          open={creating}
          onOpenChange={setCreating}
          company={{ id: data.id, name: data.name }}
          onCreated={(opportunity) => router.push(`/sales/opportunities/${opportunity.id}`)}
        />
      )}
      {confirmDialog}
    </SalesShell>
  );
}
