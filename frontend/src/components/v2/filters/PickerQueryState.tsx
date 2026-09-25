"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Stan listy w pickerze filtra (`CommandList`): ładowanie albo awaria.
 *
 * `CommandEmpty` („Brak klientów.”) renderował się także w trakcie ładowania
 * i po błędzie zapytania — awaria wyglądała jak pusty słownik, a rekruter
 * uznawał, że klienta nie ma w bazie. Pusty stan pokazujemy dopiero przy
 * sukcesie zapytania; tu jest wszystko, co wcześniej.
 */
export function PickerQueryState({
  isPending,
  isError,
  onRetry,
  loadingLabel,
  errorLabel,
}: {
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  loadingLabel: string;
  errorLabel: string;
}) {
  if (isError) {
    return (
      <div
        role="alert"
        className="flex flex-col items-center gap-2 px-3 py-4 text-center text-sm text-muted-foreground"
      >
        <span className="flex items-center gap-1.5">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          {errorLabel}
        </span>
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Ponów
        </button>
      </div>
    );
  }
  if (isPending) {
    return (
      <div role="status" className="px-3 py-4 text-center text-sm text-muted-foreground">
        {loadingLabel}
      </div>
    );
  }
  return null;
}
