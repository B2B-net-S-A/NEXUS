"use client";

/**
 * Blok „Nowe CV” po wgraniu nowego CV kandydata w rekrutacji (29.10.2026,
 * decyzje Artura D1 = A; makiety https://claude.ai/artifact/81NLWbfecdy6EsiT2Hzzrc).
 *
 * Trzy kroki jak blok po „Zapisz i przekaż dalej”: profil, oryginał w tej
 * rekrutacji, CV do klienta. CV do klienta, którego nikt nie ruszał, generuje
 * się samo z nowego pliku i zastępuje szkic („Cofnij” = „Wróć do poprzedniej”).
 * Poprawione, wybrane albo zatwierdzone — pytamy („Generuj z nowego CV” /
 * „Zostaw obecne”), bo automat skasowałby czyjąś pracę. Bez CV do klienta
 * zostają potwierdzenia z 21.10 — plik jest już potwierdzony.
 *
 * Wpis bloku zapisuje `useStageCvUpload` w pamięci zapytań pary, więc blok
 * w karcie i w panelu widzi wgranie z każdego miejsca.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { candidateStageCvApi, type CVBrandedState } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cvToClientRowsQueryKey, stageBrandedQueryKey } from "@/lib/cv-to-client";
import { newCvCompanyStep, newCvUploadKey, type NewCvUpload } from "@/lib/new-cv-upload";
import { dismissCompanyCvStale } from "@/components/v2/recruitment/CompanyCvStaleNotice";

const POLL_MS = 4000;

function Step({ done, children }: { done: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-1.5">
      {done ? (
        <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
      ) : (
        <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden />
      )}
      <span className="min-w-0">{children}</span>
    </li>
  );
}

export function NewCvProgress({
  candidateId,
  jobId,
  readOnly = false,
}: {
  candidateId: number;
  jobId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const key = newCvUploadKey(candidateId, jobId);
  // Tylko pamięć zapytań — wpis zapisuje wgranie, blok niczego nie pobiera.
  const { data: upload } = useQuery<NewCvUpload | null>({
    queryKey: key,
    queryFn: () => null,
    enabled: false,
    staleTime: Infinity,
  });
  const [now, setNow] = useState(() => Date.now());
  const stageId = upload?.companyStageId ?? null;
  const waiting = upload?.plan === "regenerating";
  const brandedQuery = useQuery<CVBrandedState>({
    queryKey: stageBrandedQueryKey(stageId),
    queryFn: () => candidateStageCvApi.branded.get(stageId as number).then((r) => r.data),
    enabled: stageId != null && upload?.plan !== "locked" && upload?.plan !== "none",
    refetchInterval: (query) =>
      waiting && upload && upload.regeneratingId !== query.state.data?.generated_document_id ? POLL_MS : false,
  });
  const step = upload ? newCvCompanyStep(upload, brandedQuery.data?.generated_document_id, now) : null;

  useEffect(() => {
    if (step?.kind !== "generating") return;
    const timer = window.setInterval(() => setNow(Date.now()), POLL_MS);
    return () => window.clearInterval(timer);
  }, [step?.kind]);

  const close = () => queryClient.setQueryData(key, null);

  const regenerate = useMutation({
    mutationFn: () =>
      candidateStageCvApi.branded.regenerateFromOriginal(stageId as number, brandedQuery.data?.edit_revision ?? 0),
    onSuccess: (response) => {
      if (!upload) return;
      queryClient.setQueryData<NewCvUpload>(key, {
        ...upload,
        at: Date.now(),
        plan: "regenerating",
        regeneratingId: response.data.generated_document_id,
      });
      setNow(Date.now());
      void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się zlecić nowego CV do klienta. Spróbuj ponownie.")),
  });

  const undo = useMutation({
    mutationFn: () =>
      candidateStageCvApi.branded.restorePrevious(stageId as number, brandedQuery.data?.edit_revision ?? 0),
    onSuccess: (response) => {
      queryClient.setQueryData(stageBrandedQueryKey(stageId), response.data);
      void queryClient.invalidateQueries({ queryKey: ["cv-qc", stageId] });
      if (upload?.snapshotAt && stageId != null) dismissCompanyCvStale(stageId, upload.snapshotAt);
      close();
      showSuccess("Przywrócone poprzednie CV do klienta. Nowa wersja jest w historii.");
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się cofnąć — CV mogło zmienić się w innym oknie.")),
  });

  if (!upload || !step) return null;

  return (
    <div
      data-testid="new-cv-progress"
      className="space-y-2 rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-xs text-foreground"
    >
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 font-semibold [overflow-wrap:anywhere]">Nowe CV: {upload.filename}</p>
        <button
          type="button"
          onClick={close}
          aria-label="Zamknij informację o nowym CV"
          className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      <ol aria-label="Nowe CV" className="space-y-1">
        <Step done>W profilu jako główne CV · AI odświeża profil</Step>
        <Step done>Oryginał CV w tej rekrutacji podmieniony</Step>
        {step.kind === "generating" ? (
          <Step done={false}>CV do klienta generuje się z nowego CV (ok. 40 s)</Step>
        ) : step.kind === "replaced" ? (
          <Step done>CV do klienta z nowego CV — poprzednie jest w historii</Step>
        ) : null}
      </ol>
      {step.kind === "replaced" && !readOnly ? (
        <Button size="sm" variant="outline" loading={undo.isPending} disabled={undo.isPending} onClick={() => undo.mutate()}>
          Cofnij
        </Button>
      ) : null}
      {step.kind === "slow" ? (
        <p className="text-muted-foreground">
          Nowe CV do klienta jeszcze się robi. Gdy będzie gotowe, podepniesz je przyciskiem „Użyj nowej wersji”.
        </p>
      ) : null}
      {step.kind === "ask" ? (
        <div className="space-y-1.5" data-testid="new-cv-ask">
          <p>
            {step.sentence} Wygenerować nowe z tego CV? Obecne zostaje w „Historii wersji”.
          </p>
          {readOnly ? null : (
            <div className="flex flex-wrap gap-1.5">
              <Button
                size="sm"
                loading={regenerate.isPending}
                disabled={regenerate.isPending || brandedQuery.isPending}
                onClick={() => regenerate.mutate()}
              >
                Generuj z nowego CV
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={regenerate.isPending}
                onClick={() => {
                  if (upload.snapshotAt && stageId != null) dismissCompanyCvStale(stageId, upload.snapshotAt);
                  close();
                }}
              >
                Zostaw obecne
              </Button>
            </div>
          )}
        </div>
      ) : null}
      {step.kind === "confirm" ? (
        <p className="text-muted-foreground">
          CV do klienta jeszcze nie ma. Plik jest już potwierdzony — przy „Generuj CV” potwierdzisz odpowiedzi
          i notatki.
        </p>
      ) : null}
      {step.kind === "locked" ? (
        <p className="text-muted-foreground">Klient ma już CV tej osoby — w tej rekrutacji zostaje wysłana wersja.</p>
      ) : null}
    </div>
  );
}
