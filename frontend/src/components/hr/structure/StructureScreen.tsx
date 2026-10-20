"use client";

import { useLayoutEffect, useMemo, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import { MoreHorizontal } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { PersonAvatar } from "@/components/hr/people/PersonAvatar";
import { TonePill } from "@/components/hr/people/people-ui";
import { peopleCount } from "@/components/hr/lifecycle/lifecycle-format";
import { contributionsBadge } from "@/components/hr/people/form-rules";
import { apiErrorMessage } from "@/lib/api-error";
import type { HrConfig } from "@/lib/api/hr";
import {
  DIVISION_LABELS,
  EMPLOYMENT_TYPE_SHORT,
  managerWords,
  useHrStructure,
  useReassignManager,
  type HrStructure,
  type StructurePerson,
} from "@/lib/api/hr-structure";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { DivisionDialog, DivisionHeadsDialog, ReassignDialog } from "./StructureDialogs";
import {
  buildStructure,
  canDropOn,
  centeredScrollLeft,
  childLayout,
  divisionKey,
  flatten,
  leavingManagers,
  todoItems,
  type DivisionGroup,
  type TodoItem,
  type TreeNode,
} from "./structure-tree";

type DialogKind = "reassign" | "division" | "heads" | null;
type View = "chart" | "list";

/** Jedna operacja na kartę (menu ⋯, panel „Do uporządkowania”) albo zaznaczenie listy. */
interface DialogState {
  kind: DialogKind;
  people: StructurePerson[];
}

/**
 * „Ludzie → Struktura” (Kadry i admin). Makieta 19.10.2026: przełącznik
 * Lista | Schemat — schemat to drzewo kart per pion; przełożonego zmienia się
 * przeciągnięciem karty albo z jej menu (ta sama trasa co lista, od razu).
 * Panel „Do uporządkowania” zbiera podpowiedzi i odejście przełożonego.
 */
export function StructureScreen({ config }: { config: HrConfig }) {
  const canManage = config.me.people_admin || config.me.is_admin;
  const query = useHrStructure(canManage);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [dialog, setDialog] = useState<DialogState>({ kind: null, people: [] });
  const [view, setView] = useState<View>("chart");

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (query.data?.people.length ?? 0) === 0,
  });
  const groups = useMemo(() => (query.data ? buildStructure(query.data) : []), [query.data]);

  if (!canManage) {
    return (
      <QueryStateNotice state="forbidden" description="Strukturę widzą Kadry i admin." />
    );
  }
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie struktury…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (state === "empty") {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Nikt nie ma jeszcze kartoteki — struktura pojawi się po założeniu kartotek.
      </div>
    );
  }

  const chosen = data.people.filter((person) => selected.has(person.user_id));
  const words = managerWords(chosen.map((person) => person.employment_type));
  const candidates = data.people.map((person) => ({ user_id: person.user_id, name: person.name }));
  const toggle = (userId: number) => {
    const next = new Set(selected);
    if (next.has(userId)) next.delete(userId);
    else next.add(userId);
    setSelected(next);
  };
  const open = (kind: Exclude<DialogKind, null>, people: StructurePerson[] = []) =>
    setDialog({ kind, people });
  const close = () => setDialog({ kind: null, people: [] });
  const divisionsCount = groups.filter((group) => group.key !== "none").length;
  const todo = todoItems(data);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div
          role="group"
          aria-label="Widok struktury"
          className="inline-flex rounded-lg border border-border bg-card p-0.5"
        >
          {(
            [
              ["list", "Lista"],
              ["chart", "Schemat"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={view === value}
              onClick={() => setView(value)}
              className={cn(
                "h-8 rounded-md px-3 text-[13px] font-medium transition-colors",
                view === value
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-[13px] text-muted-foreground">
          {peopleCount(data.total)} · {divisionsCount === 1 ? "1 pion" : `${divisionsCount} piony`}
          {view === "chart"
            ? " · przełożonego zmienisz przeciągnięciem karty albo z menu karty"
            : ""}
        </p>
        <div className="ml-auto flex flex-wrap gap-2">
          {view === "list" && chosen.length > 0 ? (
            <>
              <Button variant="ghost" onClick={() => setSelected(new Set())}>
                Wyczyść zaznaczenie
              </Button>
              <Button variant="outline" onClick={() => open("division", chosen)}>
                Ustaw pion ({chosen.length})
              </Button>
              <Button onClick={() => open("reassign", chosen)}>
                Zmień {words.ofOne} ({chosen.length})
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => open("heads")}>
              Headowie pionów
            </Button>
          )}
        </div>
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-4">
          {view === "list" ? (
            <>
              <LeavingBanners data={data} />
              {groups.map((group) => (
                <ListGroup
                  key={group.key}
                  data={data}
                  group={group}
                  selected={selected}
                  onToggle={toggle}
                />
              ))}
            </>
          ) : (
            groups.map((group) => (
              <ChartGroup
                key={group.key}
                data={data}
                group={group}
                onReassign={(person) => open("reassign", [person])}
                onDivision={(person) => open("division", [person])}
              />
            ))
          )}
        </div>
        <TodoPanel
          data={data}
          items={todo}
          onReassign={(person) => open("reassign", [person])}
          onDivision={(person) => open("division", [person])}
        />
      </div>

      {dialog.kind === "reassign" ? (
        <ReassignDialog
          people={dialog.people}
          candidates={candidates}
          open
          onOpenChange={(value) => (value ? null : close())}
          onDone={() => setSelected(new Set())}
        />
      ) : null}
      {dialog.kind === "division" ? (
        <DivisionDialog
          people={dialog.people}
          open
          onOpenChange={(value) => (value ? null : close())}
          onDone={() => setSelected(new Set())}
        />
      ) : null}
      {dialog.kind === "heads" ? (
        <DivisionHeadsDialog
          divisions={data.divisions}
          candidates={candidates}
          open
          onOpenChange={(value) => (value ? null : close())}
        />
      ) : null}
    </div>
  );
}

function ListGroup({
  data,
  group,
  selected,
  onToggle,
}: {
  data: HrStructure;
  group: DivisionGroup;
  selected: ReadonlySet<number>;
  onToggle: (userId: number) => void;
}) {
  const rows = flatten(group.roots);
  const orphanWords = managerWords(group.orphans.map((person) => person.employment_type));
  return (
    <Card className="p-0">
      <h2 className="flex flex-wrap items-baseline gap-x-2 border-b border-border px-4 py-2 text-sm font-semibold text-foreground">
        {group.label}
        <span className="text-xs font-normal text-muted-foreground">
          {group.key === "none"
            ? peopleCount(group.count)
            : `${peopleCount(group.count)} · head: ${group.head?.name ?? "nie ustawiono"}`}
        </span>
      </h2>
      <ul className="divide-y divide-border/60">
        {rows.map(({ node, depth }) => (
          <PersonRow
            key={node.person.user_id}
            data={data}
            person={node.person}
            depth={depth}
            checked={selected.has(node.person.user_id)}
            onToggle={onToggle}
            isRoot={depth === 0}
          />
        ))}
      </ul>
      {group.orphans.length > 0 ? (
        <div className="border-t border-border">
          <p className="px-4 pt-2 text-xs font-medium text-muted-foreground">
            Bez {orphanWords.ofOne} · {peopleCount(group.orphans.length)} — ich wnioski trafiają
            do Kadr
          </p>
          <ul className="divide-y divide-border/60">
            {group.orphans.map((person) => (
              <PersonRow
                key={person.user_id}
                data={data}
                person={person}
                depth={0}
                checked={selected.has(person.user_id)}
                onToggle={onToggle}
                isRoot={false}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

/** Linie drzewa (poziome i pionowe łączniki) — klasy jak w makiecie, kolor z tokenu. */
const TREE_ITEM =
  "relative flex flex-col items-center px-1.5 pt-4 " +
  "before:absolute before:right-1/2 before:top-0 before:h-4 before:w-1/2 before:border-t-[1.5px] before:border-border before:content-[''] " +
  "after:absolute after:left-1/2 after:top-0 after:h-4 after:w-1/2 after:border-l-[1.5px] after:border-t-[1.5px] after:border-border after:content-[''] " +
  "first:before:border-0 last:after:border-0 last:before:rounded-tr-md last:before:border-r-[1.5px] first:after:rounded-tl-md " +
  "only:pt-0 only:before:hidden only:after:hidden";
const TREE_CHILDREN =
  "relative m-0 flex justify-center p-0 pt-4 " +
  "before:absolute before:left-1/2 before:top-0 before:h-4 before:border-l-[1.5px] before:border-border before:content-['']";

function ChartGroup({
  data,
  group,
  onReassign,
  onDivision,
}: {
  data: HrStructure;
  group: DivisionGroup;
  onReassign: (person: StructurePerson) => void;
  onDivision: (person: StructurePerson) => void;
}) {
  const { showToast } = useToast();
  const reassign = useReassignManager();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [dragId, setDragId] = useState<number | null>(null);
  const orphanWords = managerWords(group.orphans.map((person) => person.employment_type));
  const scrollRef = useRef<HTMLDivElement>(null);
  const firstRootId = group.roots[0]?.person.user_id ?? null;
  const centered = useRef(false);

  // Szerokie drzewo otwiera się na korzeniu (raz — zapis po przeciągnięciu
  // nie przesuwa widoku pod ręką).
  useLayoutEffect(() => {
    const box = scrollRef.current;
    if (centered.current || !box || firstRootId === null) return;
    const card = box.querySelector<HTMLElement>(`[data-testid="org-card-${firstRootId}"]`);
    if (!card) return;
    centered.current = true;
    if (box.scrollWidth <= box.clientWidth) return;
    const left = card.getBoundingClientRect().left - box.getBoundingClientRect().left + box.scrollLeft;
    box.scrollLeft = centeredScrollLeft(left, card.offsetWidth, box.clientWidth, box.scrollWidth);
  }, [firstRootId]);

  const drop = async (draggedId: number, target: StructurePerson) => {
    setDragId(null);
    if (!canDropOn(data, draggedId, target.user_id)) return;
    const dragged = data.people.find((person) => person.user_id === draggedId);
    if (!dragged) return;
    const words = managerWords([dragged.employment_type]);
    const ok = await askConfirm({
      title: `Zmienić ${words.ofOne}?`,
      description: `${dragged.name}: ${words.one} — ${target.name} (było: ${dragged.manager_name ?? "nikt"}). Zmiana działa od razu; wnioski i timesheety w toku przejdą do nowej osoby.`,
      confirmLabel: "Zmień",
      cancelLabel: "Zostaw",
    });
    if (!ok) return;
    reassign.mutate(
      { user_ids: [dragged.user_id], manager_user_id: target.user_id },
      {
        onSuccess: () => showToast(`${dragged.name}: ${words.one} — ${target.name}`, "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać zmiany."), "error"),
      },
    );
  };
  const nodeProps = {
    data,
    dragId,
    onDragStart: setDragId,
    onDragEnd: () => setDragId(null),
    onDrop: drop,
    onReassign,
    onDivision,
  };

  return (
    <Card className="space-y-3 p-4" aria-label={`Schemat: ${group.label}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[15px] font-semibold text-foreground">{group.label}</h2>
          <span className="text-[13px] text-muted-foreground">{peopleCount(group.count)}</span>
        </div>
        {group.key !== "none" ? (
          <TonePill tone="neutral">head: {group.head?.name ?? "nie ustawiono"}</TonePill>
        ) : null}
      </div>
      {group.roots.length > 0 ? (
        // `w-max` + `mx-auto`: szerokie drzewo przewija się w karcie od lewej
        // krawędzi (samo `justify-center` ucinałoby lewą stronę).
        <div ref={scrollRef} className="overflow-x-auto pb-1">
          <ul className="mx-auto flex w-max p-0">
            {group.roots.map((node) => (
              <OrgBranch key={node.person.user_id} node={node} {...nodeProps} />
            ))}
          </ul>
        </div>
      ) : null}
      {group.orphans.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2.5">
          <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            Bez {orphanWords.ofOne}
          </span>
          {group.orphans.map((person) => (
            <OrgCard key={person.user_id} person={person} compact {...nodeProps} />
          ))}
          <span className="text-xs text-muted-foreground">— ich wnioski trafiają do Kadr</span>
        </div>
      ) : null}
      {confirmDialog}
    </Card>
  );
}

interface NodeHandlers {
  data: HrStructure;
  dragId: number | null;
  onDragStart: (userId: number) => void;
  onDragEnd: () => void;
  onDrop: (draggedId: number, target: StructurePerson) => void;
  onReassign: (person: StructurePerson) => void;
  onDivision: (person: StructurePerson) => void;
}

function OrgBranch({ node, ...handlers }: { node: TreeNode } & NodeHandlers) {
  const { branches, stack } = childLayout(node);
  return (
    <li className={TREE_ITEM}>
      <OrgCard person={node.person} {...handlers} />
      {node.children.length > 0 ? (
        <ul className={TREE_CHILDREN}>
          {branches.map((child) => (
            <OrgBranch key={child.person.user_id} node={child} {...handlers} />
          ))}
          {stack.length > 0 ? (
            // Podwładni bez własnych ludzi w kolumnie — jedna „gałąź” rzędu.
            <li className={TREE_ITEM}>
              <ul
                className="flex flex-col gap-1.5 p-0"
                aria-label={`Pod osobą ${node.person.name}: ${peopleCount(stack.length)}`}
              >
                {stack.map((child) => (
                  <li key={child.person.user_id}>
                    <OrgCard person={child.person} {...handlers} />
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}

function OrgCard({
  person,
  compact = false,
  data,
  dragId,
  onDragStart,
  onDragEnd,
  onDrop,
  onReassign,
  onDivision,
}: { person: StructurePerson; compact?: boolean } & NodeHandlers) {
  const [over, setOver] = useState(false);
  const droppable = dragId !== null && canDropOn(data, dragId, person.user_id);
  const words = managerWords([person.employment_type]);
  const form = person.employment_type_pending
    ? "forma do uzupełnienia"
    : person.employment_type
      ? EMPLOYMENT_TYPE_SHORT[person.employment_type]
      : null;
  const warn = Boolean(person.leaving) || Boolean(person.m365_hint) || person.manager_state === "inactive";
  const badge = contributionsBadge(person.contributions_from);
  const allowDrop = (event: DragEvent) => {
    if (!droppable) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setOver(true);
  };
  return (
    <div
      draggable
      data-testid={`org-card-${person.user_id}`}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", String(person.user_id));
        event.dataTransfer.effectAllowed = "move";
        onDragStart(person.user_id);
      }}
      onDragEnd={onDragEnd}
      onDragOver={allowDrop}
      onDragEnter={allowDrop}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const id = Number(event.dataTransfer.getData("text/plain") || dragId);
        if (Number.isInteger(id) && id > 0) onDrop(id, person);
      }}
      className={cn(
        "relative flex cursor-grab flex-col gap-1 rounded-lg border bg-card text-left shadow-sm active:cursor-grabbing",
        compact ? "flex-row items-center py-1.5 pl-2.5 pr-7" : "w-[172px] px-2.5 py-2",
        warn ? "border-warning/50 bg-warning-muted/20" : "border-border",
        dragId === person.user_id && "opacity-50",
        droppable && "border-dashed border-primary/50",
        over && "ring-2 ring-primary",
      )}
    >
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="absolute right-1 top-1 grid h-6 w-6 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label={`Więcej: ${person.name}`}
          >
            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => onReassign(person)}>
            Zmień {words.ofOne}…
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onDivision(person)}>Ustaw pion…</DropdownMenuItem>
          {person.reports > 0 ? (
            <DropdownMenuItem asChild>
              <Link href={`/people/team?manager=${person.user_id}`}>Zespół</Link>
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem asChild>
            <Link href={`/people/${person.user_id}`}>Kartoteka</Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <div className={cn("flex min-w-0 items-start gap-2", !compact && "pr-5")}>
        <PersonAvatar name={person.name} size={compact ? "xs" : "sm"} />
        <div className="min-w-0 flex-1">
          <Link
            href={`/people/${person.user_id}`}
            className="line-clamp-2 break-words text-[13px] font-semibold leading-tight text-foreground hover:underline"
            draggable={false}
          >
            {person.name}
          </Link>
          {!compact ? (
            <span className="line-clamp-2 text-[11.5px] leading-tight text-muted-foreground">
              {[person.job_title, form].filter(Boolean).join(" · ") || "—"}
            </span>
          ) : null}
        </div>
      </div>
      {!compact &&
      (person.leaving || person.m365_hint || badge || person.reports > 0 || person.manager_pending) ? (
        <div className="flex flex-wrap gap-1">
          {person.leaving ? (
            <TonePill tone="warning">
              {person.leaving.status === "draft" ? "szkic odejścia" : "odchodzi"}{" "}
              {formatWeekdayDayPl(person.leaving.last_working_day).replace(/^\S+ /, "")}
            </TonePill>
          ) : null}
          {person.m365_hint ? <TonePill tone="warning">M365: inny {words.one}</TonePill> : null}
          {person.manager_pending ? <TonePill tone="warning">{words.one} do uzupełnienia</TonePill> : null}
          {badge ? <TonePill tone="info">{badge}</TonePill> : null}
          {person.reports > 0 ? (
            <span className="text-[11px] text-muted-foreground">{peopleCount(person.reports)} pod sobą</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TodoPanel({
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
  return (
    <Card className="p-4" aria-label="Do uporządkowania">
      <div className="flex items-center justify-between pb-2">
        <h2 className="font-semibold text-foreground">Do uporządkowania</h2>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-semibold",
            items.length > 0 ? "bg-warning-muted text-warning-muted-foreground" : "bg-muted text-muted-foreground",
          )}
        >
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Wszystko poukładane.</p>
      ) : (
        <ul className="divide-y divide-border/60">
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
      )}
    </Card>
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
            {name} kończy pracę {formatWeekdayDayPl(info.last_working_day)}
          </p>
          <p className="text-xs text-muted-foreground">
            {peopleCount(person.reports)} pod sobą —{" "}
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

function LeavingBanners({ data }: { data: HrStructure }) {
  const leaving = leavingManagers(data);
  if (leaving.length === 0) return null;
  return (
    <div className="space-y-2">
      {leaving.map((person) => {
        const info = person.leaving!;
        return (
          <p
            key={person.user_id}
            className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-foreground"
          >
            {person.name} kończy pracę {formatWeekdayDayPl(info.last_working_day)}. Podwładni:{" "}
            {peopleCount(person.reports)} —{" "}
            {info.reports_receiver_name
              ? `przejmie ich ${info.reports_receiver_name}.`
              : "nikt ich jeszcze nie przejmuje."}{" "}
            <Link href={`/people/${person.user_id}/offboarding`} className="text-primary hover:underline">
              Ustaw w sprawie odejścia
            </Link>
          </p>
        );
      })}
    </div>
  );
}

/** Opis przełożonego korzenia, który jest poza grupą (inny pion, bez kartoteki, odszedł). */
function managerContext(data: HrStructure, person: StructurePerson): string | null {
  if (person.manager_user_id === null) return null;
  const words = managerWords([person.employment_type]);
  if (person.manager_state === "inactive") {
    return `${words.one} odszedł: ${person.manager_name ?? "konto wyłączone"}`;
  }
  if (person.manager_state === "no_profile") {
    return `${words.one}: ${person.manager_name ?? "—"} (bez kartoteki)`;
  }
  const manager = data.people.find((item) => item.user_id === person.manager_user_id);
  const division = manager ? divisionKey(manager) : "none";
  const where = division === "none" ? "bez pionu" : DIVISION_LABELS[division];
  return `${words.one}: ${person.manager_name ?? "—"} (${where})`;
}

function PersonRow({
  data,
  person,
  depth,
  checked,
  onToggle,
  isRoot,
}: {
  data: HrStructure;
  person: StructurePerson;
  depth: number;
  checked: boolean;
  onToggle: (userId: number) => void;
  isRoot: boolean;
}) {
  const { showToast } = useToast();
  const reassign = useReassignManager();
  const words = managerWords([person.employment_type]);
  const context = isRoot ? managerContext(data, person) : null;
  const accept = (managerId: number, label: string) =>
    reassign.mutate(
      { user_ids: [person.user_id], manager_user_id: managerId },
      {
        onSuccess: () => showToast(`${person.name}: ${words.one} — ${label}`, "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać zmiany."), "error"),
      },
    );

  return (
    <li className="flex items-start gap-3 px-4 py-2 text-sm">
      <Checkbox
        className="mt-0.5"
        checked={checked}
        onCheckedChange={() => onToggle(person.user_id)}
        aria-label={`Zaznacz: ${person.name}`}
      />
      <div className="min-w-0 flex-1" style={{ paddingLeft: `${depth * 20}px` }}>
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <Link href={`/people/${person.user_id}`} className="font-medium text-foreground hover:underline">
            {person.name}
          </Link>
          <span className="text-xs text-muted-foreground">
            {[
              person.job_title,
              person.employment_type_pending
                ? "forma do uzupełnienia"
                : person.employment_type
                  ? EMPLOYMENT_TYPE_SHORT[person.employment_type]
                  : null,
              person.student ? "student" : null,
              person.manager_pending ? "przełożony do uzupełnienia" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
            {person.reports > 0 ? ` · ${peopleCount(person.reports)} pod sobą` : ""}
          </span>
          {contributionsBadge(person.contributions_from) ? (
            <StatusDot tone="info">{contributionsBadge(person.contributions_from)}</StatusDot>
          ) : null}
          {person.reports > 0 ? (
            <Link
              href={`/people/team?manager=${person.user_id}`}
              className="text-xs text-primary hover:underline"
            >
              Zespół
            </Link>
          ) : null}
          {person.leaving ? (
            <StatusDot tone="warning">
              {person.leaving.status === "draft" ? "szkic odejścia" : "odchodzi"}{" "}
              {formatWeekdayDayPl(person.leaving.last_working_day)}
            </StatusDot>
          ) : null}
        </div>
        {context ? (
          <span className={`${CALM_SUBLINE} ${person.manager_state === "inactive" ? "text-destructive" : ""}`}>
            {context}
          </span>
        ) : null}
        {person.suggested_manager ? (
          <span className={CALM_SUBLINE}>
            Podpowiedź: {words.one} = {person.suggested_manager.name} (head pionu){" "}
            <Button
              variant="tertiary"
              size="sm"
              className="h-auto p-0 text-xs"
              disabled={reassign.isPending}
              onClick={() =>
                accept(person.suggested_manager!.user_id, person.suggested_manager!.name)
              }
            >
              Przyjmij
            </Button>
          </span>
        ) : null}
        {person.m365_hint ? (
          <span className={CALM_SUBLINE}>
            Microsoft 365: {person.m365_hint.name ?? person.m365_hint.upn}
            {person.m365_hint.user_id ? "" : " (konto spoza NEXUSA)"} · w kartotece:{" "}
            {person.manager_name ?? "nikt"}{" "}
            {person.m365_hint.can_accept && person.m365_hint.user_id ? (
              <Button
                variant="tertiary"
                size="sm"
                className="h-auto p-0 text-xs"
                disabled={reassign.isPending}
                onClick={() =>
                  accept(person.m365_hint!.user_id!, person.m365_hint!.name ?? person.m365_hint!.upn)
                }
              >
                Przyjmij
              </Button>
            ) : null}
          </span>
        ) : null}
      </div>
    </li>
  );
}
