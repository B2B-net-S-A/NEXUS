"use client";

import { useRef, useState, type ReactNode } from "react";
import { useIsFetching, useQuery } from "@tanstack/react-query";
import { Pencil } from "lucide-react";

import api from "@/lib/api";
import { useRequestBoard } from "@/lib/api/requestAllocation";
import { formatDeadlineShort } from "@/lib/job-header-subtitle";
import {
  hasWorkingOwner,
  recruitersOf,
  recruitersSummary,
  workingRecruiters,
  type JobRecruiter,
  type JobTeamSource,
} from "@/lib/job-team";
import {
  boardPeople,
  recruiterPickOptions,
  requestWord,
  type DirectoryPerson,
  type RecruiterPickOption,
} from "@/lib/request-board";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import { RecruiterChips } from "./RecruiterChips";
import { useRecruiterActions, type RecruiterActions } from "./useRecruiterActions";

export interface RecruiterCellEditorProps {
  jobId: number;
  jobTitle: string;
  job: JobTeamSource;
  /** Akceptuje i odrzuca propozycje automatu (`request.proposal.decide`). */
  canDecide: boolean;
  /** Treść komórki: osoby albo „Bez rekrutera”. */
  children: ReactNode;
}

const GROUP_CLASS =
  "p-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground";

const LINK_BUTTON_CLASS =
  "hit-area inline-flex items-center text-[11px] font-medium text-primary hover:underline disabled:pointer-events-none disabled:opacity-50";

/**
 * Kolumna „Rekruter” listy rekrutacji z edycją (prośba Head of Recruitment, 14.10.2026):
 * klik w osoby otwiera okienko, w którym rola przydzielająca zdejmuje osobę,
 * przypisuje albo dodaje rekrutera i rozstrzyga propozycję automatu — bez
 * wchodzenia w podgląd. Zapisy i komunikaty są te same co w panelu „Zespół”
 * (`useRecruiterActions`); widoczność rozstrzyga wołający, serwer i tak
 * pilnuje bramki.
 */
export function RecruiterCellEditor({
  jobId,
  jobTitle,
  job,
  canDecide,
  children,
}: RecruiterCellEditorProps) {
  const [open, setOpen] = useState(false);
  // Zapis żyje w komórce, nie w treści okienka: zamknięcie i ponowne otwarcie
  // w trakcie zapisu nie może zdjąć blokady akcji.
  const actions = useRecruiterActions({ jobId, canStaff: true });
  // `aria-label` zastępuje treść przycisku, więc niesie też obecną obsadę.
  const staffed = recruitersSummary(recruitersOf(job)).tooltip || "Bez rekrutera";
  return (
    // Zdarzenia React z portali (okienko, potwierdzenie) idą po drzewie
    // komponentów do wiersza tabeli, a klik w wiersz otwiera rekrutację.
    <div className="min-w-0" onClick={(e) => e.stopPropagation()}>
      {/* `modal`: klik obok tylko zamyka okienko — nie otwiera innego wiersza. */}
      <Popover modal open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={`Zmień rekrutera: ${jobTitle} — ${staffed}`}
            className="group relative flex min-w-0 max-w-full rounded-md text-left outline-hidden hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
          >
            {children}
            {/* Ołówek nie zajmuje miejsca w kolumnie (120 px przy 1280 px);
                na myszce widać go po najechaniu, na dotyku zawsze. */}
            <Pencil
              aria-hidden="true"
              className="absolute -right-3.5 top-0.5 h-3 w-3 text-muted-foreground pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:group-focus-visible:opacity-100"
            />
          </button>
        </PopoverTrigger>
        {open ? (
          <EditorContent
            jobTitle={jobTitle}
            job={job}
            canDecide={canDecide}
            actions={actions}
          />
        ) : null}
      </Popover>
      {actions.confirmDialog}
    </div>
  );
}

function EditorContent({
  jobTitle,
  job,
  canDecide,
  actions,
}: Omit<RecruiterCellEditorProps, "children" | "jobId"> & {
  actions: RecruiterActions;
}) {
  // Po zapisie lista odświeża wiersz; do tego czasu `job` jest sprzed zapisu
  // i wybór po „×” prowadzącego poszedłby jako współpracownik.
  const listFetching = useIsFetching({ queryKey: ["jobs-v2"] }) > 0;
  const busy = actions.pending != null || listFetching;
  const contentRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");

  // Ten sam klucz co `PersonPicker` i pasek filtrów listy — jedno zapytanie.
  const directory = useQuery<DirectoryPerson[]>({
    queryKey: ["users-directory"],
    queryFn: () => api.get("/api/users").then((r) => r.data),
    staleTime: 60_000,
  });
  const board = useRequestBoard();

  const all = recruitersOf(job);
  // Propozycja automatu tylko przy rekrutacji, nad którą nikt nie pracuje —
  // przy obsadzonej „Akceptuj” kończyłoby się 409.
  const people = boardPeople({ people: all });
  const working = workingRecruiters(all);
  const proposal = people.find((person) => person.proposed) ?? null;
  const options = recruiterPickOptions(
    Array.isArray(directory.data) ? directory.data : [],
    Array.isArray(board.data?.load) ? board.data.load : null,
    working.map((person) => person.user_id),
    query,
  );

  const pick = (option: RecruiterPickOption) => {
    const user = { id: option.user_id, name: option.name };
    // Wybór przy propozycji to decyzja o niej — liczy się do trafności
    // automatu (jak „Akceptuj” i „Zmień” w panelu „Zespół”). Wybór samej
    // proponowanej osoby to akceptacja, nie zamiana na nią samą.
    if (proposal && canDecide) {
      void (option.user_id === proposal.user_id
        ? actions.decide(proposal, "accept")
        : actions.replaceProposal(proposal, user));
      return;
    }
    void actions.add(user, { hasWorkingOwner: hasWorkingOwner(all) });
  };

  const remove = async (person: JobRecruiter) => {
    await actions.remove(person);
    searchRef.current?.focus();
  };

  return (
    <>
      <PopoverContent
        ref={contentRef}
        align="start"
        // Kolumna stoi przy prawej krawędzi — okienko nie przykleja się do niej.
        collisionPadding={8}
        className="w-[min(340px,calc(100vw-2rem))] p-0"
        onOpenAutoFocus={(event) => {
          // Fokus w polu szukania, nie na pierwszym „×” albo „Akceptuj” —
          // Enter zaraz po otwarciu nie może nikogo zdjąć. Na dotyku bez
          // klawiatury ekranowej.
          event.preventDefault();
          const fine = window.matchMedia?.("(pointer: fine)")?.matches ?? true;
          if (fine) searchRef.current?.focus();
          else contentRef.current?.focus();
        }}
      >
        <div className="space-y-2 border-b border-border px-3 py-2.5">
          <p className="truncate text-sm font-medium text-foreground" title={jobTitle}>
            Rekruter · {jobTitle}
          </p>
          <RecruiterChips
            people={people}
            size="sm"
            label={`Rekruter: ${jobTitle}`}
            onRemove={(person) => void remove(person)}
            canRemove={(person) => !busy && !person.proposed}
            caption={(person) =>
              person.proposed && !canDecide
                ? "czeka na akceptację Head of Recruitment"
                : null
            }
            proposalActions={
              canDecide
                ? (person) => (
                    <>
                      <Button
                        type="button"
                        size="sm"
                        variant="primary"
                        loading={actions.pending === `accept:${person.user_id}`}
                        disabled={busy}
                        onClick={() => void actions.decide(person, "accept")}
                      >
                        Akceptuj
                      </Button>
                      <button
                        type="button"
                        className={LINK_BUTTON_CLASS}
                        disabled={busy}
                        onClick={() => void actions.decide(person, "reject")}
                      >
                        Odrzuć
                      </button>
                    </>
                  )
                : undefined
            }
            emptyLabel={
              <span className="inline-flex h-6 items-center rounded-full bg-warning-muted px-2.5 text-xs font-medium text-warning-muted-foreground">
                Bez rekrutera
              </span>
            }
          />
        </div>
        <Command shouldFilter={false}>
          <CommandInput
            ref={searchRef}
            placeholder="Szukaj rekrutera…"
            aria-label={
              working.length > 0 ? "Dodaj kolejną osobę" : "Przypisz rekrutera"
            }
            value={query}
            onValueChange={setQuery}
          />
          <CommandList className="max-h-[min(300px,calc(100dvh-14rem))]">
            {/* Lista wisi na katalogu osób: jego awaria to błąd, nie „nikogo
                nie ma”. Obłożenie jest dodatkiem — bez niego da się przypisać. */}
            <PickerQueryState
              isPending={directory.isPending}
              isError={directory.isError && directory.data === undefined}
              onRetry={() => void directory.refetch()}
              loadingLabel="Ładowanie listy osób…"
              errorLabel="Nie udało się pobrać listy osób."
            />
            {directory.isSuccess && (
              <CommandEmpty>
                {query.trim()
                  ? "Nikt nie pasuje do wyszukiwania."
                  : "Wszyscy rekruterzy już pracują nad tą rekrutacją."}
              </CommandEmpty>
            )}
            <CommandGroup
              heading={
                working.length > 0 ? "Dodaj kolejną osobę" : "Przypisz rekrutera"
              }
              className={GROUP_CLASS}
            >
              {options.map((option) => (
                <CommandItem
                  key={option.user_id}
                  value={String(option.user_id)}
                  disabled={busy}
                  onSelect={() => pick(option)}
                  className="justify-between gap-3"
                >
                  <span className="min-w-0">
                    <span className="block truncate">{option.name}</span>
                    {option.leave_until ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        urlop do{" "}
                        {formatDeadlineShort(option.leave_until) ?? option.leave_until}
                      </span>
                    ) : null}
                  </span>
                  {option.count !== null ? (
                    <span className="shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                      <span className="block">
                        {option.count} {requestWord(option.count)}
                      </span>
                      {option.proposed > 0 ? (
                        <span className="block">+ {option.proposed} do akceptacji</span>
                      ) : null}
                    </span>
                  ) : null}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          <LoadFooter
            failed={board.isError && board.data === undefined}
            availabilityKnown={board.data?.availability_known ?? true}
            onRetry={() => void board.refetch()}
          />
        </Command>
      </PopoverContent>
    </>
  );
}

/** Stan obłożenia pod listą: awaria albo brak danych o urlopach. */
function LoadFooter({
  failed,
  availabilityKnown,
  onRetry,
}: {
  failed: boolean;
  availabilityKnown: boolean;
  onRetry: () => void;
}) {
  if (!failed && availabilityKnown) return null;
  return (
    <p className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
      {failed ? (
        <>
          Nie udało się pobrać obłożenia.{" "}
          <button type="button" className={LINK_BUTTON_CLASS} onClick={onRetry}>
            Spróbuj ponownie
          </button>
        </>
      ) : (
        "Brak danych o urlopach — lista ich nie uwzględnia."
      )}
    </p>
  );
}
