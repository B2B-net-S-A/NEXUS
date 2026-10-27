"use client";

import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { ConsentCheckNotice } from "@/components/v2/cv/ConsentCheckNotice";
import { candidateStageCvApi, cvGeneratorApi } from "@/lib/api";
import { consentAttachedMessage, needsConsentDecision, type ConsentCheck } from "@/lib/consent-check";
import { extractErrorDetail } from "@/lib/cv-generator";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";

export const CONSENT_IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";
const MAX_MB = 8;

export interface ConsentAttachButtonProps {
  /** Wygenerowane CV, do którego dołączamy zgodę (cały pakiet językowy). */
  generatedId?: number;
  /**
   * CV etapu BEZ dokumentu generatora (plik Word, kopia z innej rekrutacji,
   * przepięcie — 12.10.2026): zgoda wiązana z kandydatem i etapem, na którym
   * leży CV. Dokładnie jedno z `generatedId` / `stageCopy`.
   */
  stageCopy?: { candidateId: number; stageId: number };
  hasConsent: boolean;
  onAttached?: () => void;
  compact?: boolean;
}

/**
 * Zrzut maila ze zgodą kandydata dla JUŻ gotowego CV (wymóg PKO BP).
 * Wgranie podpisuje przypisanie do dokumentu, a dołączenie przerysowuje
 * wszystkie wersje językowe pakietu — bez ponownej generacji i bez AI.
 * Gdy zrzut już jest, ten sam przycisk go wymienia.
 *
 * 27.10.2026 (F37): wgranie sprawdza zrzut. Niepasujący wraca bez
 * pokwitowania — karta pokazuje uwagi, a „zapisz mimo to” wysyła TEN SAM
 * plik jeszcze raz z powodem rekrutera.
 */
export function ConsentAttachButton({ generatedId, stageCopy, hasConsent, onAttached, compact = false }: ConsentAttachButtonProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState<{ file: File; check: ConsentCheck } | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  async function attach(file: File | undefined, overrideReason?: string) {
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
      const upload = stageCopy
        ? await cvGeneratorApi.uploadConsentForStage(stageCopy.candidateId, stageCopy.stageId, file, overrideReason)
        : generatedId != null
          ? await cvGeneratorApi.uploadConsentForGenerated(generatedId, file, overrideReason)
          : null;
      if (!upload) return;
      const { data } = upload;
      if (needsConsentDecision(data) && data.check) {
        setMismatch({ file, check: data.check });
        return;
      }
      if (!data.consent_token) throw new Error("Missing consent binding");
      if (stageCopy) {
        const attached = await candidateStageCvApi.branded.attachConsent(stageCopy.stageId, data.consent_token);
        queryClient.setQueryData(stageBrandedQueryKey(stageCopy.stageId), attached.data);
      } else if (generatedId != null) {
        await cvGeneratorApi.attachConsent(generatedId, data.consent_token);
      }
      setMismatch(null);
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-result"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-package"] });
      toast.showSuccess(consentAttachedMessage(data.check, hasConsent));
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
      {/* Przy niepasującym zrzucie „Wgraj inny zrzut” stoi w uwagach poniżej. */}
      {mismatch ? null : (
        <Button
          type="button"
          variant={hasConsent || compact ? "outline" : "primary"}
          size={compact ? "sm" : "md"}
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          aria-describedby={error ? `${inputId}-error` : undefined}
        >
          {busy ? <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" /> : <Upload aria-hidden className="mr-2 h-4 w-4" />}
          {busy ? "Sprawdzam zrzut…" : label}
        </Button>
      )}
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
      {mismatch ? (
        <ConsentCheckNotice
          check={mismatch.check}
          busy={busy}
          onPickAnother={() => inputRef.current?.click()}
          onOverride={(reason) => void attach(mismatch.file, reason)}
        />
      ) : null}
    </div>
  );
}
