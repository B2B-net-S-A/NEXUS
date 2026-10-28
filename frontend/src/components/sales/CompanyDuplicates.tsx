"use client";

import Link from "next/link";
import { Copy } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { useCompanyDuplicateGroups, useMergeCompany, type DuplicateGroup } from "@/lib/api/sales";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

/**
 * Grupy firm z tym samym NIP-em albo nazwą kanoniczną. „Zostaw tę” scala
 * pozostałe w wybraną: kontakty, szanse, historia, pliki i leady przechodzą,
 * a scalona firma trafia do archiwum (nic nie jest kasowane).
 */
export function CompanyDuplicates() {
  const groups = useCompanyDuplicateGroups();
  const merge = useMergeCompany();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const items = groups.data ?? [];
  const state = resolveViewState({
    isLoading: groups.isLoading,
    error: groups.error,
    isSuccess: groups.isSuccess,
    isEmpty: items.length === 0,
  });

  const keep = async (group: DuplicateGroup, targetId: number) => {
    const target = group.companies.find((company) => company.id === targetId);
    const sources = group.companies.filter((company) => company.id !== targetId);
    const ok = await askConfirm({
      title: `Zostawić „${target?.name}”?`,
      description: `${sources.length === 1 ? "Druga firma przejdzie" : `${sources.length} firmy przejdą`} do niej razem z kontaktami, szansami, historią i plikami, a potem trafi do archiwum.`,
      confirmLabel: "Scal",
    });
    if (!ok) return;
    for (const source of sources) {
      try {
        await merge.mutateAsync({ target_id: targetId, source_id: source.id });
      } catch (error) {
        showError(apiErrorMessage(error, `Nie udało się scalić „${source.name}”.`));
        return;
      }
    }
    showSuccess(`Scalono w „${target?.name}”.`);
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        <Link href="/sales/companies" className="text-primary hover:underline">
          ← Firmy
        </Link>
      </p>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Szukanie duplikatów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void groups.refetch()} />
      ) : state === "empty" ? (
        <EmptyState icon={Copy} title="Brak duplikatów" description="Żadne dwie firmy nie mają tego samego NIP-u ani nazwy." />
      ) : (
        <ul className="grid gap-3">
          {items.map((group) => (
            <li key={`${group.reason}-${group.key}`}>
              <Card className="space-y-2 p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  {group.reason === "nip" ? `Ten sam NIP ${group.key}` : "Ta sama nazwa"}
                </p>
                <ul className="divide-y divide-border">
                  {group.companies.map((company) => (
                    <li key={company.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
                      <span className="min-w-0">
                        <Link href={`/sales/companies/${company.id}`} className="font-medium hover:underline">
                          {company.name}
                        </Link>
                        <span className="ml-2 text-xs text-muted-foreground">
                          {[company.nip ? `NIP ${company.nip}` : null, `${company.open_opportunities} otw. szans`]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </span>
                      {canEdit && (
                        <Button size="sm" variant="outline" loading={merge.isPending} onClick={() => void keep(group, company.id)}>
                          Zostaw tę
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {confirmDialog}
    </div>
  );
}
