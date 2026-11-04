"use client";

/**
 * Recepcja edycji Akademii (makieta „I”): wiersz na uczestnika — umowa, hotel,
 * bilet, zestaw, protokół — i check lista recepcji w 9 sekcjach z paskiem
 * postępu. Zestawy wydaje się hurtem („Wydaj zestawy”), tylko z uprawnieniem
 * „Sprzęt”. Sekcja jest widoczna przy włączonym module „Sprzęt”; dostępu
 * pilnuje serwer (recepcja albo osoba z dostępem do Akademii).
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { PROTOCOL_STATUS_LABELS } from "@/components/equipment/equipment-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cohortLabel, shortDate } from "@/lib/academy-flow";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CONTRACT_LABELS,
  KIT_LABELS,
  LOGISTICS_LABELS,
  LOGISTICS_ORDER,
  defaultEdition,
  editionRef,
  useAcademyEdition,
  useAcademyEditions,
  useSetChecklistItem,
  useSetParticipantLogistics,
  type ChecklistSection,
  type ContractState,
  type EditionInfo,
  type EditionParticipant,
  type EditionRef,
  type EditionView,
  type KitState,
  type LogisticsStatus,
} from "@/lib/api/academy-edition";
import { useHrConfig } from "@/lib/api/hr";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import { EditionKitDialog } from "./EditionKitDialog";

const CONTRACT_TONE: Record<ContractState, StatusDotTone> = {
  brak: "warning",
  dokumenty: "neutral",
  wyslana: "info",
  podpisana: "success",
  rezygnacja: "danger",
  wykluczenie: "danger",
};

const KIT_TONE: Record<KitState, StatusDotTone> = {
  brak: "neutral",
  wydany: "success",
  do_zwrotu: "danger",
  zwrocony: "neutral",
};

/** Kogo można zaznaczyć do „Wydaj zestawy”: jest w edycji i nie ma zestawu. */
export function canReceiveKit(participant: EditionParticipant): boolean {
  return !participant.left && participant.kit.state !== "wydany";
}

/** Procent postępu sekcji (0 przy pustej sekcji). */
export function sectionProgress(section: Pick<ChecklistSection, "done" | "total">): number {
  return section.total ? Math.round((section.done / section.total) * 100) : 0;
}

/** „listopad 2026 · 02.11–16.11” (z nazwą programu, gdy lista obejmuje wszystkie). */
export function editionLabel(edition: EditionInfo, withProgram: boolean): string {
  const dates = `${cohortLabel(edition.cohort_month)} · ${shortDate(edition.starts_on)}–${shortDate(
    edition.ends_on,
  )}`;
  return withProgram ? `${edition.program_name} · ${dates}` : dates;
}

/**
 * Recepcja edycji — tylko przy włączonym module „Sprzęt”. Z `programId`
 * (ekran Akademii) edycje jednego programu; bez niego (zakładka „Akademia”
 * w Sprzęcie) wszystkie programy.
 */
export function EditionLogistics({ programId = null }: { programId?: number | null }) {
  const config = useHrConfig();
  if (!config.isSuccess || !config.data.open_modules.equipment) return null;
  return <EditionPicker programId={programId} />;
}

function EditionPicker({ programId }: { programId: number | null }) {
  const editions = useAcademyEditions(programId);
  const [chosen, setChosen] = useState<string | null>(null);
  const items = editions.data ?? [];
  const state = resolveViewState({
    isLoading: editions.isLoading,
    error: editions.error,
    isSuccess: editions.isSuccess,
    isEmpty: items.length === 0,
  });
  const idOf = (edition: EditionInfo) => `${edition.program_id}:${edition.key}`;
  const current =
    items.find((edition) => idOf(edition) === chosen) ?? defaultEdition(items, warsawToday());
  const withProgram = programId == null;

  return (
    <section aria-label="Recepcja edycji" className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold">Recepcja edycji</h2>
        {items.length > 1 && current ? (
          <Select value={idOf(current)} onValueChange={setChosen}>
            <SelectTrigger aria-label="Edycja" className="h-8 w-auto min-w-56 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {items.map((edition) => (
                <SelectItem key={idOf(edition)} value={idOf(edition)}>
                  {editionLabel(edition, withProgram)} · {edition.participants} os.
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie edycji…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => editions.refetch()} />
      ) : state === "empty" || current == null ? (
        <p className="text-sm text-muted-foreground">
          Brak uczestników po zaliczonym zadaniu — lista recepcji pojawi się przy pierwszej
          osobie, która zaliczy zadanie.
        </p>
      ) : (
        <EditionDetail key={idOf(current)} edition={editionRef(current)} />
      )}
    </section>
  );
}

function EditionDetail({ edition: ref }: { edition: EditionRef }) {
  const edition = useAcademyEdition(ref);
  const state = resolveViewState({
    isLoading: edition.isLoading,
    error: edition.error,
    isSuccess: edition.isSuccess,
  });
  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Wczytywanie listy edycji…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !edition.data) {
    const blocking = state === "forbidden" || state === "not_found" ? state : "error";
    return <QueryStateNotice state={blocking} onRetry={() => edition.refetch()} />;
  }
  return <EditionBoard data={edition.data} />;
}

export function EditionBoard({ data }: { data: EditionView }) {
  const eligible = useMemo(() => data.participants.filter(canReceiveKit), [data.participants]);
  const [selected, setSelected] = useState<ReadonlySet<number>>(
    () => new Set(eligible.filter((p) => p.kit.state === "brak").map((p) => p.application_id)),
  );
  const [issuing, setIssuing] = useState(false);
  const chosen = eligible.filter((p) => selected.has(p.application_id));
  const { summary } = data;
  const present = summary.participants;
  const ref = editionRef(data.edition);

  const toggle = (id: number, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm">
          <span className="font-medium">{data.edition.program_name}</span>
          <span className="text-muted-foreground">
            {" "}
            · {editionLabel(data.edition, false)} · {present} uczestników
          </span>
        </p>
        <InlineStats
          id={`edition-${data.edition.program_id}-${data.edition.key}-stats`}
          className="ml-auto"
          stats={[
            { id: "contracts", label: "umowy podpisane", value: `${summary.contracts_signed}/${present}` },
            { id: "kits", label: "zestawy wydane", value: `${summary.kits_issued}/${present}` },
            {
              id: "protocols",
              label: "protokoły potwierdzone",
              value: `${summary.protocols_confirmed}/${present}`,
            },
            { id: "logistics", label: "hotel i bilety do zrobienia", value: summary.logistics_open },
            { id: "checklist", label: "lista edycji", value: `${data.checklist_done}/${data.checklist_total}` },
          ]}
        />
        {data.can_issue ? (
          <Button size="sm" disabled={chosen.length === 0} onClick={() => setIssuing(true)}>
            Wydaj zestawy ({chosen.length})
          </Button>
        ) : null}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_17rem]">
        <ParticipantsTable
          data={data}
          selectable={data.can_issue}
          selected={selected}
          onToggle={toggle}
        />
        <Checklist edition={ref} sections={data.checklist} />
      </div>
      {issuing ? (
        <EditionKitDialog
          edition={ref}
          participants={chosen}
          onClose={() => {
            setIssuing(false);
            setSelected(new Set());
          }}
        />
      ) : null}
    </div>
  );
}

function ParticipantsTable({
  data,
  selectable,
  selected,
  onToggle,
}: {
  data: EditionView;
  selectable: boolean;
  selected: ReadonlySet<number>;
  onToggle: (id: number, on: boolean) => void;
}) {
  const toast = useToast();
  const logistics = useSetParticipantLogistics(editionRef(data.edition));
  if (data.participants.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        W tej edycji nie ma jeszcze nikogo po zaliczonym zadaniu.
      </p>
    );
  }
  const save = (person: EditionParticipant, field: "hotel" | "ticket", value: LogisticsStatus) =>
    logistics.mutate(
      { applicationId: person.application_id, [field]: value },
      {
        onError: (err) =>
          toast.showError(apiErrorMessage(err, "Nie udało się zapisać hotelu albo biletu.")),
      },
    );

  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className={CALM_ROW}>
            {selectable ? <th className="w-8 px-2 py-1.5" aria-label="Zaznacz" /> : null}
            <th className={`${CALM_HEAD} px-2 py-1.5 text-left`}>Uczestnik</th>
            <th className={`${CALM_HEAD} px-2 py-1.5 text-left`}>Umowa</th>
            <th className={`${CALM_HEAD} px-2 py-1.5 text-left`}>Hotel</th>
            <th className={`${CALM_HEAD} px-2 py-1.5 text-left`}>Bilet</th>
            <th className={`${CALM_HEAD} px-2 py-1.5 text-left`}>Zestaw</th>
            <th className={`${CALM_HEAD} px-2 py-1.5 text-left`}>Protokół</th>
          </tr>
        </thead>
        <tbody>
          {data.participants.map((person) => (
            <tr
              key={person.application_id}
              className={person.left ? `${CALM_ROW} text-muted-foreground` : CALM_ROW}
            >
              {selectable ? (
                <td className="px-2 py-1.5 align-top">
                  {canReceiveKit(person) ? (
                    <Checkbox
                      aria-label={`Wydaj zestaw: ${person.full_name}`}
                      checked={selected.has(person.application_id)}
                      onCheckedChange={(checked) =>
                        onToggle(person.application_id, checked === true)
                      }
                    />
                  ) : null}
                </td>
              ) : null}
              <td className="px-2 py-1.5 align-top">
                <span className="block font-medium text-foreground">{person.full_name}</span>
                <span className={CALM_SUBLINE}>{person.city ?? person.status_label}</span>
              </td>
              <td className="px-2 py-1.5 align-top">
                <StatusDot tone={CONTRACT_TONE[person.contract.state]}>
                  {CONTRACT_LABELS[person.contract.state]}
                </StatusDot>
              </td>
              <td className="px-2 py-1.5 align-top">
                <LogisticsSelect
                  label={`Hotel: ${person.full_name}`}
                  value={person.hotel}
                  disabled={logistics.isPending}
                  onChange={(value) => save(person, "hotel", value)}
                />
              </td>
              <td className="px-2 py-1.5 align-top">
                <LogisticsSelect
                  label={`Bilet: ${person.full_name}`}
                  value={person.ticket}
                  disabled={logistics.isPending}
                  onChange={(value) => save(person, "ticket", value)}
                />
              </td>
              <td className="px-2 py-1.5 align-top">
                <StatusDot
                  tone={KIT_TONE[person.kit.state]}
                  note={
                    person.kit.items.length
                      ? `${person.kit.items.length} poz.`
                      : undefined
                  }
                >
                  {KIT_LABELS[person.kit.state]}
                </StatusDot>
              </td>
              <td className="px-2 py-1.5 align-top">
                {person.protocol ? (
                  <StatusDot
                    tone={person.protocol.status === "potwierdzony" ? "success" : "warning"}
                    note={person.protocol.number}
                  >
                    {PROTOCOL_STATUS_LABELS[person.protocol.status]}
                  </StatusDot>
                ) : (
                  <span className="text-muted-foreground/50">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogisticsSelect({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: LogisticsStatus;
  disabled?: boolean;
  onChange: (value: LogisticsStatus) => void;
}) {
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => {
        const status = LOGISTICS_ORDER.find((option) => option === next);
        if (status && status !== value) onChange(status);
      }}
    >
      <SelectTrigger aria-label={label} className="h-7 w-28 gap-1 px-2 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {LOGISTICS_ORDER.map((option) => (
          <SelectItem key={option} value={option}>
            {LOGISTICS_LABELS[option]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function Checklist({ edition, sections }: { edition: EditionRef; sections: ChecklistSection[] }) {
  const toast = useToast();
  const setItem = useSetChecklistItem(edition);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <section aria-label="Lista edycji" className="space-y-1">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Lista edycji
      </h3>
      <ul className="divide-y divide-border rounded-md border border-border">
        {sections.map((section) => {
          const expanded = open === section.key;
          const Icon = expanded ? ChevronDown : ChevronRight;
          return (
            <li key={section.key}>
              <button
                type="button"
                aria-expanded={expanded}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-muted"
                onClick={() => setOpen(expanded ? null : section.key)}
              >
                <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="flex justify-between gap-2">
                    <span className="truncate font-medium">{section.label}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {section.done}/{section.total}
                    </span>
                  </span>
                  <Progress
                    value={sectionProgress(section)}
                    aria-label={`${section.label}: ${section.done} z ${section.total}`}
                    className="mt-1 h-1"
                  />
                </span>
              </button>
              {expanded ? (
                <ul className="space-y-1 px-2.5 pb-2">
                  {section.items.map((item) => {
                    const id = `edition-item-${item.id}`;
                    return (
                      <li key={item.id} className="flex items-start gap-2 text-xs">
                        <Checkbox
                          id={id}
                          className="mt-0.5"
                          checked={item.done}
                          disabled={setItem.isPending}
                          onCheckedChange={(checked) =>
                            setItem.mutate(
                              { itemId: item.id, done: checked === true },
                              {
                                onError: (err) =>
                                  toast.showError(
                                    apiErrorMessage(err, "Nie udało się zapisać punktu."),
                                  ),
                              },
                            )
                          }
                        />
                        <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer">
                          <span className={item.done ? "text-muted-foreground line-through" : ""}>
                            {item.label}
                          </span>
                          {item.done && item.done_by ? (
                            <span className="block text-[11px] text-muted-foreground">
                              {item.done_by}
                            </span>
                          ) : null}
                          {item.note ? (
                            <span className="block text-[11px] text-muted-foreground">
                              {item.note}
                            </span>
                          ) : null}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
      <p className="text-[11px] leading-4 text-muted-foreground">
        Umowy, zestawy i protokoły uczestników widać w tabeli; punkty listy odhaczasz ręcznie.
      </p>
    </section>
  );
}
