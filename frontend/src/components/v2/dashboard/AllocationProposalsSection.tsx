"use client";

/**
 * „Propozycje automatu do akceptacji” w panelu „Czeka na Ciebie” (02.10.2026).
 *
 * Automat przydziału tylko PROPONUJE jedną osobę do requestu bez rekrutera.
 * Head of Recruitment albo admin każdą propozycję akceptuje, zmienia na inną
 * osobę albo odrzuca; do tego czasu nikt nie jest przypisany i nikt nie
 * dostaje powiadomienia. Wiersze przychodzą z `GET /api/board-tasks` wyłącznie
 * dla osoby, która o nich decyduje, już posortowane (P1, potem najdłużej
 * czekające).
 *
 * Każdy wiersz mówi, DLACZEGO automat wybrał tę osobę — z faktów z serwera
 * (priorytet w kategorii, obłożenie, urlop, liczba pasujących w bazie), bez
 * własnych wniosków.
 *
 * Lista nie zwija się do „Pokaż wszystkie”: „Akceptuj wszystkie” dotyczy
 * dokładnie tych wierszy, które widać.
 */

import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  competenceShortLabel,
  competenceTone,
} from "@/components/v2/CompetenceCategoryBadge";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";
import { useCapability } from "@/hooks/useCapability";
import { apiErrorMessage } from "@/lib/api-error";
import {
  BOARD_TASKS_QUERY_KEY,
  type AllocationFit,
  type AllocationProposalRow,
  type BoardTasksResponse,
} from "@/lib/api/boardTasks";
import {
  acceptProposals,
  decideProposal,
  useRequestBoard,
  type LoadPerson,
  type ProposalAcceptResult,
  type ProposalDecisionBody,
} from "@/lib/api/requestAllocation";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatDeadlineShort, shortenPersonName } from "@/lib/job-header-subtitle";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { pluralPl } from "@/lib/plural-pl";
import { fold, requestWord } from "@/lib/request-board";
import { cn } from "@/lib/utils";

/** Tyle propozycji przyjmuje jedno żądanie (`MAX_BULK_ACCEPT` w `request_board.py`). */
export const MAX_BULK_ACCEPT = 100;

const ROLE_LABEL: Record<AllocationProposalRow["role"], string> = {
  recruiter: "rekruter",
  sourcer: "sourcer",
};

const FIT_REASON: Record<AllocationFit, string> = {
  first: "1. priorytet w kategorii",
  second: "2. priorytet w kategorii",
  other: "spoza kategorii",
};

export interface ProposalReason {
  text: string;
  /** Fakt, na który warto spojrzeć przed akceptacją (osoba spoza kategorii, urlop). */
  notable: boolean;
}

/** Dlaczego automat proponuje tę osobę — same fakty z wiersza. */
export function proposalReasons(row: AllocationProposalRow): ProposalReason[] {
  const reasons: ProposalReason[] = [];
  const fit = FIT_REASON[row.fit];
  if (fit) reasons.push({ text: fit, notable: row.fit === "other" });
  reasons.push({
    text: row.load > 0 ? `ma ${row.load} ${requestWord(row.load)}` : "bez requestów",
    notable: false,
  });
  if (row.leave_until) {
    reasons.push({
      text: `urlop do ${formatDeadlineShort(row.leave_until) ?? row.leave_until}`,
      notable: true,
    });
  }
  // Liczba pasujących w bazie tłumaczy wybór SOURCERA (dużo osób w bazie =
  // wystarczy przeszukać bazę); przy rekruterze nic nie wyjaśnia.
  if (row.role === "sourcer" && row.base_matches != null) {
    reasons.push({
      text: `${row.base_matches} ${pluralPl(row.base_matches, "pasujący", "pasujących", "pasujących")} w bazie`,
      notable: false,
    });
  }
  return reasons;
}

export function proposalKey(row: { job_id: number; user_id: number }): string {
  return `${row.job_id}:${row.user_id}`;
}

/**
 * Osoby do wyboru w „Zmień”: proponowana na górze (punkt odniesienia), potem
 * od najmniej obłożonej; osoby na urlopie na końcu.
 */
export function replacementOptions(
  load: readonly LoadPerson[],
  proposedUserId: number,
  query: string,
): LoadPerson[] {
  const needle = fold(query.trim());
  return load
    .filter((person) => !needle || fold(person.name).includes(needle))
    .sort((a, b) => {
      const aProposed = a.user_id === proposedUserId;
      const bProposed = b.user_id === proposedUserId;
      if (aProposed !== bProposed) return aProposed ? -1 : 1;
      if (Boolean(a.leave_until) !== Boolean(b.leave_until)) return a.leave_until ? 1 : -1;
      return a.count - b.count || a.name.localeCompare(b.name, "pl");
    });
}

/** „Zaakceptowano 3 z 4. Jedna propozycja była już nieaktualna.” */
export function bulkAcceptMessage(accepted: number, total: number): string {
  const head = `Zaakceptowano ${accepted} z ${total}.`;
  const rest = total - accepted;
  if (rest <= 0) return head;
  if (rest === 1) return `${head} Jedna propozycja była już nieaktualna.`;
  return `${head} ${rest} ${pluralPl(rest, "propozycja była", "propozycje były", "propozycji było")} już ${pluralPl(rest, "nieaktualna", "nieaktualne", "nieaktualnych")}.`;
}

type RowAction = "accept" | "replace" | "reject";

function ReplacePicker({
  row,
  disabled,
  busy,
  onPick,
}: {
  row: AllocationProposalRow;
  disabled: boolean;
  busy: boolean;
  onPick: (person: LoadPerson) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Obłożenie czytamy dopiero po otwarciu listy: sekcja stoi na pulpicie
  // każdej osoby decydującej, a „Zmień” klika się rzadko.
  const board = useRequestBoard({ enabled: open });
  const people = useMemo(
    () => replacementOptions(board.data?.load ?? [], row.user_id, query),
    [board.data, row.user_id, query],
  );

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          loading={busy}
          aria-label={`Zmień osobę: ${row.title}`}
        >
          Zmień
          <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(340px,calc(100vw-2rem))] p-0">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Szukaj osoby…" value={query} onValueChange={setQuery} />
          <CommandList>
            {/* Awaria nie może wyglądać jak „nikogo nie ma”: pusty stan dopiero
                przy udanym odczycie. Błąd przy danych już wczytanych zostawia
                listę — to nadal lepsze źródło niż nic. */}
            <PickerQueryState
              isPending={board.isPending}
              isError={board.isError && board.data === undefined}
              onRetry={() => void board.refetch()}
              loadingLabel="Ładowanie osób…"
              errorLabel="Nie udało się pobrać listy osób."
            />
            {board.isSuccess && <CommandEmpty>Brak osób.</CommandEmpty>}
            <CommandGroup>
              {people.map((person) => {
                const proposed = person.user_id === row.user_id;
                const waiting = person.proposed ?? 0;
                return (
                  <CommandItem
                    key={person.user_id}
                    value={String(person.user_id)}
                    disabled={proposed}
                    onSelect={() => {
                      setOpen(false);
                      setQuery("");
                      onPick(person);
                    }}
                    className="justify-between gap-3"
                  >
                    <span className="min-w-0">
                      <span className={cn("block truncate", proposed && "font-medium")}>
                        {person.name}
                      </span>
                      {(proposed || person.leave_until) && (
                        <span className="block truncate text-xs text-muted-foreground">
                          {[
                            proposed ? "propozycja automatu" : null,
                            person.leave_until
                              ? `urlop do ${formatDeadlineShort(person.leave_until) ?? person.leave_until}`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                      <span className="block">
                        {person.count} {requestWord(person.count)}
                      </span>
                      {waiting > 0 && (
                        <span className="block">+ {waiting} do akceptacji</span>
                      )}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
        <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
          Wybrana osoba jest przypisana od razu.
        </p>
      </PopoverContent>
    </Popover>
  );
}

export interface AllocationProposalsSectionProps {
  rows: AllocationProposalRow[];
  /** `false` = brak świeżych urlopów z Compassa; brak urlopu znaczy wtedy „nie wiadomo”. */
  leaveKnown: boolean;
}

export function AllocationProposalsSection({ rows, leaveKnown }: AllocationProposalsSectionProps) {
  const queryClient = useQueryClient();
  const { showError, showInfo, showSuccess } = useToast();
  // Serwer wysyła wiersze tylko osobie decydującej; capability dokłada to,
  // czego serwer w odczycie nie mówi: zapis w sekcji Rekrutacje i brak
  // „podglądu jako” (tam każdy zapis kończy się odmową).
  const canAct = useCapability("request.proposal.decide");
  const [pending, setPending] = useState<Record<string, RowAction>>({});
  const [bulkPending, setBulkPending] = useState(false);

  if (rows.length === 0) return null;
  const anyRowPending = Object.keys(pending).length > 0;

  /** Rozstrzygnięte propozycje znikają od razu; odczyt z serwera potwierdza resztę. */
  const dropRows = (keys: ReadonlySet<string>) => {
    queryClient.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, (current) =>
      current?.allocation_proposals
        ? {
            ...current,
            allocation_proposals: current.allocation_proposals.filter(
              (row) => !keys.has(proposalKey(row)),
            ),
          }
        : current,
    );
  };

  const decide = async (
    row: AllocationProposalRow,
    action: RowAction,
    body: ProposalDecisionBody,
    onDone: () => void,
  ) => {
    const key = proposalKey(row);
    setPending((current) => ({ ...current, [key]: action }));
    try {
      await decideProposal(row.job_id, row.user_id, body);
      dropRows(new Set([key]));
      onDone();
    } catch (error) {
      // 409 = propozycja jest już nieaktualna; serwer mówi to po polsku.
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji."));
    } finally {
      setPending((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      // Także po błędzie — odmowa znaczy, że lista pokazuje stan, którego już nie ma.
      invalidateJobTeam(queryClient, row.job_id);
    }
  };

  const acceptAll = async () => {
    const targets = rows;
    setBulkPending(true);
    try {
      const results: ProposalAcceptResult[] = [];
      for (let start = 0; start < targets.length; start += MAX_BULK_ACCEPT) {
        results.push(
          ...(await acceptProposals(targets.slice(start, start + MAX_BULK_ACCEPT))),
        );
      }
      const accepted = results.filter((result) => result.status === "accepted").length;
      dropRows(new Set(results.map(proposalKey)));
      const message = bulkAcceptMessage(accepted, targets.length);
      if (accepted === targets.length) showSuccess(message);
      else showInfo(message);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zaakceptować propozycji."));
    } finally {
      setBulkPending(false);
      invalidateJobTeam(queryClient);
    }
  };

  return (
    <section
      aria-label="Propozycje automatu do akceptacji"
      className="@container/proposals min-w-0 lg:col-span-3"
    >
      <header className="mb-1 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Propozycje automatu do akceptacji</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {rows.length}
        </span>
        {/* Przy jednej propozycji przycisk powtarzałby „Akceptuj” z wiersza. */}
        {canAct && rows.length > 1 && (
          <Button
            type="button"
            size="sm"
            className="ml-auto"
            loading={bulkPending}
            disabled={anyRowPending}
            onClick={() => void acceptAll()}
          >
            Akceptuj wszystkie ({rows.length})
          </Button>
        )}
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        Automat proponuje osobę do requestu bez rekrutera. Dopóki nie zaakceptujesz, nikt nie
        jest przypisany i nikt nie dostaje powiadomienia.
        {canAct ? "" : " W tym widoku nie możesz podejmować decyzji o propozycjach."}
      </p>
      {!leaveKnown && (
        <p
          role="note"
          className="mb-2 flex items-start gap-2 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Brak danych o urlopach — propozycje ich nie uwzględniają.
        </p>
      )}
      <ul className="divide-y divide-border rounded-lg border border-border">
        {rows.map((row) => {
          const key = proposalKey(row);
          const action = pending[key];
          const locked = bulkPending || action !== undefined;
          const categoryLabel = row.category_name
            ? (competenceShortLabel(row.category_slug) ?? row.category_name)
            : null;
          const due = formatDeadlineShort(row.deadline);
          const meta: { key: string; node: ReactNode }[] = [];
          if (row.client_name) meta.push({ key: "client", node: row.client_name });
          if (categoryLabel) {
            meta.push({
              key: "category",
              node: (
                <Badge
                  variant={competenceTone(row.category_slug)}
                  size="sm"
                  title={row.category_name ?? undefined}
                >
                  {categoryLabel}
                </Badge>
              ),
            });
          }
          if (row.delivery_lead_name) {
            meta.push({
              key: "lead",
              node: (
                <span title={`Delivery Lead: ${row.delivery_lead_name}`}>
                  DL: {shortenPersonName(row.delivery_lead_name) ?? row.delivery_lead_name}
                </span>
              ),
            });
          }
          meta.push({
            key: "deadline",
            node: due ? (
              <span title={`Termin ${formatIsoDatePl(row.deadline)}`}>termin {due}</span>
            ) : (
              "bez terminu"
            ),
          });
          meta.push({ key: "sent", node: `wysłani ${row.sent}` });
          const reasons = proposalReasons(row);

          return (
            <li
              key={key}
              // Trzy strefy obok siebie dopiero od 780 px sekcji: request (260)
              // + osoba (220) + trzy przyciski (244) + odstępy i marginesy (56).
              // Węziej — jedna pod drugą.
              className="grid gap-x-4 gap-y-2 px-3 py-2.5 @min-[780px]/proposals:grid-cols-[minmax(0,1.25fr)_minmax(0,1.1fr)_auto] @min-[780px]/proposals:items-center"
            >
              <div className="min-w-0">
                <div className="flex min-w-0 items-start gap-1.5">
                  <Link
                    href={`/jobs/${row.job_id}`}
                    title={row.title}
                    className="min-w-0 truncate text-sm font-medium hover:underline"
                  >
                    {row.title}
                  </Link>
                  <RequestPriorityChip level={row.priority_level} className="mt-0.5 shrink-0" />
                </div>
                <p className="text-xs text-muted-foreground" data-testid="proposal-request-meta">
                  {meta.map((item, index) => (
                    <Fragment key={item.key}>
                      {index > 0 && <span aria-hidden> · </span>}
                      {item.node}
                    </Fragment>
                  ))}
                </p>
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm">
                  <span className="font-medium">{row.user_name}</span>{" "}
                  <span className="text-xs text-muted-foreground">
                    {ROLE_LABEL[row.role] ?? row.role}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground" data-testid="proposal-reasons">
                  {reasons.map((reason, index) => (
                    <Fragment key={reason.text}>
                      {index > 0 && <span aria-hidden> · </span>}
                      <span className={reason.notable ? "font-medium text-warning" : undefined}>
                        {reason.text}
                      </span>
                    </Fragment>
                  ))}
                </p>
              </div>
              {canAct && (
                <div className="flex flex-wrap items-center gap-1.5 @min-[780px]/proposals:justify-end">
                  <Button
                    type="button"
                    size="sm"
                    disabled={locked}
                    loading={action === "accept"}
                    aria-label={`Akceptuj: ${row.user_name} — ${row.title}`}
                    onClick={() =>
                      void decide(row, "accept", { decision: "accept" }, () =>
                        showSuccess(`${row.user_name} pracuje nad „${row.title}”.`),
                      )
                    }
                  >
                    Akceptuj
                  </Button>
                  <ReplacePicker
                    row={row}
                    disabled={locked}
                    busy={action === "replace"}
                    onPick={(person) =>
                      void decide(
                        row,
                        "replace",
                        { decision: "replace", replacement_user_id: person.user_id },
                        () =>
                          showSuccess(
                            `${person.name} pracuje nad „${row.title}” zamiast propozycji automatu.`,
                          ),
                      )
                    }
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={locked}
                    loading={action === "reject"}
                    aria-label={`Odrzuć: ${row.user_name} — ${row.title}`}
                    onClick={() =>
                      void decide(row, "reject", { decision: "reject" }, () =>
                        showInfo(
                          "Propozycja odrzucona. Automat nie zaproponuje już tej osoby do tego requestu.",
                        ),
                      )
                    }
                  >
                    Odrzuć
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
