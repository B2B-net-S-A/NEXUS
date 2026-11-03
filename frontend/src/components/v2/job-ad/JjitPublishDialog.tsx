"use client";

/**
 * Publikacja ogłoszenia na JustJoin.IT przez API (03.11.2026).
 *
 * Treść to zakładka JustJoin.IT po kontroli. Okno pyta o to, czego w ogłoszeniu
 * nie ma: kategorię ze słownika portalu i ustawienia wypełnione z rekrutacji.
 * Widełki są opcjonalne i wpisuje je człowiek (25.09.2026). Samo zlecenie idzie
 * do kolejki, a portal woła worker. Reguły:
 * `docs/claude/rekrutacja-tworzenie/ogloszenie-justjoin-przez-api.md`.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { PortalListingForm } from "@/components/v2/recruitment/PortalListingForm";
import { apiErrorMessage } from "@/lib/api-error";
import { jobAdApi, jobAdQueryKey, type JobAdState } from "@/lib/api/jobAd";
import {
  fetchListingDefaults,
  jobPortalKeys,
  listingProblemsFromError,
  validateListingOptions,
  type PortalListingOptions,
} from "@/lib/api/jobPortals";

export type JjitPublishApi = Pick<typeof jobAdApi, "publishJjit">;

export interface JjitPublishDialogProps {
  open: boolean;
  jobId: number;
  state: JobAdState;
  api?: JjitPublishApi;
  onClose: () => void;
  onPublished: (next: JobAdState) => void;
}

export function JjitPublishDialog({
  open,
  jobId,
  state,
  api = jobAdApi,
  onClose,
  onPublished,
}: JjitPublishDialogProps) {
  // Ponowienie po odmowie portalu zaczyna od tego, co wpisano wcześniej.
  const saved = state.jjit_api?.options ?? null;
  const defaults = useQuery({
    queryKey: jobPortalKeys.listingDefaults(jobId),
    queryFn: () => fetchListingDefaults(jobId),
    enabled: open && saved == null,
    staleTime: 60_000,
  });
  const initial = saved ?? defaults.data ?? null;

  if (!open) return null;
  return (
    <AppModal
      open
      onOpenChange={(next) => (!next ? onClose() : undefined)}
      size="lg"
      title="Opublikuj na JustJoin.IT"
      description="Opis to treść z zakładki JustJoin.IT. Publikacja zużywa kredyt portalu, a ponowna po zdjęciu ogłoszenia to nowy kredyt."
    >
      {initial ? (
        <PublishForm
          jobId={jobId}
          expectedUpdatedAt={state.ad?.updated_at ?? null}
          initial={initial}
          api={api}
          onCancel={onClose}
          onPublished={onPublished}
        />
      ) : defaults.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(defaults.error, "Nie udało się wczytać danych rekrutacji do ogłoszenia.")}
        </p>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Wczytuję dane rekrutacji…
        </p>
      )}
    </AppModal>
  );
}

function PublishForm({
  jobId,
  expectedUpdatedAt,
  initial,
  api,
  onCancel,
  onPublished,
}: {
  jobId: number;
  expectedUpdatedAt: string | null;
  initial: PortalListingOptions;
  api: JjitPublishApi;
  onCancel: () => void;
  onPublished: (next: JobAdState) => void;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [options, setOptions] = useState<PortalListingOptions>(initial);
  const [serverProblems, setServerProblems] = useState<string[] | null>(null);
  const [touched, setTouched] = useState(false);
  const problems = useMemo(
    () => validateListingOptions(options, { board: "justjoinit" }),
    [options],
  );
  const publish = useMutation({
    mutationFn: () =>
      api.publishJjit(jobId, { expected_updated_at: expectedUpdatedAt, options }),
    onSuccess: (next) => {
      showSuccess("Ogłoszenie poszło do wysyłki na JustJoin.IT.");
      onPublished(next);
    },
    onError: (err) => {
      const listing = listingProblemsFromError(err);
      if (listing) {
        setServerProblems(listing);
        return;
      }
      showError(apiErrorMessage(err, "Nie udało się wysłać ogłoszenia. Spróbuj ponownie."));
      void queryClient.invalidateQueries({ queryKey: jobAdQueryKey(jobId) });
    },
  });
  const shown = serverProblems ?? (touched ? problems : []);

  return (
    <div className="flex flex-col gap-4">
      <PortalListingForm
        value={options}
        onChange={(next) => {
          setOptions(next);
          setServerProblems(null);
        }}
        selected={["justjoinit"]}
        problems={shown}
        disabled={publish.isPending}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={publish.isPending}>
          Anuluj
        </Button>
        <Button
          type="button"
          loading={publish.isPending}
          data-testid="jjit-publish-confirm"
          onClick={() => {
            setTouched(true);
            if (problems.length === 0) publish.mutate();
          }}
        >
          Opublikuj
        </Button>
      </div>
    </div>
  );
}
