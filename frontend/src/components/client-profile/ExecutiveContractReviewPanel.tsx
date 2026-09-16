"use client";

/**
 * „Przypisania do przeglądu" — obecni konsultanci Centrum e-Zdrowia, których
 * bieżące zamówienie nie wisi jeszcze na żadnej umowie wykonawczej (wiersze
 * sprzed wdrożenia struktury umów). Delivery Lead wybiera umowę per wiersz.
 *
 * Select startuje PUSTY: backend podpowiada umowę ramową o tej samej części
 * co dotychczasowa (`suggested_framework_contract_id`), ale ticket wyklucza
 * automatyczne przypisanie — dotychczasowa część mogła być wpisana na oko,
 * więc podpowiedź jest oznaczeniem grupy w etykiecie, nigdy preselekcją.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Loader2, RefreshCw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  contractStructureQueryKey,
  executiveContractReviewQueryKey,
  executiveContractsApi,
  useExecutiveContractOptions,
  type ExecutiveContractOptionGroup,
  type ExecutiveContractReviewResponse,
  type ExecutiveContractReviewRow,
} from "@/lib/api/executiveContracts";
import { isEzdrowieClient, projectPartLabel } from "@/lib/ezdrowie";
import { formatDate } from "@/types/client-profile";

/** Klucz profilu klienta — ten sam, którego używa `ProfileTab` i `page.tsx`. */
export const clientProfileQueryKey = (clientId: number) =>
  ["client-profile", clientId] as const;

function useExecutiveContractReview(clientId: number) {
  return useQuery({
    queryKey: executiveContractReviewQueryKey(clientId),
    enabled: isEzdrowieClient(clientId),
    queryFn: () => executiveContractsApi.review(clientId),
    staleTime: 60 * 1000,
  });
}

interface Props {
  clientId: number;
}

export function ExecutiveContractReviewPanel({ clientId }: Props) {
  const review = useExecutiveContractReview(clientId);
  const { groups, isSuccess: structureLoaded } = useExecutiveContractOptions(clientId);
  const rows = review.data?.rows ?? [];

  return (
    <section className="space-y-2" aria-labelledby="executive-contract-review-heading">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="h-4 w-4 text-primary" aria-hidden="true" />
        <h4
          id="executive-contract-review-heading"
          className="text-sm font-semibold text-foreground"
        >
          Przypisania do przeglądu
        </h4>
        {review.isSuccess ? (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
            {review.data.total}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        Konsultanci z zamówieniem sprzed struktury umów. Wybierz umowę wykonawczą
        — przypisanie jest ręczne, dotychczasowa część to tylko podpowiedź.
      </p>

      {review.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie przypisań…</p>
      ) : review.isError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-md border border-dashed border-border px-3 py-2 text-sm"
        >
          <span className="text-destructive">
            Nie udało się wczytać przypisań do przeglądu.
          </span>
          <Button variant="outline" size="sm" onClick={() => review.refetch()}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Ponów
          </Button>
        </div>
      ) : rows.length === 0 ? (
        // Pusty stan WYŁĄCZNIE na `isSuccess` — przerwa między ponowieniami
        // ma `data === undefined`, a „wszyscy przypisani" byłoby wtedy kłamstwem.
        <p className="rounded-md border border-dashed border-border px-3 py-3 text-sm text-muted-foreground">
          Wszyscy obecni konsultanci mają przypisaną umowę wykonawczą.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Konsultant</th>
                <th className="py-2 pr-4 font-medium">Start</th>
                <th className="py-2 pr-4 font-medium">Dziś</th>
                <th className="py-2 pr-4 font-medium">Umowa wykonawcza</th>
                <th className="py-2 text-right font-medium">Akcje</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <ReviewRow
                  key={row.contract_id}
                  clientId={clientId}
                  row={row}
                  groups={groups}
                  structureLoaded={structureLoaded}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ReviewRow({
  clientId,
  row,
  groups,
  structureLoaded,
}: {
  clientId: number;
  row: ExecutiveContractReviewRow;
  groups: ExecutiveContractOptionGroup[];
  structureLoaded: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [selected, setSelected] = useState("");
  const noOptions = structureLoaded && groups.length === 0;

  const assign = useMutation({
    mutationFn: () =>
      executiveContractsApi.assign(clientId, {
        contract_id: row.contract_id,
        executive_contract_id: Number(selected),
      }),
    onSuccess: async (res) => {
      // Wiersz znika od razu z cache'u (nie czekamy na refetch), a licznik
      // idzie za nim — potem unieważniamy wszystko, co czyta przypisania.
      queryClient.setQueryData<ExecutiveContractReviewResponse>(
        executiveContractReviewQueryKey(clientId),
        (prev) =>
          prev
            ? {
                rows: prev.rows.filter((r) => r.contract_id !== row.contract_id),
                total: Math.max(0, prev.total - 1),
              }
            : prev,
      );
      showSuccess(
        `${row.candidate.name} — przypisano do ${res.executive_contract.number}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: executiveContractReviewQueryKey(clientId),
        }),
        queryClient.invalidateQueries({
          queryKey: contractStructureQueryKey(clientId),
        }),
        queryClient.invalidateQueries({
          queryKey: clientProfileQueryKey(clientId),
        }),
      ]);
    },
    onError: (err: unknown) => {
      showError(apiErrorMessage(err, "Nie udało się przypisać umowy wykonawczej."));
    },
  });

  const selectLabel = `Umowa wykonawcza dla ${row.candidate.name}`;

  return (
    <tr className="border-b border-border">
      <td className="py-2 pr-4">
        <span className="font-medium text-foreground">{row.candidate.name}</span>
        {row.bucket === "planned" ? (
          <span className="ml-2 text-xs text-muted-foreground">(planowany)</span>
        ) : null}
      </td>
      <td className="py-2 pr-4 tabular-nums">{formatDate(row.start_date)}</td>
      <td className="py-2 pr-4 text-muted-foreground">
        {row.legacy_project_part
          ? `dziś: ${projectPartLabel(row.legacy_project_part)}`
          : "dziś: bez części"}
      </td>
      <td className="py-2 pr-4">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          aria-label={selectLabel}
          disabled={assign.isPending || noOptions}
          className="w-full min-w-[14rem] rounded-md border border-border bg-background px-2 py-1 text-sm disabled:opacity-60"
        >
          <option value="">— wybierz —</option>
          {groups.map((group) => (
            <optgroup
              key={group.framework_contract_id}
              label={
                group.framework_contract_id === row.suggested_framework_contract_id
                  ? `${group.label} (ta sama część co dziś)`
                  : group.label
              }
            >
              {group.options.map((ec) => (
                <option key={ec.id} value={String(ec.id)}>
                  {ec.number}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {noOptions ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Brak aktywnej umowy wykonawczej — najpierw dodaj ją powyżej.
          </p>
        ) : null}
      </td>
      <td className="py-2 text-right">
        <Button
          size="sm"
          disabled={!selected || assign.isPending}
          onClick={() => assign.mutate()}
          aria-label={`Przypisz: ${row.candidate.name}`}
        >
          {assign.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : null}
          Przypisz
        </Button>
      </td>
    </tr>
  );
}
