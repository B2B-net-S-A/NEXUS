"use client";

import { useState } from "react";
import { Briefcase, Check, ChevronDown } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import {
  recruitmentClientContext,
  recruitmentClientLabel,
  recruitmentItemContext,
  useRecruitmentLabels,
  useRecruitmentSearch,
  type RecruitmentLookupClient,
  type RecruitmentLookupItem,
  type RecruitmentLookupStatus,
} from "@/lib/recruitment-lookup";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
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
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";

// Nagłówki grup jak w pozostałych listach poleceń (goły `Command` ich nie stylizuje).
const GROUP_CLASS =
  "p-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground";

const STATUS_OPTIONS: ReadonlyArray<{ value: RecruitmentLookupStatus; label: string }> = [
  { value: "open", label: "Otwarte" },
  { value: "closed", label: "Zamknięte" },
  { value: "all", label: "Wszystkie" },
];

interface RecruitmentScopePickerProps {
  recruitmentIds: number[];
  clientIds: number[];
  onChange: (recruitmentIds: number[], clientIds: number[]) => void;
}

/**
 * Zakres bloku „Rekrutacje”: wybrane rekrutacje i/albo „wszystkie rekrutacje
 * klienta”. Pusty wybór znaczy „Wszystkie rekrutacje”.
 *
 * Szukanie idzie do serwera (rekrutacji jest kilka tysięcy, tytuły się
 * powtarzają), a „cały klient” to jedna pozycja — największy klient ma ponad
 * dwa tysiące rekrutacji i dochodzą nowe.
 */
export function RecruitmentScopePicker({
  recruitmentIds,
  clientIds,
  onChange,
}: RecruitmentScopePickerProps) {
  const [open, setOpen] = useState(false);
  // Na laptopie lista otwiera się OBOK okienka filtra: pod przyciskiem zostaje
  // przy 1280 × 720 miejsce na dwa i pół wiersza. Wąski ekran nie ma miejsca
  // z boku, więc tam lista zostaje pod przyciskiem.
  const [beside, setBeside] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<RecruitmentLookupStatus>("open");
  const debouncedQuery = useDebouncedValue(query.trim(), 250);
  const search = useRecruitmentSearch(debouncedQuery, status, open);
  const labels = useRecruitmentLabels(recruitmentIds, clientIds);

  const foundJobs = search.isSuccess ? search.data.items : [];
  const foundClients = search.isSuccess ? search.data.clients : [];
  const total = search.isSuccess ? search.data.total : 0;

  // Nazwy wybranych pozycji: z etykiet, a zanim wrócą — z tego, co już widać na liście.
  const knownJobs = new Map<number, RecruitmentLookupItem>();
  for (const item of [...foundJobs, ...(labels.data?.items ?? [])]) knownJobs.set(item.id, item);
  const knownClients = new Map<number, RecruitmentLookupClient>();
  for (const client of [...foundClients, ...(labels.data?.clients ?? [])]) {
    knownClients.set(client.id, client);
  }

  const selectedJobs = new Set(recruitmentIds);
  const selectedClients = new Set(clientIds);
  const selectedCount = recruitmentIds.length + clientIds.length;

  const toggleJob = (id: number) =>
    onChange(
      selectedJobs.has(id) ? recruitmentIds.filter((x) => x !== id) : [...recruitmentIds, id],
      clientIds,
    );
  const toggleClient = (id: number) =>
    onChange(
      recruitmentIds,
      selectedClients.has(id) ? clientIds.filter((x) => x !== id) : [...clientIds, id],
    );

  // Wybrane pozycje, których nie ma na bieżącej liście (inny status, dalsza
  // strona) — bez tej grupy nie dałoby się ich odznaczyć.
  const foundJobIds = new Set(foundJobs.map((item) => item.id));
  const foundClientIds = new Set(foundClients.map((client) => client.id));
  const showChosen = debouncedQuery === "";
  const chosenClients = showChosen ? clientIds.filter((id) => !foundClientIds.has(id)) : [];
  const chosenJobs = showChosen ? recruitmentIds.filter((id) => !foundJobIds.has(id)) : [];
  const nothingListed =
    foundJobs.length === 0 &&
    foundClients.length === 0 &&
    chosenJobs.length === 0 &&
    chosenClients.length === 0;

  let triggerLabel = "Wszystkie rekrutacje";
  if (selectedCount > 1) {
    triggerLabel = `Wybrano: ${selectedCount}`;
  } else if (recruitmentIds.length === 1) {
    const item = knownJobs.get(recruitmentIds[0]);
    triggerLabel = item
      ? `${item.title} · ${recruitmentItemContext(item)}`
      : `#${recruitmentIds[0]}`;
  } else if (clientIds.length === 1) {
    const client = knownClients.get(clientIds[0]);
    triggerLabel = client ? recruitmentClientLabel(client.name) : `Klient #${clientIds[0]}`;
  }

  const jobRow = (id: number) => {
    const item = knownJobs.get(id);
    const checked = selectedJobs.has(id);
    return (
      <CommandItem
        key={`job:${id}`}
        value={`job:${id}`}
        aria-checked={checked}
        onSelect={() => toggleJob(id)}
        className="items-start"
      >
        <Check className={cn("mt-0.5 h-4 w-4 shrink-0", checked ? "opacity-100" : "opacity-0")} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{item ? item.title : `#${id}`}</span>
          {item && (
            <span className="block truncate text-xs text-muted-foreground">
              {recruitmentItemContext(item)}
            </span>
          )}
        </span>
        {item && (
          <Badge variant={item.status === "open" ? "success" : "neutral"} size="sm">
            {item.status === "open" ? "Otwarta" : "Zamknięta"}
          </Badge>
        )}
      </CommandItem>
    );
  };

  const clientRow = (id: number) => {
    const client = knownClients.get(id);
    const checked = selectedClients.has(id);
    return (
      <CommandItem
        key={`client:${id}`}
        value={`client:${id}`}
        aria-checked={checked}
        onSelect={() => toggleClient(id)}
        className="items-start"
      >
        <Check className={cn("mt-0.5 h-4 w-4 shrink-0", checked ? "opacity-100" : "opacity-0")} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">
            {client ? recruitmentClientLabel(client.name) : `Klient #${id}`}
          </span>
          {client && (
            <span className="block truncate text-xs text-muted-foreground">
              {recruitmentClientContext(client)}
            </span>
          )}
        </span>
        <Badge variant="soft" size="sm">
          Klient
        </Badge>
      </CommandItem>
    );
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) setBeside(window.matchMedia?.("(min-width: 1024px)").matches ?? false);
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          size="md"
          variant="outline"
          aria-expanded={open}
          className="w-full justify-between"
        >
          <span className="flex min-w-0 items-center gap-2">
            <Briefcase className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{triggerLabel}</span>
          </span>
          <ChevronDown className="h-4 w-4 shrink-0 opacity-60" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        side={beside ? "right" : "bottom"}
        collisionPadding={8}
        className={cn("p-0", beside ? "w-[400px]" : "w-(--radix-popover-trigger-width) min-w-72")}
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Szukaj po nazwie, kliencie albo numerze…"
            value={query}
            onValueChange={setQuery}
            className="h-9"
          />
          {/* Enter i strzałki na przełączniku należą do niego — cmdk zaznaczałby
              nimi podświetlony wiersz listy. */}
          <div
            className="border-b border-border px-2 py-1.5"
            onKeyDown={(event) => event.stopPropagation()}
          >
            <SegmentedRadio
              size="sm"
              label="Status rekrutacji"
              value={status}
              onChange={setStatus}
              options={STATUS_OPTIONS}
            />
          </div>
          <CommandList
            label="Rekrutacje"
            className="max-h-[min(360px,calc(var(--radix-popover-content-available-height)-9.5rem))]"
          >
            <PickerQueryState
              isPending={search.isPending}
              isError={search.isError}
              onRetry={() => void search.refetch()}
              loadingLabel="Ładowanie rekrutacji…"
              errorLabel={apiErrorMessage(
                search.error,
                "Nie udało się pobrać listy rekrutacji.",
              )}
            />
            {search.isSuccess && nothingListed && (
              <CommandEmpty>Brak rekrutacji dla tego wyszukiwania.</CommandEmpty>
            )}
            {search.isSuccess && (chosenClients.length > 0 || chosenJobs.length > 0) && (
              <CommandGroup heading="Wybrane" className={GROUP_CLASS}>
                {chosenClients.map(clientRow)}
                {chosenJobs.map(jobRow)}
              </CommandGroup>
            )}
            {foundClients.length > 0 && (
              <CommandGroup heading="Klienci" className={GROUP_CLASS}>
                {foundClients.map((client) => clientRow(client.id))}
              </CommandGroup>
            )}
            {foundJobs.length > 0 && (
              <CommandGroup heading="Rekrutacje" className={GROUP_CLASS}>
                {foundJobs.map((item) => jobRow(item.id))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
        {/* Stopka stoi POZA `<Command>`: w środku Enter na „Gotowe” albo „Wyczyść”
            zaznaczałby podświetlony wiersz listy zamiast wykonać przycisk. */}
        <div className="space-y-1.5 border-t border-border bg-muted px-3 py-2">
          {search.isSuccess && total > foundJobs.length && (
            <p className="text-[11px] text-muted-foreground">
              Pokazano {foundJobs.length} z {total} — zawęź wyszukiwanie.
            </p>
          )}
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">
              {selectedCount > 0
                ? `Wybrano: ${selectedCount}`
                : "Nic nie wybrano — liczą się wszystkie"}
            </span>
            <span className="flex items-center gap-1.5">
              {selectedCount > 0 && (
                <button
                  type="button"
                  onClick={() => onChange([], [])}
                  className="rounded-md px-2 py-1 text-xs text-muted-foreground underline hover:text-foreground"
                >
                  Wyczyść
                </button>
              )}
              <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
                Gotowe
              </Button>
            </span>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
