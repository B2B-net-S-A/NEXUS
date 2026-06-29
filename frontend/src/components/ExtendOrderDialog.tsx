"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

interface ExtendOrderDialogProps {
  clientId: number;
  contract: ContractWithOrdersRead;
  onClose: () => void;
  onCreated: () => void;
}

/** Flow A — "Dodaj przedłużenie": tworzy Order pod istniejącym Contract. */
export function ExtendOrderDialog({
  clientId,
  contract,
  onClose,
  onCreated,
}: ExtendOrderDialogProps) {
  const { showToast } = useToast();
  const latest = contract.orders[0]; // assumed already sorted desc

  const [title, setTitle] = useState(
    `Przedłużenie ${contract.candidate_name}`,
  );
  const [startDate, setStartDate] = useState(
    latest?.end_date
      ? // start dzień po końcu poprzedniego
        new Date(new Date(latest.end_date).getTime() + 86400000)
          .toISOString()
          .slice(0, 10)
      : "",
  );
  const [endDate, setEndDate] = useState("");
  const [rateClient, setRateClient] = useState(
    String(latest?.rate_client ?? contract.latest_order_rate_client ?? ""),
  );
  const [totalValue, setTotalValue] = useState("");
  const [jobId, setJobId] = useState(
    String(latest?.job_id ?? contract.initial_job_id ?? ""),
  );
  const [file, setFile] = useState<File | null>(null);

  // Stawki przyjmują grosze wpisane po polsku (przecinek) — parseDecimalInput.
  const rateClientNum = parseDecimalInput(rateClient);

  const mutation = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("contract_id", String(contract.contract_id));
      fd.append("title", title);
      fd.append("order_status", "active");
      if (startDate) fd.append("start_date", startDate);
      if (endDate) fd.append("end_date", endDate);
      // Wyślij znormalizowaną liczbę (kropka dziesiętna), nie surowy string z przecinkiem.
      if (rateClientNum !== null) fd.append("rate_client", String(rateClientNum));
      const totalValueNum = parseDecimalInput(totalValue);
      if (totalValueNum !== null) fd.append("total_value", String(totalValueNum));
      if (jobId) fd.append("job_id", jobId);
      if (file) fd.append("file", file);
      return dlPortalApi.createOrderExtension(clientId, fd);
    },
    onSuccess: () => {
      showToast("Przedłużenie dodane", "success");
      onCreated();
    },
    onError: (err: unknown) => {
      showToast(err instanceof Error ? err.message : "Błąd zapisu", "error");
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        className="bg-card rounded-lg shadow-xl max-w-md w-full p-6 space-y-3 max-h-[90vh] overflow-auto"
      >
        <div>
          <h3 className="text-lg font-semibold">Nowe zamówienie / przedłużenie</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Dla: <strong>{contract.candidate_name}</strong> · Contract #{contract.contract_id}
          </p>
        </div>

        <label className="block">
          <span className="text-sm">Tytuł zamówienia</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Start</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              onBlur={(e) => setStartDate(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Koniec</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              onBlur={(e) => setEndDate(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Klient płaci (rate_client) /mc</span>
            <input
              type="text"
              inputMode="decimal"
              value={rateClient}
              onChange={(e) => setRateClient(sanitizeDecimalInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              placeholder="np. 17000"
            />
            {contract.rate_candidate !== null && rateClientNum !== null && (
              <span className="text-xs text-green-700 mt-0.5 block">
                marża /mc: {rateClientNum - contract.rate_candidate}
              </span>
            )}
          </label>
          <label>
            <span className="text-sm">Total value (opcjonalnie)</span>
            <input
              type="text"
              inputMode="decimal"
              value={totalValue}
              onChange={(e) => setTotalValue(sanitizeDecimalInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        <label className="block">
          <span className="text-sm">Job ID (rekrutacja, z której przedłużenie)</span>
          <input
            type="number"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder={contract.initial_job_id?.toString() ?? "—"}
          />
        </label>

        <label className="block">
          <span className="text-sm">PDF zamówienia od klienta</span>
          <input
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 w-full text-sm"
          />
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-sm border border-border rounded"
          >
            Anuluj
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Zapisywanie…" : "Zapisz przedłużenie"}
          </button>
        </div>
      </form>
    </div>
  );
}
