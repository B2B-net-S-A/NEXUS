"use client";

import { useCallback } from "react";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";

/**
 * Akcja ekranu „Szkolenia”: komunikat sukcesu albo błąd z serwera w tostcie,
 * wynik jako `true`/`false` (formularz wie, czy się zamknąć). Błąd nie leci dalej.
 */
export type RunAction = <T>(
  action: () => Promise<T>,
  success: string | null | ((result: T) => string),
  fallback: string,
) => Promise<boolean>;

export function useRunAction(): RunAction {
  const { showSuccess, showError } = useToast();
  return useCallback<RunAction>(
    async (action, success, fallback) => {
      try {
        const result = await action();
        const message = typeof success === "function" ? success(result) : success;
        if (message) showSuccess(message);
        return true;
      } catch (error) {
        showError(apiErrorMessage(error, fallback));
        return false;
      }
    },
    [showError, showSuccess],
  );
}
