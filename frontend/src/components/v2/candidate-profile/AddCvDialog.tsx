"use client";

/**
 * „Dodaj CV” w pasku osoby na profilu (29.10.2026, D2; makiety
 * https://claude.ai/artifact/81NLWbfecdy6EsiT2Hzzrc).
 *
 * Zgłoszenie: rekruter dostał od kandydata nowe CV (LinkedIn, mail) i nie
 * wiedział, jak dodać je do profilu — wgranie siedziało w Dokumenty → Pliki
 * → „Dodaj plik” i nie ruszało rekrutacji. Okno pyta o plik, czy ma być
 * główne (domyślnie tak) i w których rekrutacjach w toku go użyć. Każda
 * zaznaczona rekrutacja to ta sama akcja co „Wgraj nowe CV” w panelu osoby
 * (`…/stages/{id}/cv/original/upload`: główne CV profilu, oryginał w tej
 * rekrutacji i CV do klienta wg reguły z 29.10). Bez rekrutacji — zwykłe
 * `POST /api/candidates/{id}/documents` jak „Dodaj plik”.
 *
 * Po „CV wysłane” rekrutacja jest wyszarzona: klient ma już CV tej osoby.
 * W rekrutacji nowe CV jest zawsze główne (decyzja D2 z 13.10.2026), więc bez
 * „Ustaw jako główne” rekrutacje są nieaktywne.
 */

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { candidatePipelinesQueryKey } from "@/components/CandidatePipelinesWidget";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { STAGE_CV_ACCEPT, STAGE_CV_MAX_BYTES } from "@/components/v2/person/StageCvUpload";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { NewCvProgress } from "@/components/v2/recruitment/NewCvProgress";
import api, { candidateStageCvApi, phase3Api, type CandidatePipelineRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { attachCvFormData } from "@/lib/add-candidate-cv";
import { BOARD_COLUMN_LABEL, isAtClientColumn, type BoardColumnKey } from "@/lib/board-stages";
import { newCvUploadFrom, newCvUploadKey } from "@/lib/new-cv-upload";

/**
 * Rekrutacje w toku osoby: otwarta rekrutacja i karta poza „Zamkniętymi”
 * (lista rezerwowa też jest zamknięta). Karta w zamkniętej rekrutacji zostaje
 * w swojej kolumnie, więc sama kolumna nie wystarcza (test na stagingu 29.10).
 */
export function openRecruitments(rows: readonly CandidatePipelineRow[]): CandidatePipelineRow[] {
  return rows.filter(
    (row) => row.board_column && row.board_column !== "closed" && (row.job_status ?? "published") !== "closed",
  );
}

/** Klient ma już CV tej osoby — nowe CV nie zmienia tej rekrutacji. */
export function cvAlreadyAtClient(row: CandidatePipelineRow): boolean {
  return isAtClientColumn(row.board_column as BoardColumnKey | undefined);
}

function columnLabel(row: CandidatePipelineRow): string {
  return BOARD_COLUMN_LABEL[row.board_column as BoardColumnKey] ?? row.stage_name ?? "";
}

interface Done {
  jobs: { jobId: number; title: string }[];
  failed: { title: string; message: string }[];
}

export function AddCvDialog({
  open,
  onOpenChange,
  candidateId,
  candidateName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
}) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [primary, setPrimary] = useState(true);
  // Odznaczone rekrutacje — domyślnie każda, w której CV nie wyszło do klienta.
  const [skipped, setSkipped] = useState<ReadonlySet<number>>(new Set());
  const [done, setDone] = useState<Done | null>(null);

  const pipelinesQuery = useQuery({
    queryKey: candidatePipelinesQueryKey(candidateId),
    queryFn: () => phase3Api.candidatePipelines(candidateId).then((r) => r.data.pipelines),
    enabled: open,
  });
  const rows = openRecruitments(pipelinesQuery.data ?? []);
  const chosen = primary ? rows.filter((row) => !cvAlreadyAtClient(row) && !skipped.has(row.job_id)) : [];

  const save = useMutation({
    mutationFn: async (picked: File): Promise<Done> => {
      if (chosen.length === 0) {
        if (primary) {
          await api.post(`/api/candidates/${candidateId}/documents`, attachCvFormData(picked), {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } else {
          const fd = new FormData();
          fd.append("file", picked);
          fd.append("document_kind", "cv");
          await api.post(`/api/candidates/${candidateId}/documents`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        }
        return { jobs: [], failed: [] };
      }
      // Po kolei: pierwsze żądanie ustawia główne CV, kolejne znajdują ten sam
      // plik po SHA — równoległe ścigałyby się o flagę głównego CV.
      const result: Done = { jobs: [], failed: [] };
      for (const row of chosen) {
        const title = row.job_title ?? `Rekrutacja #${row.job_id}`;
        try {
          // „candidate”: w profilu dodajemy CV kandydata — plik „…B2B…” nie może
          // po cichu zostać CV do klienta w kilku rekrutacjach (przegląd 29.10).
          const response = await candidateStageCvApi.original.upload(row.candidate_stage_id, picked, {
            mode: "candidate",
          });
          const entry = newCvUploadFrom(response?.data, picked.name, Date.now());
          queryClient.setQueryData(newCvUploadKey(candidateId, row.job_id), entry);
          void queryClient.invalidateQueries({ queryKey: ["cv-original", row.candidate_stage_id] });
          result.jobs.push({ jobId: row.job_id, title });
        } catch (failure) {
          result.failed.push({ title, message: apiErrorMessage(failure, "Nie udało się wgrać CV.") });
        }
      }
      if (result.jobs.length === 0) throw new Error(result.failed[0]?.message ?? "Nie udało się wgrać CV.");
      return result;
    },
    onSuccess: (result) => setDone(result),
    onError: (failure) => setError(apiErrorMessage(failure, "Nie udało się wgrać CV. Spróbuj ponownie.")),
    onSettled: () => {
      invalidateCandidateMutation(queryClient, candidateId, "document");
      for (const queryKey of [
        candidateQueryKeys.documents(candidateId),
        candidateQueryKeys.cvDocuments(candidateId),
        candidateQueryKeys.quickView(candidateId),
        candidateQueryKeys.detail(candidateId),
      ]) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });

  const close = (next: boolean) => {
    if (save.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        className="max-w-lg"
        data-testid="add-cv-dialog"
        data-tour="candidate.add-cv.dialog"
      >
        <DialogHeader>
          <DialogTitle>Dodaj CV · {candidateName}</DialogTitle>
          <DialogDescription>Np. CV, które kandydat przysłał na LinkedInie albo mailem.</DialogDescription>
        </DialogHeader>
        {done ? (
          <DialogBody className="space-y-3 text-sm">
            <p>
              CV jest w profilu{primary ? " jako główne" : ""}.
              {done.jobs.length === 0 ? "" : " Rekrutacje:"}
            </p>
            {done.jobs.map((job) => (
              <div key={job.jobId} className="space-y-1">
                <p className="text-xs font-semibold">{job.title}</p>
                <NewCvProgress candidateId={candidateId} jobId={job.jobId} />
              </div>
            ))}
            {done.failed.map((job) => (
              <p key={job.title} className="text-xs text-destructive">
                {job.title}: {job.message}
              </p>
            ))}
          </DialogBody>
        ) : (
          <DialogBody className="space-y-4 text-sm">
            <FileDropZone
              inputId={inputId}
              file={file}
              onPick={(picked) => {
                setError(null);
                setFile(picked);
              }}
              accept={STAGE_CV_ACCEPT}
              maxBytes={STAGE_CV_MAX_BYTES}
              label="Wybierz albo upuść plik CV"
              hint="PDF, DOC albo DOCX, do 10 MB"
              error={error}
              onError={setError}
              disabled={save.isPending}
            />
            <label className="flex items-start gap-2">
              <Checkbox
                checked={primary}
                onCheckedChange={(value) => setPrimary(value === true)}
                disabled={save.isPending}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">Ustaw jako główne CV</span>
                <span className="block text-xs text-muted-foreground">
                  AI odświeży profil z nowego CV (ok. 1 min). Stare CV zostaje w Dokumentach.
                </span>
              </span>
            </label>
            <section aria-label="Rekrutacje w toku" className="space-y-2 border-t border-border pt-3">
              <p className="text-xs font-semibold text-muted-foreground">
                Rekrutacje w toku{pipelinesQuery.isSuccess ? ` · ${rows.length}` : ""}
              </p>
              {pipelinesQuery.isPending ? (
                <p className="text-xs text-muted-foreground">Wczytuję rekrutacje…</p>
              ) : pipelinesQuery.isError ? (
                <p className="text-xs text-destructive">
                  Nie udało się wczytać rekrutacji — CV trafi tylko do profilu.{" "}
                  <button type="button" className="font-medium underline" onClick={() => void pipelinesQuery.refetch()}>
                    Ponów
                  </button>
                </p>
              ) : rows.length === 0 ? (
                <p className="text-xs text-muted-foreground">Ta osoba nie jest teraz w żadnej rekrutacji.</p>
              ) : (
                rows.map((row) => {
                  const atClient = cvAlreadyAtClient(row);
                  const disabled = atClient || !primary || save.isPending;
                  const checked = !atClient && primary && !skipped.has(row.job_id);
                  return (
                    <label key={row.job_id} className={`flex items-start gap-2 ${disabled ? "opacity-60" : ""}`}>
                      <Checkbox
                        checked={checked}
                        disabled={disabled}
                        onCheckedChange={(value) =>
                          setSkipped((prev) => {
                            const next = new Set(prev);
                            if (value === true) next.delete(row.job_id);
                            else next.add(row.job_id);
                            return next;
                          })
                        }
                        className="mt-0.5"
                      />
                      <span className="min-w-0">
                        <span className="font-medium [overflow-wrap:anywhere]">
                          {row.job_title ?? `Rekrutacja #${row.job_id}`}
                        </span>{" "}
                        <Badge variant="soft" size="sm" className="align-middle">
                          {columnLabel(row)}
                        </Badge>
                        <span className="block text-xs text-muted-foreground">
                          {atClient
                            ? "CV jest już u klienta — tu zostaje wysłana wersja."
                            : !primary
                              ? "W rekrutacji używamy głównego CV — zaznacz „Ustaw jako główne CV”."
                              : "Użyj tego CV w tej rekrutacji — także jako podstawy CV do klienta."}
                        </span>
                      </span>
                    </label>
                  );
                })
              )}
            </section>
          </DialogBody>
        )}
        <DialogFooter>
          {done ? (
            <Button onClick={() => onOpenChange(false)}>Gotowe</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => close(false)} disabled={save.isPending}>
                Anuluj
              </Button>
              <Button
                onClick={() => file && save.mutate(file)}
                disabled={!file || save.isPending}
                loading={save.isPending}
              >
                Dodaj CV
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
