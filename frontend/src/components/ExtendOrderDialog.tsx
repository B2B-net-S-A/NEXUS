"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Upload } from "lucide-react";
import { useToast } from "@/components/Toast";
import { extractErrorMsg } from "@/lib/api";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  ContractWithOrdersRead,
  OrderExtractionResult,
} from "@/lib/api/dlPortal";
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
  const user = useAuthStore((state) => state.user);
  const canManageFinance = canManageCandidateFinance(user);
  const latest = contract.orders[0]; // assumed already sorted desc

  // Bez autofillu: ta wartość ląduje na karcie jako „Numer zamówienia", więc
  // podpowiedź „Przedłużenie <imię>" wpisywała tam nazwisko zamiast numeru
  // z dokumentu klienta — i zostawała tam, bo nikt nie poprawia pola, które
  // wygląda na wypełnione.
  const [title, setTitle] = useState("");
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
    canManageFinance
      ? String(latest?.rate_client ?? contract.latest_order_rate_client ?? "")
      : "",
  );
  const [totalValue, setTotalValue] = useState("");
  const [jobId, setJobId] = useState(
    String(latest?.job_id ?? contract.initial_job_id ?? ""),
  );
  // „Część umowy" — tylko Centrum e-Zdrowia (ticket #3). Przedłużenie
  // DZIEDZICZY część z najnowszego zamówienia (edytowalne — zmiana części
  // przy przedłużeniu to legalny scenariusz).
  const ezdrowie = isEzdrowieClient(clientId);
  const [projectPart, setProjectPart] = useState<string>(
    latest?.project_part ?? "",
  );
  const [file, setFile] = useState<File | null>(null);

  // Odczyt PDF ("Zczytaj dane z dokumentu") — świadoma akcja, ODDZIELONA od
  // dodania pliku. Dodanie pliku samo w sobie NIC nie zmienia w formularzu.
  const [extracting, setExtracting] = useState(false);
  // Baner „Sprawdź dane!" — pokazywany gdy odczyt był niepewny (uncertain).
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);

  // Stawki przyjmują grosze wpisane po polsku (przecinek) — parseDecimalInput.
  const rateClientNum = parseDecimalInput(rateClient);

  /** Wstawia odczytane pola. Wypełnia tylko te, które dokument dostarczył —
   *  nie kasuje ręcznych wpisów dla pól nieodczytanych. Wszystkie edytowalne. */
  const applyExtraction = (d: OrderExtractionResult) => {
    if (d.title) setTitle(d.title);
    if (d.start_date) setStartDate(normalizeDateInput(d.start_date));
    if (d.end_date) setEndDate(normalizeDateInput(d.end_date));
    if (canManageFinance) {
      // Kwoty finansowe tylko dla ról z manage_finance (backend i tak je redaguje).
      if (d.rate_client != null) setRateClient(String(d.rate_client));
      if (d.total_value != null) setTotalValue(String(d.total_value));
    }
    setCheckData(Boolean(d.uncertain));
    setCheckReasons(d.uncertain_reasons ?? []);
  };

  const handleExtract = async () => {
    if (!file || extracting) return;
    setExtracting(true);
    try {
      const res = await dlPortalApi.extractOrderPdf(clientId, file);
      applyExtraction(res.data);
      showToast("Odczytano dane z dokumentu", "success");
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      showToast(
        status === 503
          ? "Odczyt AI jest chwilowo niedostępny (wyłączony lub wyczerpany limit). Wpisz dane ręcznie."
          : extractErrorMsg(err),
        "error",
      );
    } finally {
      setExtracting(false);
    }
  };

  const mutation = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("contract_id", String(contract.contract_id));
      fd.append("title", title);
      fd.append("order_status", "active");
      // Normalizacja EU→ISO także tutaj — submit przez Enter nie odpala onBlur,
      // więc surowe „1.6.2026" trafiłoby do backendu jako 422.
      if (startDate) fd.append("start_date", normalizeDateInput(startDate));
      if (endDate) fd.append("end_date", normalizeDateInput(endDate));
      if (canManageFinance) {
        // Candidate-bearing order finance is Admin-only. Operational callers
        // omit amounts entirely instead of sending redacted/default values.
        if (rateClientNum !== null) fd.append("rate_client", String(rateClientNum));
        const totalValueNum = parseDecimalInput(totalValue);
        if (totalValueNum !== null) fd.append("total_value", String(totalValueNum));
      }
      if (jobId) fd.append("job_id", jobId);
      if (ezdrowie && projectPart) fd.append("project_part", projectPart);
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
          if (ezdrowie && !projectPart) {
            showToast("Wybierz część umowy", "error");
            return;
          }
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

        {/* Baner „Sprawdź dane!" — nad tytułem zamówienia, gdy odczyt niepewny. */}
        {checkData && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 px-3 py-2 text-orange-800 dark:border-orange-800 dark:bg-orange-950/40 dark:text-orange-200"
          >
            <AlertTriangle
              className="w-5 h-5 shrink-0 mt-0.5 text-orange-500"
              aria-hidden
            />
            <div className="text-sm">
              <span className="font-bold">Sprawdź dane!</span>
              {checkReasons.length > 0 && (
                <ul className="mt-1 list-disc list-inside text-xs text-orange-700 dark:text-orange-300 space-y-0.5">
                  {checkReasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        <label className="block">
          <span className="text-sm">Numer zamówienia</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="np. 45767"
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">
              Start <span className="text-destructive">*</span>
            </span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              onBlur={(e) => setStartDate(normalizeDateInput(e.target.value))}
              // WYMAGANE, bo bez daty startu przedłużenie jest klasyfikowane
              // jako ROZPOCZĘTE (`splitOrders` traktuje NULL jak przeszłość,
              // a backend sortuje NULL na koniec) i wpada do zwiniętej
              // „Historii zamówień" zamiast do „Przyszłego zamówienia".
              // Użytkownik zgłasza to jako „zamówienie zniknęło".
              required
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

        {canManageFinance && (
          <div className="grid grid-cols-2 gap-3">
            <label>
              <span className="text-sm">Klient płaci (rate_client) /mc</span>
              <input
                type="text"
                inputMode="decimal"
                value={rateClient}
                onChange={(e) =>
                  setRateClient(sanitizeDecimalInput(e.target.value))
                }
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
                onChange={(e) =>
                  setTotalValue(sanitizeDecimalInput(e.target.value))
                }
                className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              />
            </label>
          </div>
        )}

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
          </label>
        )}

        {/* Kafelek załącznika + przycisk odczytu — na dole formularza. Dodanie
            pliku NIE uruchamia odczytu; to robi dopiero pomarańczowy przycisk. */}
        <div className="pt-1">
          <label
            htmlFor="order-pdf-input"
            className="flex items-center gap-3 w-full cursor-pointer rounded-lg border-2 border-dashed border-border bg-muted/40 px-4 py-3 hover:bg-muted/60 transition-colors"
          >
            <Upload
              className="w-5 h-5 text-muted-foreground shrink-0"
              aria-hidden
            />
            <div className="min-w-0">
              <div className="font-bold text-sm">PDF zamówienia od klienta</div>
              <div className="text-xs text-muted-foreground truncate">
                {file ? file.name : "Kliknij, aby dodać plik PDF / DOCX"}
              </div>
            </div>
          </label>
          <input
            id="order-pdf-input"
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={(e) => {
              // Sam wybór pliku NIC nie zmienia w polach — kasuje tylko baner
              // z poprzedniego odczytu (dotyczył innego pliku).
              setFile(e.target.files?.[0] ?? null);
              setCheckData(false);
              setCheckReasons([]);
            }}
            className="sr-only"
          />
          <button
            type="button"
            onClick={handleExtract}
            disabled={!file || extracting}
            className="mt-2 w-full inline-flex items-center justify-center gap-2 rounded-md bg-orange-500 px-3 py-2 text-sm font-semibold text-white hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
          </button>
        </div>

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
