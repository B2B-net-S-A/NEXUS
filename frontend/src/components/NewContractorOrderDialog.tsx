"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import api, { extractErrorMsg } from "@/lib/api";
import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";
import { PROJECT_PARTS, isEzdrowieClient } from "@/lib/ezdrowie";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import {
  canManageCandidateFinance,
  useAuthStore,
} from "@/store/auth";

interface NewContractorOrderDialogProps {
  clientId: number;
  onClose: () => void;
  onCreated: () => void;
}

interface CandidateSearchItem {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
  location?: string | null;
  competence_category?: string | null;
}

interface JobListItem {
  id: number;
  title: string;
  status?: string | null;
}

/** Backend trzyma location jako JSON string ({lat, lng, locality, iso, ...}) lub plain string. */
function formatCandidateLocation(loc?: string | null): string | null {
  if (!loc) return null;
  const trimmed = loc.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      const locality = parsed.locality ?? parsed.city ?? parsed.region1;
      return typeof locality === "string" && locality ? locality : null;
    } catch {
      return null;
    }
  }
  return trimmed;
}

/** Flow B — "Nowy kontraktor": atomic Contract + Order create. */
export function NewContractorOrderDialog({
  clientId,
  onClose,
  onCreated,
}: NewContractorOrderDialogProps) {
  const { showToast, showError } = useToast();
  const user = useAuthStore((state) => state.user);
  const canManageFinance = canManageCandidateFinance(user);

  // Candidate typeahead state
  const [candidateQuery, setCandidateQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedCandidate, setSelectedCandidate] =
    useState<CandidateSearchItem | null>(null);

  const [jobId, setJobId] = useState<string>(""); // "" = brak
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
  // „Część umowy" — pole widoczne i wymagane wyłącznie dla Centrum e-Zdrowia
  // (ticket #3; bramka po client_id, walidacja też serwerowo).
  const ezdrowie = isEzdrowieClient(clientId);
  const [projectPart, setProjectPart] = useState<string>("");

  // Debounce candidate search (300ms — same as AddCandidateToJobModal)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(candidateQuery.trim()), 300);
    return () => clearTimeout(t);
  }, [candidateQuery]);

  const { data: candidates = [], isFetching: candLoading } = useQuery<
    CandidateSearchItem[]
  >({
    queryKey: ["new-contractor-candidate-search", debouncedQuery],
    queryFn: async () => {
      if (debouncedQuery.length < 2) return [];
      const r = await api.get("/api/candidates", {
        params: { q: debouncedQuery, page_size: 15 },
      });
      const payload = r.data;
      return Array.isArray(payload) ? payload : payload?.items ?? [];
    },
    enabled: !selectedCandidate && debouncedQuery.length >= 2,
  });

  // Jobs of this client (for optional Job picker)
  const { data: clientJobs = [] } = useQuery<JobListItem[]>({
    queryKey: ["new-contractor-client-jobs", clientId],
    queryFn: async () => {
      const r = await api.get("/api/jobs", {
        params: { client_id: clientId, page_size: 100 },
      });
      const payload = r.data;
      return Array.isArray(payload) ? payload : payload?.items ?? [];
    },
  });

  // Autofill USUNIĘTY: ta wartość jest pokazywana na karcie klienta jako
  // „Numer zamówienia", a podpowiedź „Imię Nazwisko — Stanowisko" wpisywała tam
  // nazwisko z tytułem rekrutacji zamiast numeru z dokumentu klienta. Pole
  // wyglądające na wypełnione nie jest poprawiane, więc numer nigdy nie
  // trafiał do systemu.

  // Stawki przyjmują grosze wpisane po polsku (przecinek) — parseDecimalInput.
  const rateClientNum = parseDecimalInput(rateClient);
  const rateCandidateNum = parseDecimalInput(rateCandidate);
  const margin =
    rateClientNum !== null && rateCandidateNum !== null
      ? rateClientNum - rateCandidateNum
      : null;

  const mutation = useMutation({
    mutationFn: () => {
      if (!selectedCandidate) {
        throw new Error("Wybierz kandydata");
      }
      const payload: Parameters<
        typeof dlPortalApi.createContractWithOrder
      >[1] = {
        candidate_id: selectedCandidate.id,
        job_id: jobId ? Number(jobId) : null,
        title,
        contract_start_date: contractStart,
        contract_end_date: contractEnd || null,
        order_start_date: orderStart || contractStart,
        order_end_date: orderEnd || null,
        notes: notes || null,
      };
      if (ezdrowie) {
        payload.project_part = projectPart || null;
      }
      if (canManageFinance) {
        payload.rate_client = rateClientNum ?? undefined;
        payload.rate_candidate = rateCandidateNum ?? undefined;
        payload.rate_unit = rateUnit;
        payload.billing_hours_per_month = Number(billingHours);
        payload.currency = currency;
      }
      return dlPortalApi.createContractWithOrder(clientId, payload);
    },
    onSuccess: (res) => {
      const marginSuffix =
        res.data.monthly_margin == null
          ? ""
          : ` (marża ${res.data.monthly_margin}/mc)`;
      showToast(
        `Kontrakt #${res.data.contract_id} + Order #${res.data.order_id} utworzone${marginSuffix}`,
        "success",
      );
      onCreated();
    },
    onError: (err: unknown) => {
      showError(extractErrorMsg(err));
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (
            !selectedCandidate ||
            !title ||
            !contractStart ||
            (canManageFinance &&
              (rateClientNum === null || rateCandidateNum === null))
          ) {
            showError(
              canManageFinance
                ? "Wypełnij wymagane pola (kandydat, tytuł, daty, stawki)"
                : "Wypełnij wymagane pola (kandydat, tytuł, data rozpoczęcia)",
            );
            return;
          }
          if (ezdrowie && !projectPart) {
            showError("Wybierz część umowy");
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

        {/* Candidate picker (typeahead search) */}
        <div>
          <span className="text-sm">Kandydat *</span>
          {selectedCandidate ? (
            <div className="mt-1 flex items-center justify-between gap-3 px-3 py-2 border border-border rounded bg-background">
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">
                  {selectedCandidate.name} {selectedCandidate.lastname}{" "}
                  <span className="text-xs text-muted-foreground">
                    #{selectedCandidate.id}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {[
                    selectedCandidate.competence_category,
                    formatCandidateLocation(selectedCandidate.location),
                    selectedCandidate.email,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedCandidate(null);
                  setCandidateQuery("");
                  setDebouncedQuery("");
                }}
                className="text-xs text-muted-foreground hover:text-foreground shrink-0"
              >
                Zmień
              </button>
            </div>
          ) : (
            <>
              <div className="relative mt-1">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
                <input
                  type="text"
                  autoFocus
                  value={candidateQuery}
                  onChange={(e) => setCandidateQuery(e.target.value)}
                  placeholder="Szukaj po imieniu, emailu, skillu..."
                  className="w-full pl-9 pr-3 py-2 border border-border rounded bg-background"
                />
              </div>
              {debouncedQuery.length >= 2 && (
                <div className="mt-1 max-h-48 overflow-y-auto border border-border rounded bg-background">
                  {candLoading ? (
                    <p className="text-xs text-muted-foreground text-center py-3">
                      Szukam…
                    </p>
                  ) : candidates.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-3">
                      Brak wyników dla „{debouncedQuery}".
                    </p>
                  ) : (
                    candidates.map((c) => (
                      <button
                        type="button"
                        key={c.id}
                        onClick={() => {
                          setSelectedCandidate(c);
                          setCandidateQuery("");
                        }}
                        className="w-full text-left px-3 py-2 hover:bg-muted transition-colors border-b border-border last:border-b-0"
                      >
                        <p className="text-sm font-medium truncate">
                          {c.name} {c.lastname}{" "}
                          <span className="text-xs text-muted-foreground">
                            #{c.id}
                          </span>
                        </p>
                        <p className="text-xs text-muted-foreground truncate">
                          {[c.competence_category, formatCandidateLocation(c.location), c.email]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </p>
                      </button>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Job dropdown (jobs of this client) */}
        <label className="block">
          <span className="text-sm">Rekrutacja (opcjonalnie)</span>
          <select
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
          >
            <option value="">— brak —</option>
            {clientJobs.map((j) => (
              <option key={j.id} value={String(j.id)}>
                #{j.id} · {j.title}
                {j.status ? ` (${j.status})` : ""}
              </option>
            ))}
          </select>
        </label>

        {/* „Wybór części umowy" — tylko Centrum e-Zdrowia (ticket #3). */}
        {ezdrowie && (
          <label className="block">
            <span className="text-sm">Wybór części umowy *</span>
            <select
              value={projectPart}
              onChange={(e) => setProjectPart(e.target.value)}
              aria-label="Wybór części umowy"
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            >
              <option value="">— wybierz —</option>
              {PROJECT_PARTS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            {!projectPart && (
              <p className="mt-1 text-xs text-muted-foreground">
                Pole wymagane dla Centrum e-Zdrowia.
              </p>
            )}
          </label>
        )}

        <label className="block">
          {/* Ta wartość jest wyświetlana na karcie klienta jako „Numer
              zamówienia", więc etykieta musi mówić to samo — rozjazd „Tytuł"
              tutaj vs „Numer" tam kazał zgadywać, że to jedno i to samo pole. */}
          <span className="text-sm">Numer zamówienia *</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="np. 45767"
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

        {canManageFinance && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-sm">Klient płaci /mc *</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={rateClient}
                  onChange={(e) =>
                    setRateClient(sanitizeDecimalInput(e.target.value))
                  }
                  required
                  className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                  placeholder="np. 215,60"
                />
              </label>
              <label>
                <span className="text-sm">My płacimy kontraktorowi *</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={rateCandidate}
                  onChange={(e) =>
                    setRateCandidate(sanitizeDecimalInput(e.target.value))
                  }
                  required
                  className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                  placeholder="np. 150,40"
                />
              </label>
            </div>

            {margin !== null && (
              <div className="text-sm text-green-700 bg-green-50 px-3 py-2 rounded">
                Marża /mc (przybl.):{" "}
                <strong>{margin.toLocaleString("pl-PL")}</strong> {currency}
                {rateClientNum !== null && rateClientNum > 0 && (
                  <> ({((margin / rateClientNum) * 100).toFixed(1)}%)</>
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
          </>
        )}

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
