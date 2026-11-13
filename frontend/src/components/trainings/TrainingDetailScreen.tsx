"use client";

import { useMemo } from "react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadTrainingPath,
  trainingMediaUrl,
  trainingPaths,
  useAcceptQuote,
  useCancelTraining,
  useCompanySignature,
  useFileForParticipants,
  useGenerateAgreement,
  useImportAttendance,
  useMarkPaid,
  usePublishTraining,
  useReturnQuote,
  useReviewFile,
  useSendOrder,
  useTraining,
  useTrainingList,
  useTrainingPartner,
  useTrainingPeople,
  useTrainingsMe,
  useRetryTeams,
  useShareWithRegistered,
  useUpdateTraining,
  useUploadTrainingFile,
} from "@/lib/api/trainings";
import { resolveViewState } from "@/lib/view-state";

import { TrainingCard, type TrainingCardActions } from "./TrainingCard";
import { previousTrainingOf, warsawToday } from "./training-model";
import { useRunAction } from "./use-run-action";

const NO_ACCESS =
  "Kartę szkolenia widzą Talent Community Manager, Finanse i administrator. Umowę do podpisu za B2B Network znajdziesz w Szkolenia → Do podpisu.";

export function TrainingDetailScreen({ id }: { id: number }) {
  const me = useTrainingsMe();
  const training = useTraining(id);
  const view = training.data;
  const run = useRunAction();

  const canManage = me.data?.can_manage === true;
  const consultant = view?.trainer_kind === "consultant";
  const list = useTrainingList(Boolean(view && consultant && view.fees));
  const previousRow = useMemo(
    () => (view && list.data ? previousTrainingOf(list.data, view) : null),
    [view, list.data],
  );
  const previous = useTraining(previousRow?.id ?? 0, previousRow !== null);
  const partner = useTrainingPartner(
    id,
    Boolean(canManage && consultant && view?.status === "accepted"),
  );
  const people = useTrainingPeople(id, Boolean(canManage && view?.status === "signed"));

  const update = useUpdateTraining(id);
  const send = useSendOrder(id);
  const cancel = useCancelTraining(id);
  const returnQuote = useReturnQuote(id);
  const accept = useAcceptQuote(id);
  const generate = useGenerateAgreement(id);
  const companySign = useCompanySignature(id);
  const review = useReviewFile(id);
  const participants = useFileForParticipants(id);
  const upload = useUploadTrainingFile(id);
  const paid = useMarkPaid(id);
  const publish = usePublishTraining(id);
  const attendance = useImportAttendance(id);
  const retryTeams = useRetryTeams(id);
  const share = useShareWithRegistered(id);
  const busy = [
    update,
    send,
    cancel,
    returnQuote,
    accept,
    generate,
    companySign,
    review,
    participants,
    paid,
    publish,
    attendance,
    retryTeams,
    share,
  ].some((mutation) => mutation.isPending);

  const state = resolveViewState({
    isLoading: training.isLoading || me.isLoading,
    isError: training.isError,
    error: training.error,
    isSuccess: training.isSuccess,
  });
  if (state === "loading") return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  if (state === "forbidden") return <QueryStateNotice state="forbidden" description={NO_ACCESS} />;
  if (state === "not_found" || state === "error" || !view) {
    return (
      <QueryStateNotice
        state={state === "not_found" ? "not_found" : "error"}
        onRetry={() => training.refetch()}
      />
    );
  }

  const actions: TrainingCardActions = {
    saveOrder: (input) =>
      run(() => update.mutateAsync(input), "Zapisano zamówienie.", "Nie udało się zapisać zamówienia."),
    send: () =>
      run(
        () => send.mutateAsync(),
        consultant ? "Zamówienie wysłane trenerowi." : "Szkolenie zatwierdzone, zapisy otwarte.",
        "Nie udało się wysłać zamówienia.",
      ),
    cancel: (reason) =>
      run(() => cancel.mutateAsync(reason), "Szkolenie anulowane.", "Nie udało się anulować szkolenia."),
    returnQuote: (note) =>
      run(() => returnQuote.mutateAsync(note), "Wycena odesłana trenerowi.", "Nie udało się odesłać wyceny."),
    acceptQuote: () =>
      run(() => accept.mutateAsync(), "Wycena przyjęta. Uzupełnij dane do umowy.", "Nie udało się przyjąć wyceny."),
    generateAgreement: (input) =>
      run(
        () => generate.mutateAsync(input),
        "Umowa gotowa. Trener dostał ją do podpisu.",
        "Nie udało się przygotować umowy.",
      ),
    companySign: (file) =>
      run(
        () => companySign.mutateAsync(file),
        "Umowa podpisana przez obie strony.",
        "Nie udało się wgrać podpisanej umowy.",
      ),
    downloadAgreement: (version) => {
      void run(
        () => downloadTrainingPath(trainingPaths.agreementPdf(id, version), "umowa.pdf"),
        null,
        "Nie udało się pobrać umowy.",
      );
    },
    downloadFile: (file) => {
      void run(
        () => downloadTrainingPath(trainingPaths.file(id, file.id), file.file_name),
        null,
        "Nie udało się pobrać pliku.",
      );
    },
    reviewFile: (input) =>
      run(
        () => review.mutateAsync(input),
        input.accept ? "Plik przyjęty." : "Plik zwrócony do poprawy.",
        "Nie udało się zapisać decyzji o pliku.",
      ),
    toggleParticipants: (input) =>
      run(() => participants.mutateAsync(input), null, "Nie udało się zmienić widoczności pliku."),
    uploadFile: (input) =>
      run(
        () => upload.mutateAsync(input),
        input.kind === "recording" ? "Nagranie wgrane." : "Plik wgrany.",
        "Nie udało się wgrać pliku.",
      ),
    mediaUrl: async (file) => {
      try {
        return await trainingMediaUrl(file.id, id);
      } catch {
        return null;
      }
    },
    markPaid: (value) =>
      run(
        () => paid.mutateAsync(value),
        value ? "Oznaczono jako zapłacone." : "Cofnięto oznaczenie zapłaty.",
        "Nie udało się zmienić zapłaty.",
      ),
    publish: (value) =>
      run(
        () => publish.mutateAsync(value),
        value ? "Szkolenie jest w bibliotece." : "Szkolenie wycofane z biblioteki.",
        "Nie udało się zmienić publikacji.",
      ),
    importAttendance: (file) =>
      run(
        () => attendance.mutateAsync(file),
        (result) => `Wczytano obecność: ${result.imported} osób, rozpoznanych ${result.matched}.`,
        "Nie udało się wczytać raportu obecności.",
      ),
    retryTeams: () =>
      run(() => retryTeams.mutateAsync(), "Spotkanie w Teams gotowe.", "Nie udało się założyć spotkania w Teams."),
    shareRegistered: (value) =>
      run(
        () => share.mutateAsync(value),
        value ? "Zapisani widzą nagranie." : "Cofnięto udostępnienie nagrania.",
        "Nie udało się zmienić udostępnienia nagrania.",
      ),
  };

  return (
    <div className="space-y-3">
      <Link href="/trainings?tab=organize" className="text-sm text-primary hover:underline">
        ← Szkolenia: Organizuję
      </Link>
      <TrainingCard
        view={view}
        me={
          me.data ?? { can_manage: false, can_read: true, can_pay: false, is_company_signer: false }
        }
        today={warsawToday()}
        previous={previousRow && previous.data?.fees ? { row: previousRow, fees: previous.data.fees } : null}
        partner={partner.data}
        partnerError={partner.isError ? apiErrorMessage(partner.error, "Nie udało się odczytać danych trenera z kontraktu.") : null}
        people={people.data}
        peopleError={people.isError ? apiErrorMessage(people.error, "Nie udało się odczytać zapisów i obecności.") : null}
        peopleLoading={people.isLoading}
        actions={actions}
        busy={busy}
      />
    </div>
  );
}
