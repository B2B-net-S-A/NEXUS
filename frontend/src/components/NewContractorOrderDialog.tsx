"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";

interface NewContractorOrderDialogProps {
  clientId: number;
  onClose: () => void;
  onCreated: () => void;
}

const DATE_PLACEHOLDER = "RRRR-MM-DD lub DD.MM.RRRR";
const DATE_PATTERN =
  "\\d{4}-\\d{1,2}-\\d{1,2}|\\d{1,2}[./-]\\d{1,2}[./-]\\d{4}";

function normalizeDateInput(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  const iso = trimmed.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) {
    const [, y, m, d] = iso;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  const eu = trimmed.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (eu) {
    const [, d, m, y] = eu;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  return trimmed;
}

/** Flow B — "Nowy kontraktor": atomic Contract + Order create. */
export function NewContractorOrderDialog({
  clientId,
  onClose,
  onCreated,
}: NewContractorOrderDialogProps) {
  const { showToast } = useToast();
  const [candidateId, setCandidateId] = useState("");
  const [jobId, setJobId] = useState("");
  const [title, setTitle] = useState("");
  const [contractStart, setContractStart] = useState("");
  const [contractEnd, setContractEnd] = useState("");
  const [orderStart, setOrderStart] = useState("");
  const [orderEnd, setOrderEnd] = useState("");
  const [rateClient, setRateClient] = useState("");
  const [rateCandidate, setRateCandidate] = useState("");
  const [rateUnit, setRateUnit] = useState<"monthly" | "daily" | "hourly">(
    "monthly",
  );
  const [billingHours, setBillingHours] = useState("160");
  const [currency, setCurrency] = useState("PLN");
  const [notes, setNotes] = useState("");

  const margin =
    rateClient && rateCandidate
      ? Number(rateClient) - Number(rateCandidate)
      : null;

  const mutation = useMutation({
    mutationFn: () =>
      dlPortalApi.createContractWithOrder(clientId, {
        candidate_id: Number(candidateId),
        job_id: jobId ? Number(jobId) : null,
        title,
        contract_start_date: contractStart,
        contract_end_date: contractEnd || null,
        order_start_date: orderStart || contractStart,
        order_end_date: orderEnd || null,
        rate_client: Number(rateClient),
        rate_candidate: Number(rateCandidate),
        rate_unit: rateUnit,
        billing_hours_per_month: Number(billingHours),
        currency,
        notes: notes || null,
      }),
    onSuccess: (res) => {
      showToast(
        `Kontrakt #${res.data.contract_id} + Order #${res.data.order_id} utworzone (marża ${res.data.monthly_margin}/mc)`,
        "success",
      );
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
          if (!candidateId || !title || !contractStart || !rateClient || !rateCandidate) {
            showToast("Wypełnij wymagane pola", "error");
            return;
          }
          mutation.mutate();
        }}
        className="bg-card rounded-lg shadow-xl max-w-xl w-full p-6 space-y-3 max-h-[90vh] overflow-auto"
      >
        <div>
          <h3 className="text-lg font-semibold">Nowy kontraktor / zamówienie</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Atomic: tworzy nowy Contract z kandydatem + pierwszy Order pod nim.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Candidate ID *</span>
            <input
              type="number"
              value={candidateId}
              onChange={(e) => setCandidateId(e.target.value)}
              required
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              placeholder="np. 123"
            />
          </label>
          <label>
            <span className="text-sm">Job ID (rekrutacja)</span>
            <input
              type="number"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              placeholder="opcjonalnie"
            />
          </label>
        </div>

        <label className="block">
          <span className="text-sm">Tytuł zamówienia *</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="np. Jan Kowalski — Senior Java Developer"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Contract start *</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={contractStart}
              onChange={(e) => setContractStart(e.target.value)}
              onBlur={(e) => setContractStart(normalizeDateInput(e.target.value))}
              required
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Contract end</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={contractEnd}
              onChange={(e) => setContractEnd(e.target.value)}
              onBlur={(e) => setContractEnd(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Order start (PDF od klienta)</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={orderStart}
              onChange={(e) => setOrderStart(e.target.value)}
              onBlur={(e) => setOrderStart(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Order end</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={orderEnd}
              onChange={(e) => setOrderEnd(e.target.value)}
              onBlur={(e) => setOrderEnd(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Klient płaci /mc *</span>
            <input
              type="number"
              min="0"
              value={rateClient}
              onChange={(e) => setRateClient(e.target.value)}
              required
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              placeholder="rate_client"
            />
          </label>
          <label>
            <span className="text-sm">My płacimy kontraktorowi *</span>
            <input
              type="number"
              min="0"
              value={rateCandidate}
              onChange={(e) => setRateCandidate(e.target.value)}
              required
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              placeholder="rate_candidate"
            />
          </label>
        </div>

        {margin !== null && (
          <div className="text-sm text-green-700 bg-green-50 px-3 py-2 rounded">
            Marża /mc (przybl.): <strong>{margin.toLocaleString("pl-PL")}</strong> {currency}
            {Number(rateClient) > 0 && (
              <> ({((margin / Number(rateClient)) * 100).toFixed(1)}%)</>
            )}
          </div>
        )}

        <div className="grid grid-cols-3 gap-3">
          <label>
            <span className="text-sm">Jednostka stawki</span>
            <select
              value={rateUnit}
              onChange={(e) =>
                setRateUnit(e.target.value as "monthly" | "daily" | "hourly")
              }
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            >
              <option value="monthly">Miesięcznie</option>
              <option value="daily">Dziennie</option>
              <option value="hourly">Godzinowo</option>
            </select>
          </label>
          <label>
            <span className="text-sm">Godziny / mc</span>
            <input
              type="number"
              min="1"
              value={billingHours}
              onChange={(e) => setBillingHours(e.target.value)}
              disabled={rateUnit !== "hourly"}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background disabled:opacity-50"
            />
          </label>
          <label>
            <span className="text-sm">Waluta</span>
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              maxLength={3}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        <label className="block">
          <span className="text-sm">Notatki</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
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
            {mutation.isPending ? "Zapisywanie…" : "Stwórz Contract + Order"}
          </button>
        </div>
      </form>
    </div>
  );
}
