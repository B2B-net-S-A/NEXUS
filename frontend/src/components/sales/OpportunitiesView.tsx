"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ListFilter, Plus, Target } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  SERVICE_LINE_LABELS,
  useOpportunities,
  usePipelines,
  type Opportunity,
  type OpportunityStatus,
  type ServiceLine,
  type Stage,
  type OpportunitySort,
} from "@/lib/api/sales";
import { IT_FACTORIES_PIPELINE_KEY } from "@/lib/api/sales-factories";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { FactoriesView } from "./factories/FactoriesView";
import { daysSince, formatDealAmount, formatDealNumber } from "./format";
import { OpportunityBoard } from "./OpportunityBoard";
import { OpportunityFormDialog } from "./OpportunityFormDialog";
import { SalesSelect } from "./SalesSelect";
import { boardCounters, hasNoStep } from "./step";
import { useOwnerFilterOptions } from "./useOwnerFilterOptions";

const NEEDS_ACTION_DAYS = 30;

const STATUS_TONES: Record<OpportunityStatus, "info" | "success" | "neutral"> = {
  open: "info",
  won: "success",
  lost: "neutral",
};
const STATUS_LABELS: Record<OpportunityStatus, string> = {
  open: "Otwarta",
  won: "Wygrana",
  lost: "Przegrana",
};

type View = "board" | "list";

export interface PipelineSummary {
  open: number;
  value: number;
  weighted: number;
  won: number;
}

/** Liczby nad tablicą: otwarte szanse, wartość lejka, prognoza ważona, wygrane. */
export function summarize(items: readonly Opportunity[]): PipelineSummary {
  return items.reduce<PipelineSummary>(
    (sum, item) => {
      if (item.status === "won") return { ...sum, won: sum.won + 1 };
      if (item.status !== "open") return sum;
      return {
        open: sum.open + 1,
        value: sum.value + Number(item.value ?? 0),
        weighted: sum.weighted + Number(item.weighted_value ?? 0),
        won: sum.won,
      };
    },
    { open: 0, value: 0, weighted: 0, won: 0 },
  );
}

/** Kolumny tablicy: wszystkie etapy lejka, także przegrane (jak w Atlasie). */
export function boardStages(stages: readonly Stage[]): Stage[] {
  const closedLast = (stage: Stage) => (stage.outcome === "open" ? 0 : 1);
  return [...stages].sort((a, b) => closedLast(a) - closedLast(b) || a.position - b.position);
}

/** Dni od ostatniego dotyku; definicję dotyku trzyma backend. */
export function idleDays(item: Opportunity, now?: number): number | null {
  return daysSince(item.last_touch_at, now);
}

export function isWithoutMovement(item: Opportunity, now?: number): boolean {
  return item.status === "open" && (idleDays(item, now) ?? 0) > NEEDS_ACTION_DAYS;
}

const MODEL_OPTIONS = (Object.keys(SERVICE_LINE_LABELS) as ServiceLine[]).map((value) => ({
  value,
  label: SERVICE_LINE_LABELS[value],
}));

const SORT_OPTIONS: { value: OpportunitySort; label: string }[] = [
  { value: "updated", label: "Ostatnio zmieniane" },
  { value: "activity", label: "Ostatni kontakt" },
  { value: "value", label: "Największa wartość" },
  { value: "close", label: "Najbliższe zamknięcie" },
  { value: "created", label: "Najnowsze" },
];

export function OpportunitiesView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  // Makieta 11.11: osoba z „Sprzedaż: edycja” wchodzi od razu na swoje szanse; „Każdy opiekun” to `mine=0`.
  const mineParam = searchParams?.get("mine") ?? null;
  const ownerParamRaw = searchParams?.get("opiekun") ?? null;
  const mine = mineParam === "1" || (mineParam === null && ownerParamRaw === null && canEdit);
  // Konkretny opiekun (`?opiekun=`), sortowanie i archiwum — jak w Atlasie
  // (audyt importu 28.10.2026: 766 zarchiwizowanych szans było nie do znalezienia).
  const ownerParam = Number(searchParams?.get("opiekun") ?? "") || null;
  const sort = (searchParams?.get("sort") ?? "updated") as OpportunitySort;
  const archived = searchParams?.get("archiwum") === "1";
  const serviceLine = (searchParams?.get("model") as ServiceLine | null) ?? null;
  const createdFrom = searchParams?.get("od") ?? "";
  const createdTo = searchParams?.get("do") ?? "";
  const needsAction = searchParams?.get("bezruchu") === "1";
  const extraFilters = [
    serviceLine,
    createdFrom,
    createdTo,
    needsAction,
    archived,
    sort !== "updated",
  ].filter(Boolean).length;
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const [creating, setCreating] = useState(false);

  const pipelines = usePipelines();
  // Lejek z adresu (`?lejek=`) — szanse z innych lejków Atlasa (przetargi,
  // fabryki IT) nie mogą być widoczne tylko z karty firmy.
  const pipelineParam = Number(searchParams?.get("lejek") ?? "");
  const pipeline =
    pipelines.data?.find((p) => p.id === pipelineParam) ??
    pipelines.data?.find((p) => p.is_default) ??
    pipelines.data?.[0];
  // Fabryki IT startują od listy kont mierzonej kontaktem (decyzja Artura 10.11.2026):
  // etapy tego lejka opisują research, więc tablica nie mówi, z kim już rozmawialiśmy.
  const isFactories = pipeline?.key === IT_FACTORIES_PIPELINE_KEY;
  const defaultView: View = isFactories ? "list" : "board";
  const viewParam = searchParams?.get("view");
  const view: View = viewParam === "list" || viewParam === "board" ? viewParam : defaultView;
  const ownerOptions = useOwnerFilterOptions(pipeline && !pipeline.is_default ? pipeline.id : null).filter(
    (option) => option.value.startsWith("acct:"),
  );
  const opportunities = useOpportunities(
    {
      pipeline_id: pipeline?.id ?? null,
      owner_id: mine ? (user?.id ?? null) : ownerParam,
      q,
      sort,
      archived,
      service_line: serviceLine,
      created_from: createdFrom || null,
      created_to: createdTo || null,
    },
    Boolean(pipeline),
  );
  // „Wymaga działania” (Atlas: kolejka po 30 dniach bez ruchu) to `needsAction` wyżej.
  const noStepOnly = searchParams?.get("bez_kroku") === "1";
  const waitingOnly = searchParams?.get("czeka") === "1";
  const baseItems = useMemo(() => {
    const all = opportunities.data?.items ?? [];
    return needsAction ? all.filter((item) => isWithoutMovement(item)) : all;
  }, [opportunities.data, needsAction]);
  const counters = useMemo(() => boardCounters(baseItems), [baseItems]);
  const items = useMemo(
    () =>
      baseItems.filter(
        (item) => (!noStepOnly || hasNoStep(item)) && (!waitingOnly || (item.status === "open" && item.waiting_for_reply)),
      ),
    [baseItems, noStepOnly, waitingOnly],
  );
  const summary = useMemo(() => summarize(items), [items]);

  const writeParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(window.location.search);
    if (value) params.set(key, value);
    else params.delete(key);
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  const state = resolveViewState({
    isLoading: pipelines.isLoading || opportunities.isLoading,
    error: pipelines.error ?? opportunities.error,
    isSuccess: pipelines.isSuccess && opportunities.isSuccess,
    isEmpty: items.length === 0,
  });
  const open = (id: number) => router.push(`/sales/opportunities/${id}`);

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            writeParam("q", value.trim() || null);
          },
          placeholder: "Szansa, firma, NIP…",
          ariaLabel: "Szukaj szansy, firmy albo NIP",
        }}
        filters={
          <div className="flex flex-wrap items-center gap-2">
            {(pipelines.data?.length ?? 0) > 1 && pipeline && (
              <SalesSelect
                ariaLabel="Lejek"
                className="w-28"
                value={String(pipeline.id)}
                onValueChange={(value) => {
                  const chosen = pipelines.data?.find((p) => String(p.id) === value);
                  writeParam("lejek", chosen && !chosen.is_default ? value : null);
                }}
                options={(pipelines.data ?? []).map((p) => ({ value: String(p.id), label: p.name }))}
              />
            )}
            <SalesSelect
              ariaLabel="Opiekun"
              className="w-28"
              value={mine ? "me" : ownerParam ? `acct:${ownerParam}` : ""}
              onValueChange={(value) => {
                const params = new URLSearchParams(window.location.search);
                params.delete("mine");
                params.delete("opiekun");
                if (value === "me") params.set("mine", "1");
                else if (value.startsWith("acct:")) params.set("opiekun", value.slice(5));
                else params.set("mine", "0");
                const qs = params.toString();
                replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
              }}
              options={[{ value: "me", label: "Moje" }, ...ownerOptions]}
              anyLabel="Każdy opiekun"
            />
            <Popover>
              <PopoverTrigger asChild>
                <Button size="sm" variant={extraFilters ? "primary" : "outline"}>
                  <ListFilter className="mr-1 h-4 w-4" aria-hidden />
                  Filtry{extraFilters ? ` (${extraFilters})` : ""}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-80 space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="sales-filter-sort">Sortowanie</Label>
                  <SalesSelect
                    id="sales-filter-sort"
                    ariaLabel="Sortowanie"
                    value={sort}
                    onValueChange={(value) => writeParam("sort", value && value !== "updated" ? value : null)}
                    options={SORT_OPTIONS}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="sales-filter-model">Model</Label>
                  <SalesSelect
                    id="sales-filter-model"
                    value={serviceLine ?? ""}
                    onValueChange={(value) => writeParam("model", value || null)}
                    options={MODEL_OPTIONS}
                    anyLabel="Każdy model"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label htmlFor="sales-filter-from">Utworzona od</Label>
                    <Input
                      id="sales-filter-from"
                      type="date"
                      value={createdFrom}
                      max={createdTo || undefined}
                      onChange={(event) => writeParam("od", event.target.value || null)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="sales-filter-to">Utworzona do</Label>
                    <Input
                      id="sales-filter-to"
                      type="date"
                      value={createdTo}
                      min={createdFrom || undefined}
                      onChange={(event) => writeParam("do", event.target.value || null)}
                    />
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant={needsAction ? "primary" : "outline"}
                    aria-pressed={needsAction}
                    onClick={() => writeParam("bezruchu", needsAction ? null : "1")}
                  >
                    Bez ruchu &gt; {NEEDS_ACTION_DAYS} dni
                  </Button>
                  <Button
                    size="sm"
                    variant={archived ? "primary" : "outline"}
                    aria-pressed={archived}
                    onClick={() => writeParam("archiwum", archived ? null : "1")}
                  >
                    Archiwum
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">Wygranych w tym widoku: {summary.won}.</p>
              </PopoverContent>
            </Popover>
            <SegmentedRadio
              size="sm"
              label="Widok"
              options={[
                { value: "board", label: "Tablica" },
                { value: "list", label: "Lista" },
              ]}
              value={view}
              onChange={(value) => writeParam("view", value === defaultView ? null : value)}
            />
          </div>
        }
        resultLabel={
          opportunities.isSuccess && !archived ? (
            <span className="block whitespace-nowrap text-right text-xs leading-4 tabular-nums">
              {summary.open} otwartych · {formatDealAmount(summary.value)}
              <br />
              <span title="Wartość × prawdopodobieństwo etapu">
                prognoza {formatDealAmount(summary.weighted)}
              </span>
            </span>
          ) : undefined
        }
        actions={
          canEdit ? (
            <Button size="sm" disabled={!pipeline} onClick={() => setCreating(true)}>
              <Plus className="mr-1 h-4 w-4" aria-hidden /> Szansa
            </Button>
          ) : null
        }
        chips={[
          ...(serviceLine
            ? [{ id: "model", label: `Model: ${SERVICE_LINE_LABELS[serviceLine]}`, onRemove: () => writeParam("model", null) }]
            : []),
          ...(createdFrom
            ? [{ id: "od", label: `Utworzona od ${formatIsoDatePl(createdFrom)}`, onRemove: () => writeParam("od", null) }]
            : []),
          ...(createdTo
            ? [{ id: "do", label: `Utworzona do ${formatIsoDatePl(createdTo)}`, onRemove: () => writeParam("do", null) }]
            : []),
        ]}
      />
      {state === "ready" && (opportunities.data?.total ?? 0) > (opportunities.data?.items.length ?? 0) && (
        <p role="status" className="text-xs text-warning">
          Pokazujemy {opportunities.data?.items.length} z {opportunities.data?.total} szans — zawęź wyszukiwanie albo
          przejdź do „Moje”, żeby liczby lejka były pełne.
        </p>
      )}
      {!archived && (state === "ready" || noStepOnly || waitingOnly) && opportunities.isSuccess && (
          <p className="whitespace-nowrap text-xs text-muted-foreground">
            <button
              type="button"
              aria-pressed={noStepOnly}
              title="Otwarte szanse bez zaplanowanego zadania, telefonu ani spotkania"
              className={noStepOnly ? "font-semibold text-foreground underline" : "hover:text-foreground hover:underline"}
              onClick={() => writeParam("bez_kroku", noStepOnly ? null : "1")}
            >
              {counters.noStep} z {counters.open} bez kroku
            </button>
            {" · "}
            <button
              type="button"
              aria-pressed={waitingOnly}
              title="Ostatni kontakt to mail od klienta, a następnego kroku nie ma"
              className={waitingOnly ? "font-semibold text-primary underline" : "font-medium text-primary hover:underline"}
              onClick={() => writeParam("czeka", waitingOnly ? null : "1")}
            >
              {counters.waiting} czekają na odpowiedź
            </button>
          </p>
      )}

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie szans…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void opportunities.refetch()} />
      ) : isFactories && view === "list" ? (
        // Przed pustym stanem listy: kolejka osób nie zależy od filtrów szans.
        <FactoriesView
          items={items}
          ownerId={mine ? (user?.id ?? null) : ownerParam}
          currentUserId={user?.id ?? null}
          canEdit={canEdit}
          archived={archived}
          search={q}
        />
      ) : state === "empty" ? (
        <EmptyState
          icon={Target}
          title={q || mine || ownerParam || archived || needsAction || noStepOnly || waitingOnly || extraFilters ? "Nic nie pasuje do filtrów" : "Nie ma jeszcze szans"}
          description={
            q || mine || ownerParam || archived || noStepOnly || waitingOnly || extraFilters
              ? "Zmień wyszukiwanie albo pokaż wszystkie szanse."
              : "Dodaj pierwszą szansę — zacznij od firmy w zakładce Firmy."
          }
          action={
            canEdit && !q && !mine ? (
              <Button size="sm" onClick={() => setCreating(true)}>
                Dodaj szansę
              </Button>
            ) : undefined
          }
        />
      ) : view === "board" && pipeline ? (
        <OpportunityBoard
          pipeline={pipeline}
          stages={boardStages(pipeline.stages)}
          items={items}
          canEdit={canEdit && !archived}
          showOwner={!mine}
          refetch={opportunities.refetch}
        />
      ) : (
        <div className="relative overflow-x-auto">
          <Table className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} sticky left-0 bg-card`}>Szansa</TableHead>
                <TableHead className={CALM_HEAD}>Etap</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Wartość (zł)</TableHead>
                <TableHead className={CALM_HEAD}>Opiekun</TableHead>
                <TableHead className={CALM_HEAD}>Ostatnia aktywność</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow
                  key={item.id}
                  className={`${CALM_ROW} cursor-pointer`}
                  onClick={() => open(item.id)}
                >
                  <TableCell className="sticky left-0 bg-card">
                    <Link
                      href={`/sales/opportunities/${item.id}`}
                      className="font-medium text-foreground hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {item.title}
                    </Link>
                    <p className={CALM_SUBLINE}>
                      {item.company.name}
                      {item.service_line ? ` · ${SERVICE_LINE_LABELS[item.service_line]}` : ""}
                    </p>
                  </TableCell>
                  <TableCell>{item.stage.name}</TableCell>
                  <TableCell>
                    <StatusDot tone={STATUS_TONES[item.status]}>{STATUS_LABELS[item.status]}</StatusDot>
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatDealNumber(item.value)}
                  </TableCell>
                  <TableCell>{item.owner?.name ?? "—"}</TableCell>
                  <TableCell>
                    {formatIsoDatePl(item.last_touch_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {items.length === 0 && <p className={CALM_EMPTY}>Brak szans.</p>}
        </div>
      )}

      {creating && (
        <OpportunityFormDialog
          open={creating}
          onOpenChange={setCreating}
          pipelineId={pipeline?.id}
          onCreated={(opportunity) => open(opportunity.id)}
        />
      )}
    </div>
  );
}
