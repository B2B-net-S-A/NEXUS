"use client";

/**
 * Sekcja „CV” panelu osoby — czy kopia CV tej rekrutacji jest aktualna
 * (13.10.2026, „Nowe CV w rekrutacji”, D4 i ochrona przed cudzym CV).
 *
 * Dwa sygnały pod listą stanu CV, widoczne dla osoby, która może wgrać CV:
 * - „W profilu jest nowsze CV” — CV wpadło mailem albo ktoś wgrał je w profilu
 *   lub w innej rekrutacji; „Użyj w tej rekrutacji” podmienia kopię etapu
 *   (`…/cv/original/refresh`, ta sama trasa co dawne „Aktualizuj snapshot”);
 * - „AI czyta nowe CV” — przez kilka minut po wgraniu z rekrutacji.
 *
 * Gdy bramka tożsamości uzna wgrany plik za CV innej osoby, serwer sam
 * przywraca kopię etapu (`quarantine_restore`) — mówi o tym zdanie
 * „Oryginał CV” (`originalCvSentence`).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCcw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { candidateStageCvApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { newerProfileCv, type DockOriginalCv, type DockProfileCvDoc } from "@/lib/dock-cv-summary";
import { formatDate } from "@/lib/utils";

/** Jak długo po wgraniu pokazujemy „AI czyta nowe CV”. */
export const PROFILE_READ_WINDOW_MS = 3 * 60_000;

export interface DockCvCandidate {
  cv_parsed_at?: string | null;
}

/** Czy odczyt AI wgranego przed chwilą CV jeszcze trwa. */
export function profileReadPending(
  uploadedAt: number | null,
  candidate: DockCvCandidate | null,
  now: number = Date.now(),
): boolean {
  if (uploadedAt == null || now - uploadedAt > PROFILE_READ_WINDOW_MS) return false;
  const parsedAt = candidate?.cv_parsed_at ? Date.parse(candidate.cv_parsed_at) : NaN;
  // Zegar przeglądarki i serwera się rozjeżdżają — margines minuty.
  return !(Number.isFinite(parsedAt) && parsedAt >= uploadedAt - 60_000);
}

export function DockCvFreshness({
  stageId,
  original,
  profileDocs,
  candidate,
  uploadedAt,
  onShowProfileCv,
  canRefresh = true,
}: {
  stageId: number;
  original: DockOriginalCv;
  profileDocs: readonly DockProfileCvDoc[] | undefined;
  candidate: DockCvCandidate | null;
  uploadedAt: number | null;
  onShowProfileCv: (documentId: number) => void;
  /**
   * „Użyj w tej rekrutacji” podmienia kopię etapu — tylko z prawem wgrania CV.
   * Podgląd CV po „Rozwiń” pokazuje ramkę każdemu (15.10.2026, D4): osoba bez
   * tego prawa widzi, że pobiera starsze CV, i może otworzyć nowsze.
   */
  canRefresh?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const refresh = useMutation({
    mutationFn: () => candidateStageCvApi.original.refresh(stageId),
    onSuccess: (response) => {
      queryClient.setQueryData(["cv-original", stageId], response.data);
      void queryClient.invalidateQueries({ queryKey: ["cv-qc", stageId] });
      showSuccess("CV z profilu jest teraz CV tej rekrutacji.");
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się podmienić CV w tej rekrutacji.")),
  });

  const newer = newerProfileCv(original, profileDocs);
  const reading = profileReadPending(uploadedAt, candidate);
  if (!newer && !reading) return null;

  return (
    <div className="space-y-2" data-testid="dock-cv-freshness">
      {reading ? (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin" aria-hidden />
          Profil: AI czyta nowe CV, odświeży się za około minutę.
        </p>
      ) : null}
      {newer ? (
        <div className="space-y-1.5 rounded-md border border-success/30 bg-success-muted px-2.5 py-2 text-xs text-success-muted-foreground">
          <p>
            <span className="font-semibold">W profilu jest nowsze CV</span> · {newer.filename} ·{" "}
            {formatDate(newer.uploaded_at ?? newer.created_at)}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {canRefresh ? (
              <Button size="sm" variant="outline" loading={refresh.isPending} onClick={() => refresh.mutate()}>
                <RefreshCcw className="h-3.5 w-3.5" aria-hidden /> Użyj w tej rekrutacji
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => onShowProfileCv(newer.id)}>
              Pokaż
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
