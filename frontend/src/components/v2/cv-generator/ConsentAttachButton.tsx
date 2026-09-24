"use client";

import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { cvGeneratorApi } from "@/lib/api";
import { extractErrorDetail } from "@/lib/cv-generator";

export const CONSENT_IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";
const MAX_MB = 8;

export interface ConsentAttachButtonProps {
  generatedId: number;
  hasConsent: boolean;
  onAttached?: () => void;
  compact?: boolean;
}

/**
 * Zrzut maila ze zgodą kandydata dla JUŻ wygenerowanego CV (wymóg PKO BP).
 * Wgranie podpisuje przypisanie do dokumentu, a dołączenie przerysowuje
 * wszystkie wersje językowe pakietu — bez ponownej generacji i bez AI.
 * Gdy zrzut już jest, ten sam przycisk go wymienia.
 */
export function ConsentAttachButton({ generatedId, hasConsent, onAttached, compact = false }: ConsentAttachButtonProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  async function attach(file: File | undefined) {
    if (!file || busy) return;
    setError(null);
    if (!CONSENT_IMAGE_ACCEPT.split(",").includes(file.type)) {
      setError("Zrzut musi być obrazem PNG, JPG albo WEBP.");
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`Zrzut jest za duży (limit ${MAX_MB} MB).`);
      return;
    }
    setBusy(true);
    try {
      const { data } = await cvGeneratorApi.uploadConsentForGenerated(generatedId, file);
      await cvGeneratorApi.attachConsent(generatedId, data.consent_token);
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-my-list"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-result"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-package"] });
      toast.showSuccess(hasConsent ? "Wymieniono zrzut zgody — CV przerysowane." : "Dołączono zrzut zgody — CV można pobrać.");
      onAttached?.();
    } catch (err) {
      setError((await extractErrorDetail(err)) || "Nie udało się dołączyć zrzutu zgody.");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const label = hasConsent ? "Wymień zrzut" : "Wgraj zrzut maila";
  return (
    <div className="relative space-y-1.5">
      <Button
        type="button"
        variant={hasConsent || compact ? "outline" : "primary"}
        size={compact ? "sm" : "md"}
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        aria-describedby={error ? `${inputId}-error` : undefined}
      >
        {busy ? <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" /> : <Upload aria-hidden className="mr-2 h-4 w-4" />}
        {busy ? "Dołączam zrzut…" : label}
      </Button>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={CONSENT_IMAGE_ACCEPT}
        aria-label={label}
        className="sr-only"
        tabIndex={-1}
        onChange={(event) => void attach(event.target.files?.[0])}
      />
      {error ? (
        <p id={`${inputId}-error`} role="alert" className="text-xs text-destructive">{error}</p>
      ) : null}
    </div>
  );
}
