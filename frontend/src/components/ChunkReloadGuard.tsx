"use client";

import { useEffect } from "react";

import { reloadOnceForChunkError } from "@/lib/chunk-reload";

/**
 * Łapie błędy ładowania chunków JS, które nie przechodzą przez granicę błędów
 * (dynamiczne importy w handlerach, prefetch) i przeładowuje stronę raz.
 * Szczegóły: `lib/chunk-reload.ts`.
 */
export function ChunkReloadGuard() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      reloadOnceForChunkError(event.error ?? event.message);
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      reloadOnceForChunkError(event.reason);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
