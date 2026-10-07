"use client";

/**
 * Podgląd CV dla klienta w panelu osoby i w przeglądzie Delivery Leada
 * (wydzielony z `DlReviewPanel`, jeden panel osoby, 04.10.2026).
 *
 * CV firmowe etapu (po poprawkach QC) ma pierwszeństwo przed surowym plikiem
 * z generatora — DL wysyła klientowi to, co ogląda. Bez zgody RODO serwer
 * odmawia pobrania (409), więc podgląd prosi o zrzut zamiast renderować.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { ConsentAttachButton } from "@/components/v2/cv-generator/ConsentAttachButton";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import { alignB2bLetterheadPreview } from "@/lib/cv-docx-preview";
import { renderDocxSafely } from "@/lib/docx-preview-safe";
import { fetchStageCvFile } from "@/lib/stage-cv-file";

// ── CV wygenerowane automatycznie ────────────────────────────────────────────

interface GeneratedCvRow {
  id: number;
  status: "processing" | "ready" | "failed" | string;
  filename: string;
  origin?: string;
  needs_review?: boolean;
  error_message?: string | null;
  created_at?: string | null;
  /** Reguła klienta wymaga zrzutu zgody RODO, a dokument go nie ma — pobranie odpowie 409. */
  consent_missing?: boolean;
}

function pickCv(rows: GeneratedCvRow[] | undefined): GeneratedCvRow | null {
  if (!rows?.length) return null;
  // Lista stawia auto-CV do przeglądu pierwsze; bierzemy pierwsze gotowe.
  return rows.find((r) => r.status === "ready") ?? rows[0];
}

export function StageCvPreview({
  candidateId,
  jobId,
  cvStageId,
  fill = false,
}: {
  candidateId: number;
  jobId: number;
  /** Etap z CV firmowym pary — gdy jest, podgląd i DOCX idą z CV etapu (po QC). */
  cvStageId?: number | null;
  /**
   * Podgląd obok formularza screeningu (0424): bez limitu 28 rem — wysokość
   * daje kolumna podglądu, a przewija się sam dokument.
   */
  fill?: boolean;
}) {
  const { showError } = useToast();
  const query = useQuery({
    queryKey: ["cv-generated", "dl-review", candidateId, jobId],
    queryFn: () =>
      api
        .get<GeneratedCvRow[]>("/api/cv-generator/generated", {
          params: { candidate_id: candidateId, job_id: jobId, limit: 10 },
        })
        .then((r) => r.data),
    // Auto-CV generuje się w tle po weryfikacji — odpytujemy, dopóki trwa.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => r.status === "processing") ? 5000 : false,
  });
  const cv = pickCv(query.data);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [render, setRender] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [renderError, setRenderError] = useState<string | null>(null);
  // Runda 7 (R7-X4-2): CV firmowe etapu (po poprawkach QC) ma pierwszeństwo
  // przed surowym plikiem z generatora — DL wysyła klientowi to, co ogląda.
  const fromStage = cvStageId != null && cvStageId > 0;
  // Bez zgody RODO serwer odmawia pobrania pliku (409) — nie próbujemy go
  // renderować, tylko prosimy o zrzut.
  const consentMissing = !fromStage && cv?.status === "ready" && cv.consent_missing === true;
  const readyId = cv?.status === "ready" && !consentMissing ? cv.id : null;
  const sourceKey = fromStage ? `stage:${cvStageId}` : readyId != null ? `generated:${readyId}` : null;

  useEffect(() => {
    if (sourceKey == null) return;
    let cancelled = false;
    setRender("loading");
    setRenderError(null);
    (async () => {
      try {
        const blob = fromStage
          ? (await fetchStageCvFile(cvStageId as number)).blob
          : ((
              await api.get(`/api/cv-generator/generated/${readyId}/docx`, {
                responseType: "blob",
              })
            ).data as Blob);
        const host = hostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = "";
        await renderDocxSafely(blob, host, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          useBase64URL: true,
        });
        if (cancelled) return;
        alignB2bLetterheadPreview(host);
        setRender("ready");
      } catch (error) {
        if (cancelled) return;
        setRender("error");
        // 409 `consent_required` niesie polski komunikat serwera.
        setRenderError(fromStage ? apiErrorMessage(error, "") || null : null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `fromStage`/`cvStageId`/`readyId` są zawarte w `sourceKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  const download = async () => {
    try {
      if (fromStage) {
        const file = await fetchStageCvFile(cvStageId as number);
        downloadBlob(file.blob, file.filename || "CV.docx");
        return;
      }
      if (!cv) return;
      const res = await api.get(`/api/cv-generator/generated/${cv.id}/docx`, { responseType: "blob" });
      downloadBlob(res.data as Blob, cv.filename);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać CV."));
    }
  };

  const previewBox = (
    <div
      className={
        fill
          ? "relative min-h-40 overflow-auto rounded-lg border border-border bg-muted/30 p-2"
          : "relative max-h-[28rem] min-h-40 overflow-auto rounded-lg border border-border bg-muted/30 p-2"
      }
    >
      {render !== "ready" ? (
        <p className="absolute inset-0 flex items-center justify-center px-3 text-center text-xs">
          {render === "error" ? (
            <span role="alert" className="text-destructive">
              {renderError ?? "Nie udało się wyświetlić podglądu — pobierz plik DOCX."}
            </span>
          ) : (
            <span className="flex items-center text-muted-foreground">
              <Loader2 className="mr-1.5 size-3 animate-spin" aria-hidden /> Renderowanie podglądu…
            </span>
          )}
        </p>
      ) : null}
      <div ref={hostRef} data-testid="dl-review-cv-host" className="docx-preview-host mx-auto" />
    </div>
  );

  return (
    <section aria-label="CV kandydata" className="space-y-2">
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">CV</h3>
        {cv?.origin === "auto" ? (
          <Badge size="sm" variant="soft">
            Wygenerowane automatycznie
          </Badge>
        ) : null}
        {cv?.needs_review ? (
          <Badge size="sm" variant="warning">
            Do przeglądu
          </Badge>
        ) : null}
        {fromStage || (cv?.status === "ready" && !consentMissing) ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => void download()}>
            <Download className="h-3.5 w-3.5" />
            Pobierz DOCX
          </Button>
        ) : null}
      </header>
      {fromStage ? (
        previewBox
      ) : query.isLoading ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie CV…
        </p>
      ) : query.isError ? (
        <p role="alert" className="text-xs text-destructive">
          Nie udało się wczytać listy CV.{" "}
          <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
            Ponów
          </button>
        </p>
      ) : !cv ? (
        <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
          Dla tej rekrutacji nie ma jeszcze wygenerowanego CV — wygeneruj je z panelu osoby na Tablicy.
        </p>
      ) : cv.status === "processing" ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> CV jeszcze się generuje…
        </p>
      ) : cv.status !== "ready" ? (
        <p role="alert" className="text-xs text-destructive">
          Generowanie CV nie powiodło się{cv.error_message ? `: ${cv.error_message}` : "."}
        </p>
      ) : consentMissing ? (
        <div
          role="note"
          data-testid="dl-review-consent-missing"
          className="space-y-2 rounded-lg border border-destructive/25 bg-destructive-muted px-3 py-3 text-xs text-destructive-muted-foreground"
        >
          <p className="font-medium">Brak zgody RODO (PKO BP)</p>
          <p>
            Reguła klienta wymaga zrzutu maila ze zgodą kandydata na końcu CV. Bez niego CV
            nie da się pobrać ani obejrzeć — dołącz zrzut, a dokument przerysuje się bez
            ponownej generacji.
          </p>
          <ConsentAttachButton
            compact
            generatedId={cv.id}
            hasConsent={false}
            onAttached={() => void query.refetch()}
          />
        </div>
      ) : (
        previewBox
      )}
    </section>
  );
}
