"use client";

/**
 * „Wybierz gotowe CV z profilu” — screening, 09.10.2026.
 *
 * Do tej daty CV firmowe rekrutacji dało się zacząć wyłącznie od generacji,
 * a w screeningu zakładka „CV firmowe” mówiła tylko, że CV jeszcze nie ma.
 * 34 z 50 osób w screeningu miało wtedy gotowe CV w profilu (plik Word
 * „…B2B…”), 13 — CV z generatora. Lista pokazuje oba źródła; „Wybierz”
 * podpina CV jako SZKIC tej rekrutacji (plik w profilu zostaje nietknięty),
 * a dalej działa zwykły edytor CV etapu.
 *
 * 12.10.2026: trzecie źródło — CV etapu z INNEJ rekrutacji tej osoby, w wersji
 * po poprawkach rekrutera — oraz wgranie pliku Word z dysku (karta „CV do
 * klienta”). Klient z wymogiem zrzutu zgody nie wyszarza już opcji: kopia
 * powstaje, a opcja mówi, co stanie się ze zgodą.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, Repeat2, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import api, {
  candidateStageCvApi,
  type CVBrandedState,
  type GeneratedCvItem,
  type StageCvSourceItem,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";
import {
  cvToClientRowsQueryKey,
  stageBrandedQueryKey,
  stageCvSourcesQueryKey,
} from "@/lib/cv-to-client";
import {
  buildStageCvOptions,
  type StageCvDocumentSource,
  type StageCvOption,
  type StageCvOptions,
} from "@/lib/stage-cv-options";

interface StagePolicy {
  effective_policy?: { requires_rodo_consent_block?: boolean } | null;
}

/** Opcje do wyboru. Klucze zapytań wspólne z profilem i generatorem CV. */
export function useStageCvOptions({
  candidateId,
  jobId,
  stageId,
  documents,
  enabled,
}: {
  candidateId: number;
  jobId: number;
  stageId: number | null;
  documents: readonly StageCvDocumentSource[] | undefined;
  enabled: boolean;
}): { options: StageCvOptions; isPending: boolean; isError: boolean; refetch: () => void } {
  // CV etapu tej osoby z innych rekrutacji (z poprawkami rekrutera).
  const sourcesQuery = useQuery<StageCvSourceItem[]>({
    queryKey: stageCvSourcesQueryKey(stageId),
    queryFn: () =>
      candidateStageCvApi.branded
        .sources(stageId as number)
        .then((r) => (Array.isArray(r.data?.items) ? r.data.items : [])),
    enabled: enabled && stageId != null,
    staleTime: 60_000,
    retry: false,
  });
  const generatedQuery = useQuery<GeneratedCvItem[]>({
    queryKey: ["candidate-generated-cvs", candidateId],
    queryFn: () =>
      api
        .get<GeneratedCvItem[]>("/api/cv-generator/generated", {
          params: { candidate_id: candidateId, limit: 50 },
        })
        .then((r) => (Array.isArray(r.data) ? r.data : [])),
    enabled: enabled && candidateId > 0,
    staleTime: 60_000,
    retry: false,
  });
  // Tylko po to, żeby wyszarzyć opcje u klienta ze zrzutem zgody, zanim ktoś
  // kliknie — odmowę i tak wydaje serwer, więc błąd tego zapytania nie szkodzi.
  const policyQuery = useQuery<StagePolicy>({
    queryKey: ["central-cv-policy", null, stageId, false],
    queryFn: async () =>
      (await api.get<StagePolicy>("/api/cv-generator/policy", { params: { stage_id: stageId } })).data,
    enabled: enabled && stageId != null,
    staleTime: 30_000,
    retry: false,
  });
  return {
    options: buildStageCvOptions({
      stages: sourcesQuery.data,
      generated: generatedQuery.data,
      documents,
      jobId,
      consentClient: policyQuery.data?.effective_policy?.requires_rodo_consent_block === true,
    }),
    isPending:
      enabled && (generatedQuery.isPending || (stageId != null && sourcesQuery.isPending)),
    // Awaria listy nie może wyglądać jak „ta osoba nie ma gotowego CV”.
    isError: generatedQuery.isError || sourcesQuery.isError,
    refetch: () => {
      void generatedQuery.refetch();
      void sourcesQuery.refetch();
    },
  };
}

/** Podpięcie wybranego CV jako szkicu CV firmowego etapu. */
export function useChooseStageCv({
  candidateId,
  jobId,
  stageId,
  targetStageId,
  revision,
  onChosen,
}: {
  candidateId: number;
  jobId: number;
  /** Najnowszy wiersz etapu pary (jego klucz też trzeba odświeżyć). */
  stageId: number;
  /** Wiersz, na którym leży (albo powstanie) CV firmowe pary. */
  targetStageId: number;
  revision: number;
  onChosen?: (state: CVBrandedState) => void;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  // Jedno miejsce na skutki wyboru — także dla pliku wgranego z dysku.
  const onSuccess = (response: { data: CVBrandedState }) => {
    queryClient.setQueryData(stageBrandedQueryKey(targetStageId), response.data);
    if (stageId !== targetStageId) {
      void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(stageId) });
    }
    void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
    void queryClient.invalidateQueries({ queryKey: ["cv-generated", "dl-review", candidateId, jobId] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
    void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
    showSuccess("CV wybrane — możesz je teraz edytować.");
    onChosen?.(response.data);
  };
  const mutation = useMutation({
    mutationFn: (option: StageCvOption) =>
      option.kind === "generated"
        ? candidateStageCvApi.branded.selectGenerated(targetStageId, option.id, revision)
        : option.kind === "stage"
          ? candidateStageCvApi.branded.selectStageCv(targetStageId, option.id, revision)
          : candidateStageCvApi.branded.selectDocument(targetStageId, option.id, revision),
    onSuccess,
    onError: (error) =>
      showError(
        apiErrorMessage(error, "Nie udało się wybrać CV. Odśwież podgląd i spróbuj ponownie."),
      ),
  });
  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      candidateStageCvApi.branded.uploadDocx(targetStageId, file, revision),
    onSuccess,
    onError: (error) =>
      showError(
        apiErrorMessage(error, "Nie udało się wczytać pliku. Sprawdź, czy to plik Word (.docx), i spróbuj ponownie."),
      ),
  });
  return {
    choose: (option: StageCvOption) => mutation.mutate(option),
    /** Plik Word z dysku → szkic (bez zapisu w plikach kandydata). */
    upload: (file: File) => uploadMutation.mutate(file),
    busyKey: mutation.isPending ? (mutation.variables?.key ?? null) : null,
    uploading: uploadMutation.isPending,
  };
}

function OptionRow({
  option,
  busyKey,
  onChoose,
  onPreviewDocument,
  onPreviewStage,
}: {
  option: StageCvOption;
  busyKey: string | null;
  onChoose: (option: StageCvOption) => void;
  onPreviewDocument?: (documentId: number) => void;
  onPreviewStage?: (option: StageCvOption) => void;
}) {
  const busy = busyKey === option.key;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2">
      <div className="min-w-0 flex-1 basis-48">
        <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-foreground">
          <span className="min-w-0 break-words">{option.title}</span>
          {option.origin ? (
            <Badge
              size="sm"
              variant={
                option.origin === "ta rekrutacja"
                  ? "soft"
                  : option.origin.startsWith("zatwierdzone")
                    ? "success"
                    : "outline"
              }
            >
              {option.origin}
            </Badge>
          ) : null}
        </p>
        {option.detail ? <p className="text-xs text-muted-foreground">{option.detail}</p> : null}
        {option.note ? <p className="mt-0.5 text-xs text-muted-foreground">{option.note}</p> : null}
      </div>
      <div className="flex flex-none items-center gap-1.5">
        {option.kind === "document" && onPreviewDocument ? (
          <Button size="sm" variant="ghost" onClick={() => onPreviewDocument(option.id)}>
            Podgląd
          </Button>
        ) : null}
        {option.kind === "stage" && onPreviewStage ? (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Podgląd: ${option.title}`}
            onClick={() => onPreviewStage(option)}
          >
            Podgląd
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          disabled={busyKey != null}
          loading={busy}
          aria-label={`Wybierz: ${option.title}`}
          onClick={() => onChoose(option)}
        >
          Wybierz
        </Button>
      </div>
    </li>
  );
}

function OptionGroup({
  icon,
  label,
  options,
  ...row
}: {
  icon: React.ReactNode;
  label: string;
  options: StageCvOption[];
  busyKey: string | null;
  onChoose: (option: StageCvOption) => void;
  onPreviewDocument?: (documentId: number) => void;
  onPreviewStage?: (option: StageCvOption) => void;
}) {
  if (options.length === 0) return null;
  return (
    <section aria-label={label} className="rounded-lg border border-border bg-background">
      <h4 className="flex items-center gap-1.5 border-b border-border px-3 py-1.5 text-xs font-semibold text-muted-foreground">
        {icon}
        {label} ({options.length})
      </h4>
      <ul className="divide-y divide-border">
        {options.map((option) => (
          <OptionRow key={option.key} option={option} {...row} />
        ))}
      </ul>
    </section>
  );
}

export interface StageCvPickerProps {
  options: StageCvOptions;
  isPending?: boolean;
  busyKey: string | null;
  onChoose: (option: StageCvOption) => void;
  onPreviewDocument?: (documentId: number) => void;
  /** Podgląd treści CV etapu z innej rekrutacji (karta „CV do klienta”). */
  onPreviewStage?: (option: StageCvOption) => void;
  /** Zdanie nad listą — inne przy pierwszym wyborze, inne przy zmianie CV. */
  intro: string;
}

export function StageCvPicker({ options, isPending = false, intro, ...row }: StageCvPickerProps) {
  return (
    <div data-testid="stage-cv-picker" className="min-h-0 flex-1 space-y-3 overflow-y-auto">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Wybierz gotowe CV z profilu</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">{intro}</p>
      </div>
      {isPending ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Sprawdzam CV z generatora…
        </p>
      ) : null}
      <OptionGroup
        icon={<Repeat2 className="h-3.5 w-3.5" aria-hidden />}
        label="Z innych rekrutacji"
        options={options.stages}
        {...row}
      />
      <OptionGroup
        icon={<Sparkles className="h-3.5 w-3.5" aria-hidden />}
        label="Z generatora"
        options={options.generated}
        {...row}
      />
      <OptionGroup
        icon={<FileText className="h-3.5 w-3.5" aria-hidden />}
        label="Pliki Word z profilu"
        options={options.documents}
        {...row}
      />
      <p className="text-xs text-muted-foreground">
        Wybrane CV staje się szkicem CV firmowego tej rekrutacji. Źródło — plik w profilu albo CV z innej
        rekrutacji — zostaje bez zmian.
      </p>
    </div>
  );
}
