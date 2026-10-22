"use client";

import { useEffect, useState } from "react";
import { Users, X } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  OWNER_REASON_LABELS,
  useAssignOwners,
  useCareConsultants,
  useCareOwners,
  type ConsultantRow,
  type OwnerReason,
} from "@/lib/api/care";
import { useCreateAnnouncement } from "@/lib/api/care-announcements";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { todayInBusinessTz } from "@/lib/candidate-followup";
import { daysUntil } from "@/lib/client-order-list";
import { formatDayMonthPl } from "@/lib/date-pl";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { MAX_BULK_ASSIGN } from "./team/team-format";
import {
  CADENCE_BADGE,
  cadenceLabel,
  cadenceSubline,
  consultantsIn,
  contractForm,
  monthTalks,
  peopleText,
  rowSignals,
  signalText,
  sinceText,
} from "./cadence-format";
import { CadenceDialog } from "./CadenceDialog";
import { HEALTH_BADGE, healthLabel, healthWhy, needsAttention } from "./health-format";

export type ConsultantsFilter = "all" | "biweekly" | "paused" | "attention" | "redeploy" | "ending";

/** Jak „Kończą w 60 dni” na liście „Klienci” (`portfolio.ENDING_DAYS`). */
const ENDING_DAYS = 60;

const FILTERS: { value: ConsultantsFilter; label: string }[] = [
  { value: "all", label: "Wszystkie rytmy" },
  { value: "biweekly", label: "Rytm: co 2 tygodnie" },
  { value: "paused", label: "Wstrzymani" },
  { value: "attention", label: "Z sygnałem" },
  { value: "redeploy", label: "Do przepięcia" },
  { value: "ending", label: `Kończą w ${ENDING_DAYS} dni` },
];

const REASONS = Object.keys(OWNER_REASON_LABELS) as OwnerReason[];

/**
 * „Z sygnałem” = zdrowie „Uwaga” albo „Ryzyko”; czytający spoza kręgu D11
 * (bez etykiety zdrowia) — dawne sygnały rytmu.
 */
export function matchesConsultantsFilter(
  row: ConsultantRow,
  filter: ConsultantsFilter,
  today: string = todayInBusinessTz(),
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "biweekly":
      return row.cadence.level === "biweekly";
    case "paused":
      return row.cadence.level === "paused";
    case "attention":
      return row.health != null ? needsAttention(row.health) : row.signals.length > 0;
    case "redeploy":
      return Boolean(row.redeploy_active);
    case "ending": {
      const left = daysUntil(row.end_date, today);
      return left != null && left >= 0 && left < ENDING_DAYS;
    }
  }
}

/** Filtr opiekuna z adresu (`?owner=<id>` albo `?owner=none`) — link z „Zespołu opiekunów”. */
export type OwnerFilter = number | "none" | null;

export function ownerFilterFrom(value: string | null | undefined): OwnerFilter {
  if (value === "none") return "none";
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function matchesOwner(row: ConsultantRow, owner: OwnerFilter): boolean {
  if (owner === null) return true;
  if (owner === "none") return !row.owner;
  return row.owner?.id === owner;
}

/** Treść startowa komunikatu — jak w edytorze (pola `{imię}` i `{opiekun}`). */
const ANNOUNCEMENT_BODY =
  "Cześć {imię},\n\n\n\nW razie pytań odpisz na tę wiadomość albo napisz do swojej opiekunki lub opiekuna: {opiekun}.";

function NextTalk({ row }: { row: ConsultantRow }) {
  const next = row.next_contact;
  if (next?.overdue) {
    return (
      <Badge variant="danger" size="md">
        zaległa {next.overdue_days === 1 ? "1 dzień" : `${next.overdue_days} dni`}
      </Badge>
    );
  }
  if (next) {
    return (
      <>
        <span className="tabular-nums">{formatDayMonthPl(next.due_on)}</span>
        {next.kind === "pre_end" ? <span className={CALM_SUBLINE}>30 dni przed końcem</span> : null}
        {next.kind === "follow_up" ? <span className={CALM_SUBLINE}>umówiony kontakt</span> : null}
      </>
    );
  }
  if (row.cadence.level === "paused" && row.cadence.until_on) {
    return <span className="text-muted-foreground">po {formatDayMonthPl(row.cadence.until_on)}</span>;
  }
  return <span className={CALM_EMPTY}>—</span>;
}

function LastTalk({ row }: { row: ConsultantRow }) {
  const last = row.last_conversation;
  if (!last) return <span className={CALM_EMPTY}>bez rozmów</span>;
  const text = [
    formatDayMonthPl(last.occurred_on),
    last.satisfaction ? `${last.satisfaction}/5` : null,
    last.note_excerpt ? `„${last.note_excerpt}”` : "bez uwag",
  ]
    .filter(Boolean)
    .join(" · ");
  return <span className="line-clamp-2 text-muted-foreground">{text}</span>;
}

/** „Zdrowie” — etykieta z „dlaczego”; bez etykiety (spoza D11) zostają sygnały rytmu. */
function HealthCell({ row }: { row: ConsultantRow }) {
  if (row.health) {
    const why = healthWhy(row.health);
    return (
      <>
        <Badge variant={HEALTH_BADGE[row.health.level]} size="md">
          {healthLabel(row.health)}
        </Badge>
        {why ? <span className={cn(CALM_SUBLINE, "line-clamp-2")}>{why}</span> : null}
        {row.redeploy_active ? <span className={CALM_SUBLINE}>do przepięcia</span> : null}
      </>
    );
  }
  const signals = rowSignals(row);
  if (!signals.length) return <span className={CALM_EMPTY}>—</span>;
  return <span className="text-xs text-muted-foreground">{signals.map(signalText).join(" · ")}</span>;
}

interface ConsultantsPanelProps {
  scope: "mine" | "all";
  onScopeChange: (scope: "mine" | "all") => void;
  /** Otwiera kartę konsultanta (`?contract=`). */
  onOpenContract: (contractId: number) => void;
  /** Otwiera szkic komunikatu (`?tab=announcements&announcement=<id>`). */
  onOpenAnnouncement: (id: number) => void;
  /** Autor komunikatów (opiekun, DL, head back office, admin). */
  canAnnounce: boolean;
  /** Hurtowa zmiana opiekuna — head back office i admin. */
  canAssign: boolean;
  /** Filtr startowy (dawne `?tab=redeploy` → „Do przepięcia”). */
  initialFilter?: ConsultantsFilter;
  selectedId?: number | null;
}

/**
 * „Opieka · Konsultanci”: rytm i zdrowie relacji przy każdej osobie, filtry
 * stanu, zaznaczanie wierszy — „Napisz komunikat do zaznaczonych” (szkic
 * z grupą „wybrane osoby”) i zmiana opiekuna hurtem dla head back office
 * i admina. Klik w osobę otwiera kartę konsultanta. Awaria ≠ pusta lista.
 */
export function ConsultantsPanel({
  scope,
  onScopeChange,
  onOpenContract,
  onOpenAnnouncement,
  canAnnounce,
  canAssign,
  initialFilter = "all",
  selectedId = null,
}: ConsultantsPanelProps) {
  const { showToast } = useToast();
  const query = useCareConsultants();
  const [filter, setFilter] = useState<ConsultantsFilter>(initialFilter);
  const [cadenceFor, setCadenceFor] = useState<number | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [ownerId, setOwnerId] = useState("");
  const [reason, setReason] = useState<OwnerReason | "">("");
  const owners = useCareOwners(canAssign && picked.size > 0);
  const assign = useAssignOwners();
  const createAnnouncement = useCreateAnnouncement();
  const { replaceUrl } = useUrlWriter();
  // `?owner=` czytany po zamontowaniu (link „Konsultanci” z „Zespołu
  // opiekunów”); opiekun to zawsze cały zakres, nie „Moi”.
  const [ownerFilter, setOwnerFilter] = useState<OwnerFilter>(null);
  useEffect(() => {
    const owner = ownerFilterFrom(new URLSearchParams(window.location.search).get("owner"));
    if (owner === null) return;
    setOwnerFilter(owner);
    onScopeChange("all");
    // Tylko przy wejściu — dalej filtr zmienia się chipem.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const clearOwner = () => {
    setOwnerFilter(null);
    setPicked(new Set());
    const params = new URLSearchParams(window.location.search);
    params.delete("owner");
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  const items = query.data?.items ?? [];
  const inScope = consultantsIn(items, scope).filter((row) => matchesOwner(row, ownerFilter));
  const ownerName =
    ownerFilter === "none"
      ? "bez opiekuna"
      : ownerFilter !== null
        ? (items.find((row) => row.owner?.id === ownerFilter)?.owner?.name ?? "wybrany opiekun")
        : null;
  const rows = inScope.filter((row) => matchesConsultantsFilter(row, filter));
  const counts = Object.fromEntries(
    FILTERS.map(({ value }) => [value, inScope.filter((row) => matchesConsultantsFilter(row, value)).length]),
  ) as Record<ConsultantsFilter, number>;
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  const today = query.data?.today ?? "";
  const selectable = canAnnounce || canAssign;
  const pickedRows = rows.filter((row) => picked.has(row.contract_id));
  const allPicked = rows.length > 0 && rows.every((row) => picked.has(row.contract_id));

  const choose = (next: ConsultantsFilter) => {
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

  const announce = () => {
    const candidateIds = [...new Set(pickedRows.map((row) => row.candidate_id).filter((id): id is number => id != null))];
    if (!candidateIds.length) {
      showToast("Zaznaczone osoby nie mają profilu kandydata — komunikatu nie da się zaadresować.", "error");
      return;
    }
    createAnnouncement.mutate(
      {
        kind: "informational",
        subject: "Komunikat do wybranych osób",
        body: ANNOUNCEMENT_BODY,
        audience: { group: "selected", candidate_ids: candidateIds },
      },
      {
        onSuccess: (created) => {
          setPicked(new Set());
          onOpenAnnouncement(created.id);
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się założyć szkicu komunikatu."), "error"),
      },
    );
  };

  const reassign = () => {
    if (!ownerId || !reason || !pickedRows.length) return;
    assign.mutate(
      { contract_ids: pickedRows.map((row) => row.contract_id), owner_user_id: Number(ownerId), reason },
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

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Filtr konsultantów" className="flex flex-wrap gap-1">
          {ownerName ? (
            <button
              type="button"
              onClick={clearOwner}
              aria-label={`Usuń filtr opiekuna: ${ownerName}`}
              className="inline-flex items-center gap-1 rounded-full border border-primary bg-primary/10 px-3 py-1 text-xs text-foreground"
            >
              Opiekun: {ownerName}
              <X className="size-3" aria-hidden />
            </button>
          ) : null}
          {FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={filter === item.value}
              onClick={() => choose(item.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                filter === item.value
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {item.label}
              {query.isSuccess && item.value !== "all" ? (
                <>
                  {" "}
                  <span className="tabular-nums">{counts[item.value]}</span>
                </>
              ) : null}
            </button>
          ))}
        </div>
        {query.isSuccess ? (
          <span className="text-xs text-muted-foreground" title="Kamienie i rozmowy według rytmu osób na liście">
            Rozmów w tym miesiącu według rytmów:{" "}
            <span className="font-semibold tabular-nums">{monthTalks(rows)}</span>
          </span>
        ) : null}
      </div>

      {picked.size ? (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-sm"
          role="group"
          aria-label="Akcje dla zaznaczonych"
        >
          <span className="font-medium">Zaznaczone: {picked.size}</span>
          {canAnnounce ? (
            <Button size="sm" variant="outline" loading={createAnnouncement.isPending} onClick={announce}>
              Napisz komunikat do zaznaczonych
            </Button>
          ) : null}
          {canAssign ? (
            <>
              <Select value={ownerId} onValueChange={setOwnerId}>
                <SelectTrigger aria-label="Nowy opiekun zaznaczonych" className="h-8 w-52">
                  <SelectValue placeholder="Zmień opiekuna na…" />
                </SelectTrigger>
                <SelectContent>
                  {(owners.data ?? []).map((owner) => (
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
              <Button
                size="sm"
                disabled={!ownerId || !reason || pickedRows.length > MAX_BULK_ASSIGN}
                loading={assign.isPending}
                onClick={reassign}
              >
                Przypisz
              </Button>
            </>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>
            Odznacz
          </Button>
        </div>
      ) : null}

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie konsultantów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "error" ? "Nie udało się wczytać listy konsultantów." : undefined}
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <EmptyState
          icon={Users}
          title={
            filter !== "all"
              ? "Nikt nie pasuje do tego filtra"
              : scope === "mine"
                ? "Nie opiekujesz się żadnym konsultantem"
                : "Brak trwających kontraktów"
          }
          description={
            scope === "mine" && filter === "all"
              ? "Opiekuna ustawia się w karcie konsultanta („Więcej” → „Zmień opiekuna”), domyślnie dla klienta albo w „Zespole opiekunów”."
              : undefined
          }
          action={
            // Admin bez podopiecznych widział tu pustkę, a „Mój zakres” miał 501 osób (19.10.2026).
            scope === "mine" && filter === "all" ? (
              <Button size="sm" variant="outline" onClick={() => onScopeChange("all")}>
                Pokaż wszystkich w moim zakresie
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm" aria-label="Konsultanci i rytm kontaktu">
            <thead>
              <tr className={CALM_ROW}>
                {selectable ? (
                  <th className="w-8 px-3 py-2">
                    <Checkbox
                      aria-label="Zaznacz wszystkich na liście"
                      checked={allPicked}
                      onCheckedChange={(value) =>
                        setPicked(value === true ? new Set(rows.map((row) => row.contract_id)) : new Set())
                      }
                    />
                  </th>
                ) : null}
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient · menedżer u klienta</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Zdrowie</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Rytm</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Następna rozmowa</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Ostatnio</th>
                {scope === "all" ? <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const subline = cadenceSubline(row.cadence);
                const about = [row.job_title, contractForm(row.contract_type), sinceText(row.start_date, today)]
                  .filter(Boolean)
                  .join(" · ");
                const name = row.candidate_name ?? "konsultant";
                return (
                  <tr
                    key={row.contract_id}
                    className={cn(CALM_ROW, selectedId === row.contract_id && "bg-muted/60")}
                  >
                    {selectable ? (
                      <td className="px-3 py-1.5 align-top">
                        <Checkbox
                          aria-label={`Zaznacz: ${name}`}
                          checked={picked.has(row.contract_id)}
                          onCheckedChange={() => toggle(row.contract_id)}
                        />
                      </td>
                    ) : null}
                    <td className="px-3 py-1.5 align-top">
                      <button
                        type="button"
                        className="text-left font-medium hover:underline"
                        aria-label={`Karta konsultanta: ${name}`}
                        onClick={() => onOpenContract(row.contract_id)}
                      >
                        {row.candidate_name ?? "Konsultant"}
                      </button>
                      {about ? <span className={CALM_SUBLINE}>{about}</span> : null}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      {row.client_name}
                      <span className={CALM_SUBLINE}>{row.manager?.name ?? "menedżer: nie wskazano"}</span>
                    </td>
                    <td className="max-w-56 px-3 py-1.5 align-top">
                      <HealthCell row={row} />
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <span className="flex items-center gap-1.5">
                        <Badge variant={CADENCE_BADGE[row.cadence.level]} size="md">
                          {cadenceLabel(row.cadence.level)}
                        </Badge>
                        {row.can_change_cadence ? (
                          <Button
                            size="sm"
                            variant="quiet"
                            className="h-6 px-1.5 text-xs"
                            aria-label={`Zmień rytm: ${name}`}
                            onClick={() => setCadenceFor(row.contract_id)}
                          >
                            Zmień
                          </Button>
                        ) : null}
                      </span>
                      {subline ? <span className={cn(CALM_SUBLINE, "max-w-44")}>{subline}</span> : null}
                      {row.suggested_level ? (
                        <span className={CALM_SUBLINE}>podnieść rytm?</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <NextTalk row={row} />
                    </td>
                    <td className="max-w-52 px-3 py-1.5 align-top">
                      <LastTalk row={row} />
                    </td>
                    {scope === "all" ? (
                      <td className="px-3 py-1.5 align-top">
                        {row.owner?.name ?? <span className={CALM_EMPTY}>—</span>}
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {query.isSuccess && !query.data.feedback_visible ? (
        <p className="text-xs text-muted-foreground">
          Zdrowie relacji i opinie menedżerów widzą opiekun, Delivery Lead klienta, Head of Recruitment i administrator.
        </p>
      ) : null}
      {cadenceFor != null ? (
        <CadenceDialog
          contractId={cadenceFor}
          open
          onOpenChange={(open) => {
            if (!open) setCadenceFor(null);
          }}
        />
      ) : null}
    </div>
  );
}
