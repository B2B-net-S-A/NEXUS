"use client";

import * as React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface WidgetStateProps {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty?: boolean;
  onRetry?: () => void;
  loadingFallback: React.ReactNode;
  emptyFallback?: React.ReactNode;
  errorFallback?: React.ReactNode;
  children: React.ReactNode;
}

// Renders one of {loading | error | empty | data} based on React Query state.
// Without this, widgets stay mounted in skeleton state when a query errors.
export function WidgetState({
  isLoading,
  isError,
  error,
  isEmpty,
  onRetry,
  loadingFallback,
  emptyFallback,
  errorFallback,
  children,
}: WidgetStateProps) {
  if (isLoading) return <>{loadingFallback}</>;
  if (isError)
    return <>{errorFallback ?? <WidgetErrorBlock error={error} onRetry={onRetry} />}</>;
  if (isEmpty && emptyFallback) return <>{emptyFallback}</>;
  return <>{children}</>;
}

function errorMessage(error: unknown): string {
  const e = error as { response?: { status?: number }; message?: string } | null;
  const status = e?.response?.status;
  if (status === 403) return "Brak uprawnień do tego widoku.";
  if (status === 404) return "Nie znaleziono danych.";
  if (status && status >= 500) return "Błąd serwera. Spróbuj ponownie za chwilę.";
  if (status && status >= 400) return "Żądanie zostało odrzucone.";
  return e?.message ?? "Spróbuj ponownie za chwilę.";
}

// Reusable error block — exported so callers can compose it inside their own
// container (e.g. a Card) when a bare error block looks out of place.
export function WidgetErrorBlock({
  error,
  onRetry,
  title = "Nie udało się załadować danych.",
}: {
  error?: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center py-6 text-center"
    >
      <AlertCircle className="h-8 w-8 mb-2 text-destructive/60" />
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="text-xs mt-1 text-muted-foreground">{errorMessage(error)}</p>
      {onRetry && (
        <Button
          variant="outline"
          size="sm"
          onClick={onRetry}
          className="mt-3"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Spróbuj ponownie
        </Button>
      )}
    </div>
  );
}
