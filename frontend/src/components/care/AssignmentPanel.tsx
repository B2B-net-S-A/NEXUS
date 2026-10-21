"use client";

import { useState } from "react";
import { UserCheck } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CADENCE_LEVELS,
  OWNER_REASON_LABELS,
  useAssignOwners,
  useCareAssignment,
  useSetLoadThreshold,
  type CareAssignment,
  type OwnerLoad,
  type OwnerReason,
} from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { formatDayMonthPl, monthYearPl } from "@/lib/date-pl";

import {
  assignmentHint,
  assignmentRows,
  cadenceLabel,
  contractForm,
  loadWidth,
  peopleText,
  talksText,
  type AssignmentFilter,
} from "./cadence-format";
import { ClientDefaultOwnersDialog } from "./ClientDefaultOwnersDialog";
import { OwnerPoolPanel } from "./OwnerPoolPanel";

const REASONS = Object.keys(OWNER_REASON_LABELS) as OwnerReason[];
/** Limit jednego zapisu (`MAX_BULK` w `care/assignment.py`) — więcej = 422 i nic się nie zapisuje. */
export const MAX_BULK_ASSIGN = 500;

function shortName(name: string): string {
  const [first, ...rest] = name.trim().split(/\s+/);
  return rest.length ? `${first} ${rest[rest.length - 1].charAt(0)}.` : first;
}

function OwnerCard({
  owner,
  scale,
  threshold,
  selected,
  onSelect,
}: {
  owner: OwnerLoad;
  scale: number;
  threshold: number | null;
  selected: boolean;
  onSelect: () => void;
}) {
  const over = threshold != null && owner.conversations > threshold;
  const width = loadWidth(Math.min(owner.conversations, threshold ?? owner.conversations), scale);
  const extra = over && threshold != null ? loadWidth(owner.conversations - threshold, scale) : 0;
  const levels = CADENCE_LEVELS.filter((level) => owner.by_level[level]);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "grid gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-left",
        selected && "border-primary bg-primary/10",
      )}
    >
      <span className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-foreground">
          {owner.name}
          {owner.is_delivery_lead ? <span className="text-muted-foreground"> (DL)</span> : null}
        </span>
        <span className="tabular-nums text-muted-foreground">
          {peopleText(owner.consultants)} · {talksText(owner.conversations)}
        </span>
      </span>
      <span className="flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className="h-full bg-primary" style={{ width: `${width}%` }} />
        {extra ? <span className="h-full bg-warning" style={{ width: `${extra}%` }} /> : null}
      </span>
      <span className="flex flex-wrap gap-x-2.5 text-xs text-muted-foreground">
        {over && threshold != null ? (
          <span className="text-warning-muted-foreground">powyżej progu {talksText(threshold)}</span>
        ) : null}
        {levels.map((level) => (
          <span key={level}>
            {owner.by_level[level]} {cadenceLabel(level)}
          </span>
        ))}
        {owner.is_delivery_lead && owner.clients.length ? (
          <span>klienci: {owner.clients.join(", ")}</span>
        ) : null}
        {!owner.consultants ? <span>bez konsultantów</span> : null}
      </span>
    </button>
  );
}

function ThresholdEditor({ data }: { data: CareAssignment }) {
  const { showToast } = useToast();
  const save = useSetLoadThreshold();
  const [value, setValue] = useState(
    data.threshold.monthly_conversations ? String(data.threshold.monthly_conversations) : "",
  );
  const submit = () => {
    const parsed = value.trim() ? Number(value) : null;
    if (parsed != null && (!Number.isInteger(parsed) || parsed < 1 || parsed > 1000)) {
      showToast("Próg to liczba rozmów w miesiącu od 1 do 1000.", "error");
      return;
    }
    save.mutate(parsed, {
      onSuccess: () => showToast(parsed ? "Próg zapisany" : "Próg wyłączony", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać progu."), "error"),
    });
  };
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <label htmlFor="care-load-threshold">Próg obciążenia (rozmów w miesiącu)</label>
      <Input
        id="care-load-threshold"
        type="number"
        min={1}
        max={1000}
        inputMode="numeric"
        className="h-7 w-20"
        value={value}
        placeholder="brak"
        onChange={(event) => setValue(event.target.value)}
      />
      <Button size="sm" variant="outline" className="h-7" disabled={save.isPending} onClick={submit}>
        Zapisz próg
      </Button>
    </div>
  );
}

/**
 * „Opieka · Przydział” (makieta M3): opiekunowie z obciążeniem liczonym
 * z rytmów (rozmowy w następnym miesiącu), próg jako ostrzeżenie, lista
 * „bez opiekuna” i zmiana wielu kontraktów naraz z powodem (head back
 * office, admin), nad nimi pula opiekunów i „Przypisz wg obłożenia”
 * (``OwnerPoolPanel``). Każda zmiana zostaje na osi konsultanta.
 */
export function AssignmentPanel({
  withPool = true,
}: {
  /** „Zespół opiekunów” pokazuje pulę zwiniętą w „Ustawieniach przydziału” — wtedy `false`. */
  withPool?: boolean;
} = {}) {
  const { showToast } = useToast();
  const query = useCareAssignment();
  const assign = useAssignOwners();
  const [filter, setFilter] = useState<AssignmentFilter>({ kind: "none" });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [ownerId, setOwnerId] = useState<string>("");
  const [reason, setReason] = useState<OwnerReason | "">("");
  const [defaultsOpen, setDefaultsOpen] = useState(false);
  const data = query.data;
  const rows = data ? assignmentRows(data.items, filter) : [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  if (state === "loading") return <p className="text-sm text-muted-foreground">Wczytywanie przydziału…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error" || !data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={state === "error" ? "Nie udało się wczytać przydziału opiekunów." : undefined}
        onRetry={() => query.refetch()}
      />
    );
  }

  const threshold = data.threshold.monthly_conversations;
  const scale = Math.max(threshold ?? 0, ...data.owners.map((owner) => owner.conversations), 1);
  const month = monthYearPl(data.month.from.slice(0, 7));
  const choose = (next: AssignmentFilter) => {
    setFilter(next);
    setPicked(new Set());
  };
  const toggle = (id: number) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const pickable = rows.slice(0, MAX_BULK_ASSIGN);
  const allPicked = pickable.length > 0 && pickable.every((row) => picked.has(row.contract_id));
  const overLimit = picked.size > MAX_BULK_ASSIGN;
  const submit = () => {
    if (!ownerId || !reason || !picked.size || overLimit) return;
    assign.mutate(
      { contract_ids: [...picked], owner_user_id: Number(ownerId), reason },
      {
        onSuccess: (result) => {
          showToast(
            result.changed
              ? `Opiekun ${result.owner.name}: ${peopleText(result.changed)}`
              : "Ci konsultanci mieli już tego opiekuna",
            "success",
          );
          setPicked(new Set());
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić opiekuna."), "error"),
      },
    );
  };
  const chips: { key: string; label: string; active: boolean; onClick: () => void }[] = [
    {
      key: "none",
      label: `Bez opiekuna (${data.counts.without_owner})`,
      active: filter.kind === "none",
      onClick: () => choose({ kind: "none" }),
    },
    ...data.owners
      .filter((owner) => owner.consultants)
      .map((owner) => ({
        key: `owner-${owner.id}`,
        label: `${shortName(owner.name)} (${owner.consultants})`,
        active: filter.kind === "owner" && filter.id === owner.id,
        onClick: () => choose({ kind: "owner", id: owner.id }),
      })),
    {
      key: "ending",
      label: `Kończący zamówienie (${data.counts.ending})`,
      active: filter.kind === "ending",
      onClick: () => choose({ kind: "ending" }),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <InlineStats
          id="care-assignment-stats"
          stats={[
            { id: "active", label: "aktywnych konsultantów", value: data.counts.active },
            { id: "none", label: "bez opiekuna", value: data.counts.without_owner },
            { id: "owners", label: "opiekunów", value: data.counts.owners },
            {
              id: "talks",
              label: `rozmów · ${month}`,
              value: data.counts.conversations,
              title: "Kamienie i rozmowy według rytmów wszystkich konsultantów na liście",
            },
          ]}
        />
        <Button size="sm" variant="outline" onClick={() => setDefaultsOpen(true)}>
          Domyślni opiekunowie klientów
        </Button>
      </div>
      {data.can_assign && withPool ? <OwnerPoolPanel /> : null}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)]">
        <section className="grid content-start gap-2" aria-label="Opiekunowie i obciążenie">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Opiekunowie i obciążenie · {month}
          </h3>
          {data.owners.length ? (
            data.owners.map((owner) => (
              <OwnerCard
                key={owner.id}
                owner={owner}
                scale={scale}
                threshold={threshold}
                selected={filter.kind === "owner" && filter.id === owner.id}
                onSelect={() => choose({ kind: "owner", id: owner.id })}
              />
            ))
          ) : (
            <p className="text-sm text-muted-foreground">Nikt nie jest jeszcze opiekunem.</p>
          )}
          {data.can_edit_threshold ? <ThresholdEditor data={data} /> : null}
          <p className="text-xs text-muted-foreground">
            Obciążenie liczone z rytmów, nie samą liczbą osób. Próg to ostrzeżenie, nie blokada
            {threshold ? ` (${talksText(threshold)} w miesiącu)` : ""}.
          </p>
        </section>
        <section className="grid content-start gap-2" aria-label="Konsultanci do przydziału">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filtr przydziału">
            {chips.map((chip) => (
              <Button
                key={chip.key}
                size="sm"
                variant={chip.active ? "primary" : "ghost"}
                aria-pressed={chip.active}
                onClick={chip.onClick}
              >
                {chip.label}
              </Button>
            ))}
          </div>
          {data.can_assign && picked.size ? (
            <div
              className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-sm"
              role="group"
              aria-label="Zmiana opiekuna zaznaczonych"
            >
              <span className="font-medium">Zaznaczone: {picked.size}</span>
              {overLimit || (allPicked && rows.length > MAX_BULK_ASSIGN) ? (
                <span className="text-muted-foreground">
                  Naraz najwyżej {MAX_BULK_ASSIGN} — resztę przypisz w kolejnym kroku.
                </span>
              ) : null}
              <Select value={ownerId} onValueChange={setOwnerId}>
                <SelectTrigger aria-label="Przypisz do" className="h-8 w-52">
                  <SelectValue placeholder="Przypisz do…" />
                </SelectTrigger>
                <SelectContent>
                  {data.owner_choices.map((owner) => (
                    <SelectItem key={owner.id} value={String(owner.id)}>
                      {owner.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={reason} onValueChange={(value) => setReason(value as OwnerReason)}>
                <SelectTrigger aria-label="Powód zmiany opiekuna" className="h-8 w-56">
                  <SelectValue placeholder="Powód…" />
                </SelectTrigger>
                <SelectContent>
                  {REASONS.map((key) => (
                    <SelectItem key={key} value={key}>
                      {OWNER_REASON_LABELS[key]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="sm" disabled={!ownerId || !reason || overLimit || assign.isPending} onClick={submit}>
                {assign.isPending ? "Zapisywanie…" : "Przypisz"}
              </Button>
            </div>
          ) : null}
          {rows.length ? (
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full text-sm" aria-label="Kontrakty do przydziału">
                <thead>
                  <tr className={CALM_ROW}>
                    {data.can_assign ? (
                      <th className="w-8 px-3 py-2">
                        <Checkbox
                          aria-label="Zaznacz wszystkich"
                          checked={allPicked}
                          onCheckedChange={(value) =>
                            setPicked(value === true ? new Set(pickable.map((row) => row.contract_id)) : new Set())
                          }
                        />
                      </th>
                    ) : null}
                    <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
                    <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
                    <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Start</th>
                    <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Rytm</th>
                    <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Podpowiedź</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const about = [row.job_title, contractForm(row.contract_type)].filter(Boolean).join(" · ");
                    return (
                      <tr key={row.contract_id} className={CALM_ROW}>
                        {data.can_assign ? (
                          <td className="px-3 py-1.5 align-top">
                            <Checkbox
                              aria-label={`Zaznacz: ${row.candidate_name ?? "konsultant"}`}
                              checked={picked.has(row.contract_id)}
                              onCheckedChange={() => toggle(row.contract_id)}
                            />
                          </td>
                        ) : null}
                        <td className="px-3 py-1.5 align-top">
                          <span className="font-medium">{row.candidate_name ?? "Konsultant"}</span>
                          {about ? <span className={CALM_SUBLINE}>{about}</span> : null}
                        </td>
                        <td className="px-3 py-1.5 align-top">{row.client_name}</td>
                        <td className="px-3 py-1.5 align-top tabular-nums">
                          {row.start_date ? formatDayMonthPl(row.start_date) : <span className={CALM_EMPTY}>—</span>}
                        </td>
                        <td className="px-3 py-1.5 align-top">
                          {row.cadence_level ? cadenceLabel(row.cadence_level) : <span className={CALM_EMPTY}>—</span>}
                          {row.ending_soon && row.end_date ? (
                            <Badge variant="warning" size="sm" className="ml-1.5">
                              koniec {formatDayMonthPl(row.end_date)}
                            </Badge>
                          ) : null}
                        </td>
                        <td className="px-3 py-1.5 align-top text-muted-foreground">{assignmentHint(row)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={UserCheck}
              title={filter.kind === "none" ? "Każdy konsultant ma opiekuna" : "Nikogo tu nie ma"}
            />
          )}
          <p className="text-xs text-muted-foreground">
            Każda zmiana opiekuna zostaje na osi konsultanta z powodem. Odejście opiekuna przekazuje jego
            konsultantów w kroku „Przekazanie pracy”.
            {data.can_assign ? "" : " Wielu konsultantów naraz przypisuje head back office albo administrator."}
          </p>
        </section>
      </div>
      {defaultsOpen ? (
        <ClientDefaultOwnersDialog data={data} open onOpenChange={setDefaultsOpen} />
      ) : null}
    </div>
  );
}
