"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { formatDayShort, peopleCount } from "@/components/hr/lifecycle/lifecycle-format";
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
import { resolveViewState } from "@/lib/view-state";

import { DivisionDialog, DivisionHeadsDialog, ReassignDialog } from "./StructureDialogs";
import { buildStructure, divisionKey, flatten, leavingManagers } from "./structure-tree";

type DialogKind = "reassign" | "division" | "heads" | null;

/** „Ludzie → Struktura” (Kadry i admin): drzewo po pionie i przełożonym. */
export function StructureScreen({ config }: { config: HrConfig }) {
  const canManage = config.me.people_admin || config.me.is_admin;
  const query = useHrStructure(canManage);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [dialog, setDialog] = useState<DialogKind>(null);

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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <InlineStats
          stats={[
            { id: "people", label: "osób", value: data.total },
            { id: "orphans", label: "bez przełożonego", value: data.without_manager },
            { id: "gone", label: "przełożony odszedł", value: data.inactive_manager },
            { id: "m365", label: "rozjazd z Microsoft 365", value: data.m365_mismatches },
          ]}
        />
        <div className="ml-auto flex flex-wrap gap-2">
          {chosen.length > 0 ? (
            <>
              <Button variant="ghost" onClick={() => setSelected(new Set())}>
                Wyczyść zaznaczenie
              </Button>
              <Button variant="outline" onClick={() => setDialog("division")}>
                Ustaw pion ({chosen.length})
              </Button>
              <Button onClick={() => setDialog("reassign")}>
                Zmień {words.ofOne} ({chosen.length})
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => setDialog("heads")}>
              Headowie pionów
            </Button>
          )}
        </div>
      </div>

      <LeavingBanners data={data} />

      {groups.map((group) => {
        const rows = flatten(group.roots);
        const orphanWords = managerWords(group.orphans.map((person) => person.employment_type));
        return (
          <Card key={group.key} className="p-0">
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
                  onToggle={toggle}
                  isRoot={depth === 0}
                />
              ))}
            </ul>
            {group.orphans.length > 0 ? (
              <div className="border-t border-border">
                <p className="px-4 pt-2 text-xs font-medium text-muted-foreground">
                  Bez {orphanWords.ofOne} · {peopleCount(group.orphans.length)} — ich wnioski
                  trafiają do Kadr
                </p>
                <ul className="divide-y divide-border/60">
                  {group.orphans.map((person) => (
                    <PersonRow
                      key={person.user_id}
                      data={data}
                      person={person}
                      depth={0}
                      checked={selected.has(person.user_id)}
                      onToggle={toggle}
                      isRoot={false}
                    />
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>
        );
      })}

      {dialog === "reassign" ? (
        <ReassignDialog
          people={chosen}
          candidates={candidates}
          open
          onOpenChange={(open) => setDialog(open ? "reassign" : null)}
          onDone={() => setSelected(new Set())}
        />
      ) : null}
      {dialog === "division" ? (
        <DivisionDialog
          people={chosen}
          open
          onOpenChange={(open) => setDialog(open ? "division" : null)}
          onDone={() => setSelected(new Set())}
        />
      ) : null}
      {dialog === "heads" ? (
        <DivisionHeadsDialog
          divisions={data.divisions}
          candidates={candidates}
          open
          onOpenChange={(open) => setDialog(open ? "heads" : null)}
        />
      ) : null}
    </div>
  );
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
            {person.name} kończy pracę {formatDayShort(info.last_working_day)}. Podwładni:{" "}
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
            {[person.job_title, EMPLOYMENT_TYPE_SHORT[person.employment_type]]
              .filter(Boolean)
              .join(" · ")}
            {person.reports > 0 ? ` · ${peopleCount(person.reports)} pod sobą` : ""}
          </span>
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
              {formatDayShort(person.leaving.last_working_day)}
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
