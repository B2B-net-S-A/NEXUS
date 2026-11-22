"use client";

/**
 * Podgląd PDF nowego CV obok formularzy „Strona 1” i „Stanowiska” (22.11.2026).
 *
 * - pierwszy podgląd od razu, kolejny dopiero `PREVIEW_DEBOUNCE_MS` po
 *   ostatniej zmianie treści albo dodatków strony 1,
 * - tylko gdy formularz jest na ekranie i karta przeglądarki widoczna,
 * - najwyżej `PREVIEW_MAX_PER_MINUTE` żądań na minutę (trasa ma limit 20/min
 *   na osobę, wspólny z „Jak u klienta” i „Pobierz PDF”),
 * - ostatni dobry obraz zostaje na czas odświeżania i po błędzie; błąd tej
 *   samej treści nie ponawia się sam (pętla żądań), tylko po zmianie albo
 *   „Ponów”.
 */

import { useEffect, useRef, useState } from "react";

import type { AuthenticatedDownload } from "@/lib/authenticated-files";
import { apiErrorMessage } from "@/lib/api-error";
import { previewDelay, renderInfo, type NewCvRenderInfo } from "@/lib/cv-new-preview";

export interface NewCvPreviewFile {
  blob: Blob;
  info: NewCvRenderInfo;
  /** Stan treści, z którego powstał PDF. */
  key: string;
}

export interface NewCvPreview {
  file: NewCvPreviewFile | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

function pageVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

export function useNewCvPreview({
  load,
  changeKey,
  active,
}: {
  load: () => Promise<AuthenticatedDownload>;
  /** Zmienia się przy każdej zmianie treści albo dodatków strony 1. */
  changeKey: string;
  active: boolean;
}): NewCvPreview {
  const [file, setFile] = useState<NewCvPreviewFile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(pageVisible);
  // Po każdym żądaniu: przelicz, czy treść nie zmieniła się w trakcie.
  const [settled, setSettled] = useState(0);
  const sent = useRef<number[]>([]);
  const lastChangeAt = useRef<number | null>(null);
  const firstKey = useRef(changeKey);
  const failedKey = useRef<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (changeKey !== firstKey.current) lastChangeAt.current = Date.now();
  }, [changeKey]);

  useEffect(() => {
    const onVisibility = () => setVisible(pageVisible());
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!active || !visible || inFlight.current) return;
    if (file?.key === changeKey || failedKey.current === changeKey) return;
    const now = Date.now();
    const wait = previewDelay({
      now,
      lastChangeAt: file ? lastChangeAt.current : null,
      sent: sent.current,
    });
    const key = changeKey;
    const timer = setTimeout(() => {
      inFlight.current = true;
      setLoading(true);
      const at = Date.now();
      sent.current = [...sent.current.filter((time) => at - time < 60_000), at];
      loadRef
        .current()
        .then((result) => {
          if (!mounted.current) return;
          failedKey.current = null;
          setError(null);
          setFile({ blob: result.blob, info: renderInfo(result.headers), key });
        })
        .catch((reason: unknown) => {
          if (!mounted.current) return;
          failedKey.current = key;
          setError(apiErrorMessage(reason, "Nie udało się odświeżyć podglądu strony."));
        })
        .finally(() => {
          inFlight.current = false;
          if (!mounted.current) return;
          setLoading(false);
          setSettled((count) => count + 1);
        });
    }, wait);
    return () => clearTimeout(timer);
  }, [active, visible, changeKey, file, settled]);

  const retry = () => {
    failedKey.current = null;
    setError(null);
    setSettled((count) => count + 1);
  };

  return { file, loading, error, retry };
}
