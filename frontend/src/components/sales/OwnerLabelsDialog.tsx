"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { api } from "@/lib/api";
import { assigneeLabel, type AssigneeOption } from "@/lib/api/boardTasks";
import { useAssignOwnerLabel, useOwnerLabels } from "@/lib/api/sales";

import { SalesSelect } from "./SalesSelect";

/**
 * Admin przypisuje opiekunów z Atlasa (sam tekst, bez konta) do kont NEXUSA.
 * Firmy z etykietą i ich szanse bez opiekuna dostają wybrane konto. Nazwisk
 * nie ma w kodzie ani w logach — mapę ustala człowiek na tym ekranie.
 */
// Handlowcy bywają „Pracownikami” (rola bez rekrutacji), więc katalog obejmuje
// każdą rolę, która może dostać „Sprzedaż: edycja”.
const OWNER_ROLES = ["admin", "head_of_recruitment", "delivery_lead", "recruiter", "employee", "finance"];

function useOwnerCandidates() {
  return useQuery<AssigneeOption[]>({
    queryKey: ["users-directory", "sales-owners"],
    queryFn: async () =>
      (
        await api.get<AssigneeOption[]>("/api/users", {
          params: { roles: OWNER_ROLES },
          paramsSerializer: { indexes: null },
        })
      ).data,
    staleTime: 5 * 60_000,
  });
}

export function OwnerLabelsDialog({ onClose }: { onClose: () => void }) {
  const labels = useOwnerLabels();
  const users = useOwnerCandidates();
  const assign = useAssignOwnerLabel();
  const { showError, showSuccess } = useToast();
  const [choice, setChoice] = useState<Record<string, string>>({});
  const userOptions = (users.data ?? []).map((user) => ({ value: String(user.id), label: assigneeLabel(user) }));

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Opiekunowie z Atlasa"
      description="Osoby, które w Atlasie prowadziły firmy, a nie mają tu przypisanego konta. Wybierz konto, a firmy i ich szanse bez opiekuna przejdą na nie."
      size="lg"
      footer={
        <Button variant="outline" onClick={onClose}>
          Zamknij
        </Button>
      }
    >
      {labels.isLoading ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (labels.data ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">Wszystkie firmy z Atlasa mają już opiekuna z kontem.</p>
      ) : (
        <ul className="divide-y divide-border">
          {(labels.data ?? []).map((entry) => (
            <li key={entry.label} className="flex flex-wrap items-center justify-between gap-3 py-2">
              <div className="min-w-0 text-sm">
                <p className="font-medium text-foreground">{entry.label}</p>
                <p className="text-xs text-muted-foreground">{entry.companies} firm</p>
              </div>
              <div className="flex items-center gap-2">
                <SalesSelect
                  ariaLabel={`Konto dla: ${entry.label}`}
                  className="w-60"
                  value={choice[entry.label] ?? ""}
                  onValueChange={(value) => setChoice((current) => ({ ...current, [entry.label]: value }))}
                  options={userOptions}
                  anyLabel="Wybierz konto"
                />
                <Button
                  size="sm"
                  disabled={!choice[entry.label]}
                  loading={assign.isPending && assign.variables?.label === entry.label}
                  onClick={() =>
                    assign.mutate(
                      { label: entry.label, owner_user_id: Number(choice[entry.label]) },
                      {
                        onSuccess: (result) =>
                          showSuccess(`Przypisano ${result.companies} firm i ${result.opportunities} szans.`),
                        onError: (error) => showError(apiErrorMessage(error, "Nie udało się przypisać opiekuna.")),
                      },
                    )
                  }
                >
                  Przypisz
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </AppModal>
  );
}
