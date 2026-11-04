"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Building2, Plus } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  LIFECYCLE_LABELS,
  useSalesCompanies,
  type CompanyLifecycle,
} from "@/lib/api/sales";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

import { CompanyFormDialog } from "./CompanyFormDialog";
import { formatDealNumber } from "./format";
import { SalesSelect } from "./SalesSelect";
import { OwnerLabelsDialog } from "./OwnerLabelsDialog";
import { useOwnerFilterOptions } from "./useOwnerFilterOptions";

const LIFECYCLE_OPTIONS = Object.entries(LIFECYCLE_LABELS).map(([value, label]) => ({
  value,
  label,
}));
const PAGE = 50;

/** Firmy w kartotece sprzedaży: szukaj po nazwie i NIP, etap relacji, otwarty lejek. */
export function CompaniesList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const lifecycle = (searchParams?.get("etap") ?? "") as CompanyLifecycle | "";
  const offset = Math.max(0, Number(searchParams?.get("od") ?? 0) || 0);
  const [creating, setCreating] = useState(false);
  // Opiekun: konto NEXUSA albo etykieta z Atlasa (osoba bez konta); archiwum;
  // firmy, które import przepuścił warunkowo (audyt importu 28.10.2026).
  const owner = searchParams?.get("opiekun") ?? "";
  const archived = searchParams?.get("archiwum") === "1";
  const review = searchParams?.get("przeglad") === "1";
  const ownerOptions = useOwnerFilterOptions();
  const [assigningLabels, setAssigningLabels] = useState(false);
  const isAdmin = hasRole(user, "admin");
  const ownerId =
    owner === "me" ? (user?.id ?? null) : owner.startsWith("acct:") ? Number(owner.slice(5)) : null;
  const ownerLabel = owner.startsWith("label:") ? owner.slice(6) : null;
  const companies = useSalesCompanies({
    q,
    lifecycle,
    offset,
    owner_id: ownerId,
    owner_label: ownerLabel,
    review,
    archived,
  });
  const items = companies.data?.items ?? [];
  const total = companies.data?.total ?? 0;

  const writeParams = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(patch)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  const state = resolveViewState({
    isLoading: companies.isLoading,
    error: companies.error,
    isSuccess: companies.isSuccess,
    isEmpty: items.length === 0,
  });

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            writeParams({ q: value.trim() || null, od: null });
          },
          placeholder: "Szukaj po nazwie, NIP albo domenie…",
          ariaLabel: "Szukaj firmy",
        }}
        filters={
          <>
            <SalesSelect
              ariaLabel="Etap relacji"
              className="w-48"
              value={lifecycle}
              onValueChange={(value) => writeParams({ etap: value || null, od: null })}
              options={LIFECYCLE_OPTIONS}
              anyLabel="Każdy etap relacji"
            />
            <SalesSelect
              ariaLabel="Opiekun"
              className="w-56"
              value={owner}
              onValueChange={(value) => writeParams({ opiekun: value || null, od: null })}
              options={ownerOptions}
              anyLabel="Każdy opiekun"
            />
            <Button
              size="sm"
              variant={review ? "primary" : "outline"}
              aria-pressed={review}
              onClick={() => writeParams({ przeglad: review ? null : "1", od: null })}
            >
              Do przejrzenia po imporcie
            </Button>
            <Button
              size="sm"
              variant={archived ? "primary" : "outline"}
              aria-pressed={archived}
              onClick={() => writeParams({ archiwum: archived ? null : "1", od: null })}
            >
              Archiwum
            </Button>
          </>
        }
        resultCount={companies.isSuccess ? total : undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            {isAdmin && (
              <Button size="sm" variant="outline" onClick={() => setAssigningLabels(true)}>
                Opiekunowie z Atlasa
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => router.push("/sales/companies/duplicates")}>
              Duplikaty
            </Button>
            {canEdit && (
              <Button size="sm" onClick={() => setCreating(true)}>
                <Plus className="mr-1 h-4 w-4" aria-hidden /> Nowa firma
              </Button>
            )}
          </div>
        }
      />

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie firm…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void companies.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={Building2}
          title={q || lifecycle || owner || review || archived ? "Nic nie pasuje do filtrów" : "Kartoteka jest pusta"}
          description={
            q || lifecycle || owner || review || archived
              ? "Zmień wyszukiwanie albo etap relacji."
              : "Dodaj pierwszą firmę albo poczekaj na import z Atlasa."
          }
        />
      ) : (
        <>
          <div className="relative overflow-x-auto">
            <Table className="min-w-[760px]">
              <TableHeader>
                <TableRow>
                  <TableHead className={`${CALM_HEAD} sticky left-0 bg-card`}>Firma</TableHead>
                  <TableHead className={CALM_HEAD}>Etap relacji</TableHead>
                  <TableHead className={`${CALM_HEAD} text-right`}>Otwarte szanse</TableHead>
                  <TableHead className={`${CALM_HEAD} text-right`}>W lejku (zł)</TableHead>
                  <TableHead className={CALM_HEAD}>Opiekun</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((company) => (
                  <TableRow
                    key={company.id}
                    className={`${CALM_ROW} cursor-pointer`}
                    onClick={() => router.push(`/sales/companies/${company.id}`)}
                  >
                    <TableCell className="sticky left-0 bg-card">
                      <Link
                        href={`/sales/companies/${company.id}`}
                        className="font-medium text-foreground hover:underline"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {company.name}
                      </Link>
                      {company.needs_review && (
                        <Badge variant="warning" size="sm" className="ml-1.5">
                          do przejrzenia
                        </Badge>
                      )}
                      <p className={CALM_SUBLINE}>
                        {[company.client ? "klient w NEXUSIE" : null, company.industry, company.hq_city]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </p>
                    </TableCell>
                    <TableCell>{LIFECYCLE_LABELS[company.lifecycle_stage]}</TableCell>
                    <TableCell className={CALM_AMOUNT}>{company.open_opportunities}</TableCell>
                    <TableCell className={CALM_AMOUNT}>
                      {company.open_opportunities ? formatDealNumber(company.open_value) : "—"}
                    </TableCell>
                    <TableCell>
                      {company.owner?.name ??
                        (company.owner_label ? (
                          <span className="text-muted-foreground">
                            {company.owner_label}
                            <span className={`${CALM_SUBLINE} block`}>z Atlasa · bez konta w NEXUSIE</span>
                          </span>
                        ) : (
                          "—"
                        ))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {total > PAGE && (
            <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, total)} z {total}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => writeParams({ od: offset - PAGE > 0 ? String(offset - PAGE) : null })}
              >
                Poprzednie
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={offset + PAGE >= total}
                onClick={() => writeParams({ od: String(offset + PAGE) })}
              >
                Następne
              </Button>
            </div>
          )}
        </>
      )}

      {assigningLabels && <OwnerLabelsDialog onClose={() => setAssigningLabels(false)} />}
      {creating && (
        <CompanyFormDialog
          open={creating}
          onOpenChange={setCreating}
          onSaved={(company) => router.push(`/sales/companies/${company.id}`)}
        />
      )}
    </div>
  );
}
