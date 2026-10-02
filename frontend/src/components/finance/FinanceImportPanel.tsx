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
 * Domyślny miesiąc importu = POPRZEDNI miesiąc w czasie lokalnym.
 *
 * Wyniki dotyczą miesiąca zakończonego — arkusz za wrzesień przychodzi
 * w październiku. Domyślny bieżący miesiąc zapisywał dane pod złym okresem,
 * gdy nikt nie zmienił listy. Data z `getFullYear`/`getMonth` (lokalna), nie
 * z `toISOString` — tamto jest w UTC i 1. dnia miesiąca po północy dawało
 * miesiąc wcześniej.
 */
export function defaultImportPeriod(today: Date): { year: number; month: number } {
  const previous = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  return { year: previous.getFullYear(), month: previous.getMonth() + 1 };
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
  const [year, setYear] = useState(() => defaultImportPeriod(now).year);
  const [month, setMonth] = useState(() => defaultImportPeriod(now).month);

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
    // Jeden wąski pasek z przerywaną ramką (makieta 02.10.2026): etykieta,
    // strefa pliku, miesiąc, przycisk i zdanie o Archiwum w jednym rzędzie.
    <div className="relative rounded-[10px] border border-dashed border-border bg-card px-3.5 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-[13px] font-semibold">
          Importuj plik Excel z wynikami
        </span>
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
            "flex min-h-8 min-w-0 flex-1 basis-60 cursor-pointer items-center gap-2 rounded-md border border-dashed px-2.5 py-1 text-xs transition-colors pointer-coarse:min-h-10",
            dragOver
              ? "border-primary bg-primary/10"
              : "border-border bg-muted/40 hover:bg-muted/60",
            file ? "font-medium text-foreground" : "text-muted-foreground",
          )}
        >
          <Upload className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">
            {file
              ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB`
              : ".xlsx · przeciągnij plik tutaj lub wybierz z dysku · maks. 15 MB"}
          </span>
        </div>

        <select
          value={`${year}-${month}`}
          aria-label="Miesiąc, którego dotyczą dane"
          onChange={(e) => {
            const [y, m] = e.target.value.split("-").map(Number);
            setYear(y);
            setMonth(m);
          }}
          className="h-8 rounded-md border border-border bg-background px-2.5 text-sm font-medium pointer-coarse:h-10"
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
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 pointer-coarse:min-h-10"
        >
          {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          {/* Przycisk WYSYŁA import — „Wybierz plik” obiecywało okno wyboru,
              a wybór pliku to pole obok. */}
          Importuj plik
        </button>

        <p className="flex basis-full items-center gap-1.5 text-xs text-muted-foreground 2xl:ml-auto 2xl:basis-auto">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          Import miesiąca, który ma już dane, wymaga potwierdzenia — poprzednia
          wersja trafia do Archiwum.
        </p>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx"
        className="sr-only"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />

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
              <p className="rounded-md border border-warning/40 bg-warning-muted p-2 text-warning-muted-foreground">
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
