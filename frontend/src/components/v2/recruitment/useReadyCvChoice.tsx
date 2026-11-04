"use client";

/**
 * Gotowe CV tej osoby do użycia ZAMIAST generacji — dane i akcje wspólne dla
 * paska „Ta osoba ma już gotowe CV” i okna „Użyj innego CV” w karcie
 * „CV do klienta” (12.10.2026).
 *
 * Pomiar na produkcji: 16 z 22 auto-CV z dwóch tygodni powstało dla osób,
 * które miały już gotowe CV, a karta dawała tylko „Wygeneruj ponownie”.
 * Jedna instancja w karcie: pasek i okno dzielą zapytania, potwierdzenie
 * zastąpienia szkicu i stan „w toku”.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import api, { type CVBrandedState } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { networkHistoryApi } from "@/lib/api/cvEditorHistory";
import { useToast } from "@/components/Toast";
import type { StageCvOption } from "@/lib/stage-cv-options";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useChooseStageCv,
  useStageCvOptions,
} from "@/components/v2/screening-form/StageCvPicker";

export function useReadyCvChoice({
  candidateId,
  jobId,
  stageId,
  targetStageId,
  revision,
  replaces,
  enabled,
  onChosen,
}: {
  candidateId: number;
  jobId: number;
  /** Bieżący wiersz etapu osoby w tej rekrutacji. */
  stageId: number;
  /** Wiersz, na którym leży (albo powstanie) CV firmowe pary. */
  targetStageId: number;
  revision: number;
  /** Para ma już CV — wybór je zastąpi, więc najpierw pytamy. */
  replaces: boolean;
  enabled: boolean;
  onChosen?: (state: CVBrandedState) => void;
}) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError } = useToast();
  // Plik z dysku przed zapisem: czy ma układ szablonu B2B (29.10.2026). Sam
  // odczyt (`import-preview` niczego nie zapisuje) — zapis robi `upload`.
  const inspectMutation = useMutation({
    mutationFn: (file: File) => networkHistoryApi.importPreview(targetStageId, file),
    onError: (error) =>
      showError(
        apiErrorMessage(error, "Nie udało się wczytać pliku. Sprawdź, czy to plik Word (.docx), i spróbuj ponownie."),
      ),
  });
  // Ten sam klucz co podgląd screeningu i dok osoby — odpowiedź jest wspólna.
  const docsQuery = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.cvDocuments(candidateId),
    queryFn: () =>
      api
        .get<CandidateDocument[]>(`/api/candidates/${candidateId}/documents?kind=cv`)
        .then((r) => (Array.isArray(r.data) ? r.data : [])),
    enabled,
    staleTime: 30_000,
    retry: false,
  });
  const picker = useStageCvOptions({
    candidateId,
    jobId,
    stageId,
    documents: docsQuery.data,
    enabled,
  });
  const chooser = useChooseStageCv({
    candidateId,
    jobId,
    stageId,
    targetStageId,
    revision,
    onChosen,
  });
  const confirmReplace = async () =>
    !replaces ||
    (await askConfirm({
      title: "Zastąpić CV do klienta?",
      description:
        "Obecny szkic zostanie zastąpiony wybranym CV. Zatwierdzone wersje i wysłane linki zostają bez zmian.",
      confirmLabel: "Zastąp",
    }));
  return {
    options: picker.options,
    documents: docsQuery.data ?? [],
    isPending: picker.isPending || (enabled && docsQuery.isPending),
    // Awaria listy nie może wyglądać jak „ta osoba nie ma gotowego CV”.
    isError: picker.isError || docsQuery.isError,
    refetch: () => {
      picker.refetch();
      void docsQuery.refetch();
    },
    choose: async (option: StageCvOption) => {
      if (await confirmReplace()) chooser.choose(option);
    },
    upload: async (file: File) => {
      if (await confirmReplace()) chooser.upload(file);
    },
    /**
     * Czy plik wygląda na CV w szablonie B2B; `null` = nie udało się go
     * odczytać (komunikat już poszedł). Starszy serwer bez pola = tak.
     */
    inspect: (file: File): Promise<boolean | null> =>
      inspectMutation.mutateAsync(file).then(
        (preview) => preview.b2b_template !== false,
        () => null,
      ),
    busyKey: chooser.busyKey,
    uploading: chooser.uploading || inspectMutation.isPending,
    confirmDialog,
  };
}

export type ReadyCvChoice = ReturnType<typeof useReadyCvChoice>;
