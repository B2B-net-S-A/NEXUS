"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Loader2, Upload } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";
import {
  financeApi,
  type FinanceHeaderMismatch,
  type FinanceImportResult,
  type FinancePeriodConflict,
} from "@/lib/api/finance";

const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;

const MONTHS = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

interface Props {
  onImported: (result: FinanceImportResult) => void;
}

/**
 * Wgrywanie miesięcznego arkusza.
 *
 * Okres wybiera CZŁOWIEK (pkt 6 ticketu) — arkusz nie niesie jednoznacznej
 * informacji o miesiącu, więc nie zgadujemy go z nazwy pliku.
 */
export function FinanceImportPanel({ onImported }: Props) {
  const { showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const now = new Date();

  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState("");
  const [headerError, setHeaderError] = useState<FinanceHeaderMismatch | null>(null);
  const [conflict, setConflict] = useState<FinancePeriodConflict | null>(null);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  function pick(next: File | null) {
    setError("");
    setHeaderError(null);
    if (!next) return;
    if (!next.name.toLowerCase().endsWith(".xlsx")) {
      setError("Dozwolone są wyłącznie pliki .xlsx");
      setFile(null);
      return;
    }
    if (next.size > MAX_UPLOAD_BYTES) {
      setError("Plik przekracza 15 MB.");
      setFile(null);
      return;
    }
    setFile(next);
  }

  const mutation = useMutation({
    mutationFn: async (replace: boolean) => {
      if (!file) throw new Error("Nie wybrano pliku");
      const res = await financeApi.importWorkbook(file, year, month, replace);
      return res.data;
    },
    onSuccess: (result) => {
      setConflict(null);
      setFile(null);
      // Bez tego ponowny wybór TEGO SAMEGO pliku nie odpali zdarzenia change.
      if (fileInputRef.current) fileInputRef.current.value = "";
      showToast(
        `Zaimportowano ${result.imported} wierszy` +
          (result.needs_completion > 0
            ? `, w tym ${result.needs_completion} z brakującymi danymi do uzupełnienia`
            : ""),
        "success",
      );
      onImported(result);
    },
    onError: (err: unknown) => {
      const response = (
        err as { response?: { status?: number; data?: { detail?: unknown } } }
      )?.response;
      const detail = response?.data?.detail as
        | FinancePeriodConflict
        | FinanceHeaderMismatch
        | string
        | undefined;

      if (response?.status === 409 && detail && typeof detail === "object") {
        setConflict(detail as FinancePeriodConflict);
        return;
      }
      if (
        response?.status === 422 &&
        detail &&
        typeof detail === "object" &&
        "missing" in detail
      ) {
        setHeaderError(detail as FinanceHeaderMismatch);
        return;
      }
      setError(
        typeof detail === "string"
          ? detail
          : err instanceof Error
            ? err.message
            : "Nie udało się zaimportować pliku.",
      );
    },
  });

  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            pick(e.dataTransfer.files?.[0] ?? null);
          }}
          onClick={() => fileInputRef.current?.click()}
          className={cn(
            "flex flex-1 cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed px-4 py-3 transition-colors",
            dragOver
              ? "border-primary bg-primary/10"
              : "border-border bg-muted/40 hover:bg-muted/60",
          )}
        >
          <Upload className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0">
            <div className="text-sm font-semibold">Importuj plik Excel z wynikami</div>
            <div className="truncate text-xs text-muted-foreground">
              {file
                ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB`
                : ".xlsx · przeciągnij plik tutaj lub wybierz z dysku · maks. 15 MB"}
            </div>
          </div>
        </div>

        <select
          value={`${year}-${month}`}
          aria-label="Miesiąc, którego dotyczą dane"
          onChange={(e) => {
            const [y, m] = e.target.value.split("-").map(Number);
            setYear(y);
            setMonth(m);
          }}
          className="rounded-md border border-border bg-background px-3 py-2 text-sm font-medium"
        >
          {Array.from({ length: 24 }, (_, i) => {
            const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
            const y = d.getFullYear();
            const m = d.getMonth() + 1;
            return (
              <option key={`${y}-${m}`} value={`${y}-${m}`}>
                {MONTHS[m - 1]} {y}
              </option>
            );
          })}
        </select>

        <button
          type="button"
          onClick={() => mutation.mutate(false)}
          disabled={!file || mutation.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Wybierz plik
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx"
        className="sr-only"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />

      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <AlertCircle className="h-3.5 w-3.5" aria-hidden />
        Import dla miesiąca, dla którego dane już istnieją, wymaga potwierdzenia
        zastąpienia — poprzednia wersja zostanie zapisana w Archiwum.
      </p>

      {error && (
        <p className="mt-2 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {headerError && (
        <div
          className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm"
          role="alert"
        >
          <p className="font-medium text-destructive">
            Plik nie ma wymaganych kolumn — import odrzucony.
          </p>
          {headerError.missing.length > 0 && (
            <p className="mt-1 text-xs">
              <span className="font-medium">Brakujące:</span>{" "}
              {headerError.missing.join(", ")}
            </p>
          )}
          {headerError.unexpected.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="font-medium">Nierozpoznane:</span>{" "}
              {headerError.unexpected.join(", ")}
            </p>
          )}
        </div>
      )}

      {conflict && (
        <AppModal
          open
          onOpenChange={(next) => {
            if (!next) setConflict(null);
          }}
          title="Zastąpić poprzednią wersję?"
          footer={
            <>
              <button
                type="button"
                onClick={() => setConflict(null)}
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
              >
                Anuluj
              </button>
              <button
                type="button"
                onClick={() => mutation.mutate(true)}
                disabled={mutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:opacity-90 disabled:opacity-50"
              >
                {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                Zastąp
              </button>
            </>
          }
        >
          <div className="space-y-2 text-sm">
            <p>
              Dla <strong>{MONTHS[conflict.month - 1]} {conflict.year}</strong> już
              istnieją zaimportowane dane (<strong>{conflict.row_count}</strong>{" "}
              {conflict.row_count === 1 ? "wiersz" : "wierszy"}).
            </p>
            {conflict.edited_row_count > 0 && (
              // Liczba ręcznych poprawek jest tu istotą ostrzeżenia: bez niej
              // nie da się ocenić, ile pracy przepadnie.
              <p className="rounded-md border border-amber-400/50 bg-amber-50 p-2 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                <strong>{conflict.edited_row_count}</strong>{" "}
                {conflict.edited_row_count === 1 ? "wiersz zawiera" : "wierszy zawiera"}{" "}
                ręczne poprawki, które zostaną zastąpione danymi z nowego pliku.
              </p>
            )}
            <p className="text-muted-foreground">
              Poprzednia wersja nie zostanie usunięta — trafi do Archiwum ze statusem
              „Zastąpiony" i można ją przywrócić.
            </p>
          </div>
        </AppModal>
      )}
    </div>
  );
}
