"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { peopleCount } from "@/components/hr/lifecycle/lifecycle-format";
import { apiErrorMessage } from "@/lib/api-error";
import {
  managerWords,
  useReassignManager,
  type HrStructure,
  type StructurePerson,
} from "@/lib/api/hr-structure";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { DivisionDialog, ReassignDialog } from "./StructureDialogs";
import { todoItems, type TodoItem } from "./structure-tree";

interface DialogState {
  kind: "reassign" | "division" | null;
  people: StructurePerson[];
}

/**
 * Sekcja „Struktura” w panelu „Porządki” (22.10.2026; wcześniej panel
 * „Do uporządkowania” obok schematu): odejście z ludźmi w zespole, koordynator,
 * który odszedł, rozjazd z Microsoft 365, podpowiedź „head pionu”, osoby bez
 * koordynatora i bez pionu. „Przyjmij” = zwykła zmiana koordynatora.
 */
export function StructureTodoSection({ data }: { data: HrStructure }) {
  const items = useMemo(() => todoItems(data), [data]);
  const [dialog, setDialog] = useState<DialogState>({ kind: null, people: [] });
  const candidates = data.people.map((person) => ({ user_id: person.user_id, name: person.name }));
  const close = () => setDialog({ kind: null, people: [] });
  return (
    <>
      <StructureTodoList
        data={data}
        items={items}
        onReassign={(person) => setDialog({ kind: "reassign", people: [person] })}
        onDivision={(person) => setDialog({ kind: "division", people: [person] })}
      />
      {dialog.kind === "reassign" ? (
        <ReassignDialog
          people={dialog.people}
          candidates={candidates}
          open
          onOpenChange={(value) => (value ? null : close())}
          onDone={() => undefined}
        />
      ) : null}
      {dialog.kind === "division" ? (
        <DivisionDialog
          people={dialog.people}
          open
          onOpenChange={(value) => (value ? null : close())}
          onDone={() => undefined}
        />
      ) : null}
    </>
  );
}

export function StructureTodoList({
  data,
  items,
  onReassign,
  onDivision,
}: {
  data: HrStructure;
  items: TodoItem[];
  onReassign: (person: StructurePerson) => void;
  onDivision: (person: StructurePerson) => void;
}) {
  const { showToast } = useToast();
  const reassign = useReassignManager();
  const accept = (person: StructurePerson, managerId: number, label: string) => {
    const words = managerWords([person.employment_type]);
    reassign.mutate(
      { user_ids: [person.user_id], manager_user_id: managerId },
      {
        onSuccess: () => showToast(`${person.name}: ${words.one} — ${label}`, "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać zmiany."), "error"),
      },
    );
  };
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">Wszystko poukładane.</p>;
  }
  return (
    <ul aria-label="Do uporządkowania w strukturze" className="divide-y divide-border/60">
      {items.map((item) => (
        <li key={`${item.kind}-${item.person.user_id}`} className="space-y-1.5 py-3">
          <TodoBody
            data={data}
            item={item}
            busy={reassign.isPending}
            onAccept={accept}
            onReassign={onReassign}
            onDivision={onDivision}
          />
        </li>
      ))}
    </ul>
  );
}

function TodoBody({
  data,
  item,
  busy,
  onAccept,
  onReassign,
  onDivision,
}: {
  data: HrStructure;
  item: TodoItem;
  busy: boolean;
  onAccept: (person: StructurePerson, managerId: number, label: string) => void;
  onReassign: (person: StructurePerson) => void;
  onDivision: (person: StructurePerson) => void;
}) {
  const { person } = item;
  const words = managerWords([person.employment_type]);
  const name = <strong className="font-semibold">{person.name}</strong>;
  switch (item.kind) {
    case "leaving": {
      const info = person.leaving!;
      return (
        <>
          <p className="text-[13px]">
            {name} kończy współpracę {formatWeekdayDayPl(info.last_working_day)}
          </p>
          <p className="text-xs text-muted-foreground">
            {peopleCount(person.reports)} w zespole —{" "}
            {info.reports_receiver_name
              ? `przejmie ${info.reports_receiver_name}`
              : "nikt ich jeszcze nie przejmuje"}
          </p>
          <Link
            href={`/people/${person.user_id}/offboarding`}
            className="text-[13px] font-medium text-primary hover:underline"
          >
            Ustaw w sprawie odejścia →
          </Link>
        </>
      );
    }
    case "manager_gone":
      return (
        <>
          <p className="text-[13px]">
            {name} — {words.one} odszedł
          </p>
          <p className="text-xs text-muted-foreground">{person.manager_name ?? "konto wyłączone"}</p>
          <Button size="sm" variant="outline" onClick={() => onReassign(person)}>
            Zmień {words.ofOne}
          </Button>
        </>
      );
    case "m365": {
      const hint = person.m365_hint!;
      return (
        <>
          <p className="text-[13px]">{name} — Microsoft 365 mówi inaczej</p>
          <p className="text-xs text-muted-foreground">
            M365: {hint.name ?? hint.upn}
            {hint.user_id ? "" : " (konto spoza NEXUSA)"} · kartoteka: {person.manager_name ?? "nikt"}
          </p>
          {hint.can_accept && hint.user_id ? (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => onAccept(person, hint.user_id!, hint.name ?? hint.upn)}
            >
              Przyjmij z M365
            </Button>
          ) : null}
        </>
      );
    }
    case "suggestion": {
      const suggestion = person.suggested_manager!;
      return (
        <>
          <p className="text-[13px]">
            {name} — bez {words.ofOne}
          </p>
          <p className="text-xs text-muted-foreground">
            podpowiedź: {suggestion.name} (head pionu)
            {person.employment_type_pending ? " · forma do uzupełnienia" : ""}
          </p>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onAccept(person, suggestion.user_id, suggestion.name)}
          >
            Przyjmij: {shortLabel(suggestion.name)}
          </Button>
        </>
      );
    }
    case "no_manager":
      return (
        <>
          <p className="text-[13px]">
            {name} — bez {words.ofOne}
          </p>
          <p className="text-xs text-muted-foreground">wnioski trafiają do Kadr</p>
          <Button size="sm" variant="outline" onClick={() => onReassign(person)}>
            Wskaż {words.ofOne}
          </Button>
        </>
      );
    case "no_division":
      return (
        <>
          <p className="text-[13px]">{name} — bez pionu</p>
          {data.divisions.length > 0 ? (
            <Button size="sm" variant="outline" onClick={() => onDivision(person)}>
              Wybierz pion
            </Button>
          ) : null}
        </>
      );
  }
}

/** „Kamil Testowy” → „Kamil T.” (przyciski w wąskim panelu). */
function shortLabel(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : name;
}
