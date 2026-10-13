"use client";

/**
 * „CV firmowe powstało z poprzedniego CV” — sekcja „CV” panelu osoby
 * (13.10.2026, D3 „Nowego CV w rekrutacji”).
 *
 * Po wgraniu nowego CV w rekrutacji (albo „Użyj w tej rekrutacji”) szkic CV
 * firmowego dalej opisuje stary plik. Nic nie generuje się samo — automat
 * nadpisałby poprawki rekrutera. Ramka mówi o tym i daje „Wygeneruj od nowa”.
 * Generator nigdy nie podmienia istniejącego szkicu (`attach_as_stage_draft`),
 * więc gotowa nowa wersja pojawia się tutaj jako „Użyj nowej wersji” — ten sam
 * zapis co w karcie „CV do klienta” (`branded.selectGenerated`). Zatwierdzone
 * CV i wysłane linki zostają bez zmian.
 */

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Sparkles } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { useCvToClientRows } from "@/hooks/useCvToClientRows";
import { candidateStageCvApi, type CVBrandedState } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cvToClientRowsQueryKey, resolveCvToClient, stageBrandedQueryKey } from "@/lib/cv-to-client";
import { companyCvStale, companyDraftSince, type DockOriginalCv } from "@/lib/dock-cv-summary";
import { formatDate } from "@/lib/utils";

const POLL_MS = 4000;
/** Po tylu minutach przestajemy czekać na nową wersję — jak karta „CV do klienta”. */
const PENDING_TIMEOUT_MS = 5 * 60_000;

function dismissKey(stageId: number): string {
  return `nexus:company-cv-stale-dismissed:${stageId}`;
}

function readDismissed(stageId: number): string | null {
  try {
    return window.localStorage.getItem(dismissKey(stageId));
  } catch {
    return null;
  }
}

function writeDismissed(stageId: number, snapshotAt: string): void {
  try {
    window.localStorage.setItem(dismissKey(stageId), snapshotAt);
  } catch {
    // Pamięć przeglądarki zablokowana — ramka wróci przy następnym otwarciu.
  }
}

export function CompanyCvStaleNotice({
  stageId,
  candidateId,
  candidateName,
  jobId,
  branded,
  original,
}: {
  stageId: number;
  candidateId: number;
  candidateName: string;
  jobId: number;
  /** CV etapu z doku (`["cv-branded", stageId]`) — tylko własne CV tego etapu. */
  branded: CVBrandedState | undefined;
  original: DockOriginalCv;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [pending, setPending] = useState<{ id: number; since: number } | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);
  // Odczyt w efekcie: pierwszy render taki jak na serwerze.
  useEffect(() => setDismissed(readDismissed(stageId)), [stageId]);

  const snapshotAt = original.kind === "snapshot" ? original.date : null;
  // Wiersze generatora są potrzebne tylko, gdy kopia CV została podmieniona ręcznie.
  const replaced =
    original.kind === "snapshot" &&
    (original.source === "manual_upload" || original.source === "manual_refresh") &&
    branded?.status === "draft";
  const waiting = pending != null && Date.now() - pending.since < PENDING_TIMEOUT_MS;
  const rowsQuery = useCvToClientRows(candidateId, jobId, {
    enabled: replaced,
    refetchInterval: waiting ? POLL_MS : false,
  });
  const state = resolveCvToClient({ branded, rows: rowsQuery.data, pendingGeneratedId: pending?.id ?? null });
  // Nowa wersja liczy się dopiero, gdy powstała z podmienionego CV.
  const freshVersion =
    state.candidate && snapshotAt && Date.parse(state.candidate.created_at ?? "") > Date.parse(snapshotAt)
      ? state.candidate
      : null;

  useEffect(() => {
    if (pending && (freshVersion || state.failed)) setPending(null);
  }, [pending, freshVersion, state.failed]);

  const attach = useMutation({
    mutationFn: (generatedId: number) =>
      candidateStageCvApi.branded.selectGenerated(stageId, generatedId, branded?.edit_revision ?? 0),
    onSuccess: (response) => {
      queryClient.setQueryData(stageBrandedQueryKey(stageId), response.data);
      void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
      void queryClient.invalidateQueries({ queryKey: ["cv-qc", stageId] });
      showSuccess("CV firmowe z nowego CV podpięte do tej rekrutacji.");
    },
    onError: (error) =>
      showError(
        apiErrorMessage(
          error,
          "Nie udało się podpiąć CV — szkic mógł zmienić się w innym oknie. Odśwież i spróbuj ponownie.",
        ),
      ),
  });

  const stale = companyCvStale({
    brandedStatus: branded?.status,
    original,
    draftSince: companyDraftSince(branded, rowsQuery.data),
  });
  if (!stale || !snapshotAt || (dismissed === snapshotAt && !waiting && !freshVersion)) return null;

  return (
    <div
      data-testid="company-cv-stale"
      className="space-y-1.5 rounded-md border border-warning/30 bg-warning-muted px-2.5 py-2 text-xs text-warning-muted-foreground"
    >
      {freshVersion ? (
        <>
          <p>
            <span className="font-semibold">Nowe CV firmowe gotowe</span>
            {freshVersion.created_at ? ` (${formatDate(freshVersion.created_at)})` : ""}. Zastąpi bieżący szkic;
            zatwierdzone wersje zostają.
          </p>
          <Button
            size="sm"
            variant="outline"
            loading={attach.isPending}
            disabled={attach.isPending}
            onClick={() => attach.mutate(freshVersion.id)}
          >
            Użyj nowej wersji
          </Button>
        </>
      ) : waiting || state.generating ? (
        <p className="flex items-center gap-1.5">
          <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden /> Generuje się CV firmowe z nowego CV…
        </p>
      ) : (
        <>
          <p className="flex items-start gap-1.5">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              <span className="font-semibold">CV firmowe powstało z poprzedniego CV.</span> Szkic nie zawiera zmian
              z nowego pliku.
            </span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setGeneratorOpen(true)}>
              <Sparkles className="h-3.5 w-3.5" aria-hidden /> Wygeneruj od nowa
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                writeDismissed(stageId, snapshotAt);
                setDismissed(snapshotAt);
              }}
            >
              Zostaw obecne
            </Button>
          </div>
        </>
      )}
      {generatorOpen ? (
        <CvGeneratorDialog
          open={generatorOpen}
          onOpenChange={setGeneratorOpen}
          candidateId={candidateId}
          candidateName={candidateName}
          jobId={jobId}
          onEnqueued={(generatedId) => {
            setGeneratorOpen(false);
            setPending({ id: generatedId, since: Date.now() });
            void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
            showSuccess("CV firmowe generuje się w tle. Gdy będzie gotowe, podepniesz je tutaj.");
          }}
        />
      ) : null}
    </div>
  );
}
