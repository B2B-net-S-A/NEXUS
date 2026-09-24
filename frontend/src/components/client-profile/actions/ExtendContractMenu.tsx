"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { useClickOutside } from "@/lib/use-click-outside";
import { useAuthStore } from "@/store/auth";
import { canManageClientDelivery } from "@/components/client-profile/permissions";

interface Props {
  contractId: number;
  clientId: number;
  /** Status kontraktu z profilu — „Przedłuż” wyłącznie dla `ending`. */
  contractStatus?: string | null;
}

const DURATIONS = [3, 6, 12];

/**
 * Czy wiersz konsultanta pokazuje „Przedłuż” (audyt 24.09.2026, W2).
 *
 * `POST /api/contracts/bulk-extend` wymaga `DeliveryLeadPlus` (admin + DL),
 * a przycisk widziały też Finanse i TCM — klik kończył się 403. Sensowny jest
 * tylko dla kontraktu „Kończący się”: umowę bezterminową backend pomija.
 */
export function canExtendContract(
  user: Parameters<typeof canManageClientDelivery>[0],
  contractStatus: string | null | undefined,
): boolean {
  return contractStatus === "ending" && canManageClientDelivery(user);
}

/** Klucze odświeżane po przedłużeniu — profil, zamówienia i rejestr kontraktów. */
export const EXTEND_INVALIDATED_KEYS = [
  ["client-profile"],
  ["dl-orders-grouped"],
  ["contracts-v2"],
  ["contracts-expiring-v2"],
  ["contractors-v2"],
] as const;

export function ExtendContractMenu({ contractId, clientId, contractStatus }: Props) {
  const user = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const [pendingMonths, setPendingMonths] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  // `open` jako `enabled`: przycisk otwierający leży poza containerRef, więc
  // listener podpięty na stałe zamknąłby menu tym samym mousedown, który je otwiera.
  useClickOutside(containerRef, () => setOpen(false), open);

  const mutation = useMutation({
    mutationFn: (months: number) =>
      api.post(
        `/api/contracts/bulk-extend?ids=${contractId}&months=${months}`,
        {}
      ),
    onSuccess: (response, months) => {
      for (const queryKey of EXTEND_INVALIDATED_KEYS) {
        queryClient.invalidateQueries({ queryKey: [...queryKey] });
      }
      // Backend pomija umowy bezterminowe (w tym każdą umowę B2B bez ręcznego
      // zakończenia) — „przedłużono" byłoby wtedy nieprawdą.
      if ((response?.data?.extended ?? 0) === 0) {
        showError(
          "Umowa jest bezterminowa — nie ma czego przedłużać. Przedłuż zamówienie klienta.",
        );
      } else {
        showSuccess(`Kontrakt przedłużony o ${months} mc`);
      }
      setPendingMonths(null);
    },
    onError: () => showError("Nie udało się przedłużyć kontraktu"),
  });

  if (!canExtendContract(user, contractStatus)) return null;

  return (
    <div ref={containerRef} className="relative" data-client-id={clientId}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={mutation.isPending}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/30 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 rounded-md transition-colors disabled:opacity-50"
      >
        {mutation.isPending ? "…" : "Przedłuż"}
        <ChevronDown className="w-3 h-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 bg-card dark:bg-muted border border-border dark:border-border rounded-lg shadow-lg z-10 min-w-[120px] py-1">
          {DURATIONS.map((m) => (
            <button
              key={m}
              onClick={() => {
                setOpen(false);
                setPendingMonths(m);
              }}
              className={cn(
                "block w-full text-left px-3 py-1.5 text-xs hover:bg-emerald-50 dark:hover:bg-emerald-900/30 text-foreground dark:text-muted-foreground"
              )}
            >
              + {countPl(m, "miesiąc", "miesiące", "miesięcy")}
            </button>
          ))}
        </div>
      )}
      <AppModal
        open={pendingMonths !== null}
        onOpenChange={(next) => {
          if (!next && !mutation.isPending) setPendingMonths(null);
        }}
        title="Przedłużyć kontrakt?"
        size="sm"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setPendingMonths(null)}
              disabled={mutation.isPending}
            >
              Anuluj
            </Button>
            <Button
              onClick={() => {
                if (pendingMonths !== null) mutation.mutate(pendingMonths);
              }}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Przedłużam…" : "Przedłuż i cofnij wypowiedzenie"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-foreground">
          Data końca kontraktu przesunie się o{" "}
          {pendingMonths !== null
            ? countPl(pendingMonths, "miesiąc", "miesiące", "miesięcy")
            : ""}
          .
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Jeśli współpraca była wypowiedziana, wypowiedzenie zostanie cofnięte:
          dane rozwiązania umowy znikną z kontraktu, a kontrakt wróci do
          aktywnych. Tego nie da się cofnąć jednym kliknięciem.
        </p>
      </AppModal>
    </div>
  );
}
