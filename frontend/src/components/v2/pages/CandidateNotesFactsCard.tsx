"use client";

/**
 * „Z notatek rekruterów” — fakty wyciągnięte przez AI z notatek kandydata,
 * obok tego, co jest w profilu, z jednym przyciskiem „Zapisz w profilu” przy
 * każdym polu, które profil może przyjąć (22.09.2026).
 *
 * Wartość do zapisu wylicza SERWER (`POST …/notes-facts/apply` wskazuje tylko
 * pole) — przycisk nie może zapisać czegoś innego niż to, co widać na karcie.
 * Stawkę chroni ta sama wersja co okno edycji stawki: zmiana w innym oknie
 * daje 412 i świeży odczyt zamiast cichego nadpisania.
 */

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NotebookPen, RefreshCw } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCapability } from "@/hooks/useCapability";
import {
  candidateFactsApi,
  extractErrorMsg,
  type CandidateNotesFactField,
  type CandidateNotesFacts,
} from "@/lib/api";
import {
  CONTRACT_FORM_LABELS,
  contractTypesText,
  describeNotesRate,
  formatExtractedAt,
  notesAvailabilityText,
  notesWorkModeText,
  profileRateText,
} from "@/lib/notes-facts";
import { invalidateCandidateMutation } from "./candidate-cache";
import { candidateQueryKeys } from "./candidate-query-keys";

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error))
    return null;
  return (error as { response?: { status?: number } }).response?.status ?? null;
}

function FactRow({
  label,
  children,
  profile,
  note,
  action,
}: {
  label: string;
  children: React.ReactNode;
  profile?: string | null;
  note?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 border-b border-border py-3 last:border-b-0 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
        <dd className="mt-0.5 text-sm font-medium text-foreground [overflow-wrap:anywhere]">
          {children}
        </dd>
        {note ? (
          <dd className="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
            {note}
          </dd>
        ) : null}
        {profile ? (
          <dd className="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
            W profilu: {profile}
          </dd>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CandidateNotesFactsCard({
  candidateId,
  readOnly = false,
}: {
  candidateId: number;
  readOnly?: boolean;
}) {
  const canManage = useCapability("candidate.profile_fact.manage");
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [pendingField, setPendingField] =
    React.useState<CandidateNotesFactField | null>(null);

  const query = useQuery<CandidateNotesFacts>({
    queryKey: candidateQueryKeys.notesFacts(candidateId),
    queryFn: () => candidateFactsApi.getNotesFacts(candidateId),
    enabled: candidateId > 0 && canManage,
    retry: false,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: ({
      field,
      version,
    }: {
      field: CandidateNotesFactField;
      version?: number;
    }) => candidateFactsApi.applyNotesFact(candidateId, field, version),
    onMutate: ({ field }) => setPendingField(field),
    onSuccess: (data, { field }) => {
      queryClient.setQueryData(
        candidateQueryKeys.notesFacts(candidateId),
        data,
      );
      invalidateCandidateMutation(
        queryClient,
        candidateId,
        field === "rate" ? "rate" : "edit",
      );
      if (field === "rate") {
        queryClient.invalidateQueries({
          queryKey: candidateQueryKeys.profileRate(candidateId),
        });
      }
      showSuccess("Zapisano w profilu kandydata");
    },
    onError: (error) => {
      const status = requestStatus(error);
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.notesFacts(candidateId),
      });
      if (status === 412) {
        queryClient.invalidateQueries({
          queryKey: candidateQueryKeys.profileRate(candidateId),
        });
        showError(
          "Stawka zmieniła się w innym oknie. Pobraliśmy aktualne dane — sprawdź je przed ponownym zapisem.",
        );
        return;
      }
      showError(extractErrorMsg(error) || "Nie udało się zapisać w profilu");
    },
    onSettled: () => setPendingField(null),
  });

  if (!canManage) return null;

  const saveButton = (field: CandidateNotesFactField, version?: number) =>
    readOnly ? null : (
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="min-h-11"
        loading={pendingField === field}
        disabled={mutation.isPending && pendingField !== field}
        onClick={() => mutation.mutate({ field, version })}
      >
        Zapisz w profilu
      </Button>
    );

  const data = query.data;
  const extractedAt = formatExtractedAt(data?.extracted_at ?? null);

  return (
    <Card aria-labelledby="candidate-notes-facts-title">
      <CardHeader className="pb-1">
        <CardTitle
          id="candidate-notes-facts-title"
          className="flex items-center gap-2"
        >
          <NotebookPen aria-hidden="true" className="size-4 text-primary" />Z
          notatek rekruterów
        </CardTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          Fakty, które AI wyczytało z notatek (Traffit i NEXUS)
          {extractedAt ? ` · ostatnia analiza ${extractedAt}` : ""}. Sprawdź
          przed zapisem w profilu.
        </p>
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <p role="status" className="py-3 text-sm text-muted-foreground">
            Ładowanie…
          </p>
        ) : query.isError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground"
          >
            <span>
              {requestStatus(query.error) === 403
                ? "Brak dostępu do faktów z notatek."
                : "Nie udało się wczytać faktów z notatek."}
            </span>
            {requestStatus(query.error) === 403 ? null : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="min-h-11"
                onClick={() => query.refetch()}
              >
                <RefreshCw aria-hidden="true" className="size-4" />
                Ponów
              </Button>
            )}
          </div>
        ) : !data?.has_facts ? (
          <p className="py-3 text-sm text-muted-foreground">
            {data?.extracted_at
              ? "Notatki nie zawierają faktów, które da się dopisać do profilu."
              : "Notatki tego kandydata nie zostały jeszcze przeanalizowane."}
          </p>
        ) : (
          <NotesFactsList data={data} saveButton={saveButton} />
        )}
      </CardContent>
    </Card>
  );
}

function NotesFactsList({
  data,
  saveButton,
}: {
  data: CandidateNotesFacts;
  saveButton: (
    field: CandidateNotesFactField,
    version?: number,
  ) => React.ReactNode;
}) {
  const rate = data.rate ? describeNotesRate(data.rate) : null;
  const workMode = data.work_mode ? notesWorkModeText(data.work_mode) : null;
  const availability = data.availability
    ? notesAvailabilityText(data.availability)
    : null;
  const engagement = data.current_engagement;
  const relocation = data.relocation;
  const [showMore, setShowMore] = React.useState(false);
  const extraCount = [
    relocation,
    engagement,
    data.not_looking_until,
    data.languages.length ? data.languages : null,
    data.sectors_prefer.length || data.sectors_avoid.length ? true : null,
    data.client_vetoes.length ? data.client_vetoes : null,
    data.matching_facts,
  ].filter(Boolean).length;
  const primaryCount = [
    data.rate,
    data.work_mode,
    data.contract_form,
    data.availability,
    data.office_cities,
  ].filter(Boolean).length;
  // Bez pól do profilu nie ma czego zwijać — pokaż od razu resztę faktów.
  const extrasVisible = showMore || primaryCount === 0;

  return (
    <>
      <dl>
        {data.rate && rate ? (
          <FactRow
            label="Oczekiwana stawka"
            profile={profileRateText(data.rate.profile_amount)}
            note={
              <>
                {rate.hourly && rate.conversion ? (
                  <span className="block">
                    W notatce: {rate.original} ({rate.conversion})
                  </span>
                ) : null}
                {rate.warning ? (
                  <span className="block font-medium text-warning-muted-foreground">
                    {rate.warning}
                  </span>
                ) : null}
                {data.rate.raw ? (
                  <span className="block">„{data.rate.raw}”</span>
                ) : null}
                {data.rate.flexibility ? (
                  <span className="block">
                    Elastyczność: {data.rate.flexibility}
                  </span>
                ) : null}
              </>
            }
            action={
              data.rate.can_apply
                ? saveButton("rate", data.rate.profile_rate_version)
                : null
            }
          >
            {rate.hourly ?? rate.original}
          </FactRow>
        ) : null}

        {data.work_mode && workMode ? (
          <FactRow
            label="Tryb pracy"
            profile={workMode.profile}
            action={data.work_mode.can_apply ? saveButton("work_mode") : null}
          >
            {workMode.notes}
          </FactRow>
        ) : null}

        {data.contract_form ? (
          <FactRow
            label="Forma współpracy"
            profile={contractTypesText(
              data.contract_form.profile_contract_types,
            )}
            action={
              data.contract_form.can_apply ? saveButton("contract_form") : null
            }
          >
            {CONTRACT_FORM_LABELS[data.contract_form.value]}
          </FactRow>
        ) : null}

        {data.availability && availability ? (
          <FactRow
            label="Dostępność"
            profile={availability.profile}
            note={
              data.availability.raw &&
              data.availability.raw !== availability.notes
                ? `„${data.availability.raw}”`
                : null
            }
            action={
              data.availability.can_apply ? saveButton("availability") : null
            }
          >
            {availability.notes}
          </FactRow>
        ) : null}

        {data.office_cities ? (
          <FactRow
            label="Preferowane miasta"
            profile={
              data.office_cities.profile_office_cities.length
                ? data.office_cities.profile_office_cities.join(", ")
                : "nie uzupełniono"
            }
            action={
              data.office_cities.can_apply ? saveButton("office_cities") : null
            }
          >
            {data.office_cities.cities.join(", ")}
          </FactRow>
        ) : null}

        {extrasVisible && relocation ? (
          <FactRow label="Relokacja">
            {relocation.willing === false
              ? "Nie chce się przeprowadzać"
              : relocation.willing
                ? "Gotowy do przeprowadzki"
                : "Wspominał o przeprowadzce"}
            {relocation.targets.length
              ? ` · ${relocation.targets.join(", ")}`
              : ""}
          </FactRow>
        ) : null}

        {extrasVisible && engagement ? (
          <FactRow
            label="Obecny projekt"
            note={engagement.raw ? `„${engagement.raw}”` : null}
          >
            {[engagement.employer, engagement.project]
              .filter(Boolean)
              .join(" · ") || "W trakcie projektu"}
            {engagement.ends_at ? ` · do ${engagement.ends_at}` : ""}
          </FactRow>
        ) : null}

        {extrasVisible && data.not_looking_until ? (
          <FactRow label="Nie szuka do">{data.not_looking_until}</FactRow>
        ) : null}

        {extrasVisible && data.languages.length ? (
          <FactRow label="Języki z rozmów">
            {data.languages
              .map((l) => (l.level ? `${l.name} (${l.level})` : l.name))
              .join(", ")}
          </FactRow>
        ) : null}

        {extrasVisible &&
        (data.sectors_prefer.length || data.sectors_avoid.length) ? (
          <FactRow label="Branże">
            {[
              data.sectors_prefer.length
                ? `chętnie: ${data.sectors_prefer.join(", ")}`
                : null,
              data.sectors_avoid.length
                ? `unika: ${data.sectors_avoid.join(", ")}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </FactRow>
        ) : null}

        {extrasVisible && data.client_vetoes.length ? (
          <FactRow
            label="Nie chce pracować u"
            note="Nie zakłada konfliktu z klientem — jeśli trzeba, dodaj go ręcznie."
          >
            {data.client_vetoes
              .map((v) => (v.reason ? `${v.client} (${v.reason})` : v.client))
              .join("; ")}
          </FactRow>
        ) : null}

        {extrasVisible && data.matching_facts ? (
          <FactRow label="Najważniejsze fakty">{data.matching_facts}</FactRow>
        ) : null}
      </dl>
      {extraCount > 0 && primaryCount > 0 ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mt-1 min-h-11"
          aria-expanded={showMore}
          onClick={() => setShowMore((v) => !v)}
        >
          {showMore ? "Pokaż mniej" : `Więcej z notatek (${extraCount})`}
        </Button>
      ) : null}
    </>
  );
}

export default CandidateNotesFactsCard;
