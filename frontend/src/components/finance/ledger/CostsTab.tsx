"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  QUEUE_PAGE,
  useAccountingModule,
  useCostAction,
  useCostQueue,
  useSetAccountingModule,
  type CostCategory,
  type CostFilters,
  type CostFlag,
  type CostRow,
  type CostStage,
} from "@/lib/api/finance-ledger";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl, monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FLAG_LABELS,
  FLAG_ORDER,
  STAGE_TABS,
  bulkLabel,
  describeResult,
  keepVisible,
  recentMonths,
  stageButtons,
  toggleAll,
  type StageButton,
} from "./ledger-model";

export const COSTS_URL_KEYS = ["costStage"] as const;

const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

function readStage(): CostStage {
  if (typeof window === "undefined") return "received";
  const raw = new URLSearchParams(window.location.search).get("costStage");
  return STAGE_TABS.some((tab) => tab.stage === raw) ? (raw as CostStage) : "received";
}

function writeStage(stage: CostStage) {
  const params = new URLSearchParams(window.location.search);
  if (stage === "received") params.delete("costStage");
  else params.set("costStage", stage);
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
}

/** Plakietki flag procesowych (dawne etykiety eBI24). */
export function FlagChips({ flags }: { flags: readonly CostFlag[] }) {
  if (flags.length === 0) return <span className={CALM_EMPTY}>—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {flags.map((flag) => (
        <Badge
          key={flag}
          size="sm"
          variant={flag === "hold_payment" || flag === "duplicate" ? "danger" : "warning"}
        >
          {FLAG_LABELS[flag]}
        </Badge>
      ))}
    </span>
  );
}

/** „Kogo dotyczy” — to, co źródło już ustaliło (osoba, kontrakt, zgoda). */
export function Concerning({ row }: { row: Pick<CostRow, "concerning"> }) {
  const about = row.concerning;
  if (!about) return <span className={CALM_EMPTY}>—</span>;
  return (
    <span className="block min-w-0">
      <span className="block truncate">{about.person ?? about.label}</span>
      <span
        className={cn(CALM_SUBLINE, "truncate")}
        title={[about.person ? about.label : null, about.status_label].filter(Boolean).join(" · ")}
      >
        {about.person ? `${about.label} · ` : ""}
        {about.status_label}
      </span>
    </span>
  );
}

function ModuleBanner() {
  const accounting = useAccountingModule();
  const toggle = useSetAccountingModule();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  if (!accounting.data || accounting.data.enabled) return null;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/30 bg-warning-muted/50 px-3.5 py-2.5 text-sm text-warning-muted-foreground">
      <span className="min-w-0 flex-1">
        Moduł „Księgowość” jest wyłączony — widzisz go jako administrator. Finanse
        zobaczą zakładki po włączeniu.
      </span>
      <Button
        size="sm"
        variant="outline"
        loading={toggle.isPending}
        onClick={async () => {
          const ok = await askConfirm({
            title: "Włączyć moduł „Księgowość”?",
            description:
              "Finanse zobaczą „Koszty” i „Kontrahentów”, a pobieranie z KSeF zacznie zapisywać faktury dostawców także bez modułu „Zgody”.",
            confirmLabel: "Włącz",
          });
          if (!ok) return;
          toggle.mutate(true, {
            onSuccess: () => showToast("Moduł „Księgowość” włączony.", "success"),
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się włączyć modułu."), "error"),
          });
        }}
      >
        Włącz moduł
      </Button>
      {confirmDialog}
    </div>
  );
}

/**
 * Finanse → „Koszty”: jedna kolejka faktur kosztowych z etapami (makieta M1).
 * `canWrite = false` (podgląd jako inna osoba) — lista bez zaznaczania i akcji.
 */
export function CostsTab({ canWrite = true }: { canWrite?: boolean }) {
  const [filters, setFilters] = useState<CostFilters>(() => ({
    stage: readStage(),
    month: null,
    category: null,
    flag: null,
    q: "",
    offset: 0,
  }));
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const queue = useCostQueue(filters);
  const action = useCostAction();
  const { askReason, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const months = useMemo(() => recentMonths(warsawToday().slice(0, 7)), []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((current) => (current.q === search ? current : { ...current, q: search, offset: 0 }));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);
  const selectable = items.filter((row) => !row.own).map((row) => row.id);
  useEffect(() => {
    setSelected((current) => keepVisible(current, selectable));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko po nowej liście
  }, [queue.data]);

  const update = (patch: Partial<CostFilters>) => {
    setSelected(new Set());
    setFilters((current) => ({ ...current, offset: 0, ...patch }));
  };

  const changeStage = (stage: CostStage) => {
    writeStage(stage);
    update({ stage });
  };

  const run = async (button: StageButton | null, flag?: { flag: CostFlag; on: boolean }) => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    let reason: string | undefined;
    if (button?.needsReason) {
      const answer = await askReason({
        title: `Odrzucić ${ids.length === 1 ? "fakturę" : "zaznaczone faktury"}?`,
        description:
          "Odrzucona faktura nie idzie do księgowania. Można ją przywrócić z zakładki „Odrzucone”.",
        confirmLabel: "Odrzuć",
        variant: "destructive",
        field: { label: "Powód", placeholder: "np. faktura nie dotyczy firmy", minLength: 3, maxLength: 500 },
      });
      if (!answer) return;
      reason = answer;
    }
    action.mutate(
      flag
        ? { ids, action: flag.on ? "flag_add" : "flag_remove", flag: flag.flag }
        : { ids, action: button!.action, reason },
      {
        onSuccess: (result) => {
          const message = describeResult(result);
          showToast(message.text, message.tone);
          setSelected(new Set());
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić faktur."), "error"),
      },
    );
  };

  const counts = queue.data?.counts;
  const buttons = canWrite ? stageButtons(filters.stage) : [];
  const allOn = selectable.length > 0 && selectable.every((id) => selected.has(id));
  const someOn = selectable.some((id) => selected.has(id));
  const shown = filters.offset + items.length;

  return (
    <div className="space-y-3" data-help="finance.costs">
      {canWrite ? <ModuleBanner /> : null}
      <div
        role="tablist"
        aria-label="Etap faktur kosztowych"
        className="flex max-w-full gap-0.5 overflow-x-auto border-b border-border"
      >
        {STAGE_TABS.map((tab) => (
          <button
            key={tab.stage}
            type="button"
            role="tab"
            aria-selected={filters.stage === tab.stage}
            onClick={() => changeStage(tab.stage)}
            className={cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] transition-colors pointer-coarse:min-h-10",
              filters.stage === tab.stage
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
            {counts ? (
              <span className="tabular-nums text-muted-foreground">{counts[tab.stage]}</span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Miesiąc wpływu"
          value={filters.month ?? ""}
          onChange={(event) => update({ month: event.target.value || null })}
          className={CONTROL}
        >
          <option value="">Wszystkie miesiące</option>
          {months.map((month) => (
            <option key={month} value={month}>
              {monthTitlePl(month)}
            </option>
          ))}
        </select>
        <select
          aria-label="Rodzaj"
          value={filters.category ?? ""}
          onChange={(event) => update({ category: (event.target.value || null) as CostCategory | null })}
          className={CONTROL}
        >
          <option value="">Rodzaj: wszystkie</option>
          {CATEGORY_ORDER.map((category) => (
            <option key={category} value={category}>
              {CATEGORY_LABELS[category]}
            </option>
          ))}
        </select>
        <select
          aria-label="Flagi"
          value={filters.flag ?? ""}
          onChange={(event) =>
            update({ flag: (event.target.value || null) as CostFilters["flag"] })
          }
          className={CONTROL}
        >
          <option value="">Flagi: wszystkie</option>
          <option value="none">Bez flag</option>
          {FLAG_ORDER.map((flag) => (
            <option key={flag} value={flag}>
              {FLAG_LABELS[flag]}
            </option>
          ))}
        </select>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Sprzedawca, numer, NIP, KSeF…"
          aria-label="Szukaj faktur"
          className={cn(CONTROL, "w-56 min-w-0 flex-1 sm:flex-none")}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {canWrite && selected.size > 0 && filters.stage !== "booked" ? (
            <select
              aria-label="Flaga dla zaznaczonych"
              value=""
              disabled={action.isPending}
              onChange={(event) => {
                const [sign, flag] = event.target.value.split(":");
                if (flag) void run(null, { flag: flag as CostFlag, on: sign === "+" });
              }}
              className={CONTROL}
            >
              <option value="">Flaga dla zaznaczonych…</option>
              <optgroup label="Dodaj">
                {FLAG_ORDER.map((flag) => (
                  <option key={`+${flag}`} value={`+:${flag}`}>
                    {FLAG_LABELS[flag]}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Zdejmij">
                {FLAG_ORDER.map((flag) => (
                  <option key={`-${flag}`} value={`-:${flag}`}>
                    {FLAG_LABELS[flag]}
                  </option>
                ))}
              </optgroup>
            </select>
          ) : null}
          {buttons.map((button) => (
            <Button
              key={button.action}
              size="sm"
              variant={button.primary ? "primary" : "outline"}
              disabled={selected.size === 0 || action.isPending}
              loading={action.isPending && action.variables?.action === button.action}
              onClick={() => void run(button)}
            >
              {selected.size > 0 ? bulkLabel(button, selected.size) : button.label}
            </Button>
          ))}
        </div>
      </div>

      {queue.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktur…</p>
      ) : queue.isError ? (
        <QueryStateNotice state="error" onRetry={() => queue.refetch()} />
      ) : queue.isSuccess && items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {filters.stage === "received"
            ? "Nic nie czeka na przyjęcie z KSeF."
            : "W tej zakładce nie ma faktur dla wybranych filtrów."}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-9">
                  <Checkbox
                    aria-label="Zaznacz wszystkie widoczne"
                    checked={allOn ? true : someOn ? "indeterminate" : false}
                    disabled={!canWrite || selectable.length === 0 || filters.stage === "booked"}
                    onCheckedChange={() => setSelected(toggleAll(selected, selectable))}
                  />
                </TableHead>
                <TableHead className={`${CALM_HEAD} w-[8%]`}>Wpływ</TableHead>
                <TableHead className={`${CALM_HEAD} w-[20%]`}>Sprzedawca</TableHead>
                <TableHead className={`${CALM_HEAD} w-[15%]`}>Numer</TableHead>
                <TableHead className={`${CALM_HEAD} w-[22%]`}>Kogo dotyczy</TableHead>
                <TableHead className={`${CALM_HEAD} w-[12%] text-right`}>Netto</TableHead>
                <TableHead className={`${CALM_HEAD} w-[13%]`}>Flagi</TableHead>
                <TableHead className={`${CALM_HEAD} w-[9%]`}>Termin</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} align-top`}>
                  <TableCell>
                    <Checkbox
                      aria-label={`Zaznacz ${row.invoice_number ?? "fakturę"}`}
                      checked={selected.has(row.id)}
                      disabled={!canWrite || row.own || filters.stage === "booked"}
                      title={row.own ? "Twoja faktura — status zmienia ktoś inny z Finansów" : undefined}
                      onCheckedChange={(checked) =>
                        setSelected((current) => {
                          const next = new Set(current);
                          if (checked) next.add(row.id);
                          else next.delete(row.id);
                          return next;
                        })
                      }
                    />
                  </TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums">
                    {formatIsoDatePl(warsawToday(new Date(row.received_at)))}
                  </TableCell>
                  <TableCell className="min-w-0">
                    <span className="block truncate">{row.seller_name ?? "—"}</span>
                    <span className={cn(CALM_SUBLINE, "truncate")}>
                      {row.seller_nip ? `NIP ${row.seller_nip}` : row.category_label}
                    </span>
                  </TableCell>
                  <TableCell className="min-w-0">
                    <Link
                      href={`/finance/costs/${row.id}`}
                      className="block truncate font-medium text-primary hover:underline"
                    >
                      {row.invoice_number ?? `Faktura #${row.id}`}
                    </Link>
                    <span className={CALM_SUBLINE}>
                      {row.from_ksef ? "KSeF" : "PDF"} · {row.category_label}
                    </span>
                  </TableCell>
                  <TableCell className="min-w-0">
                    <Concerning row={row} />
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatMoney(row.net_amount, row.currency)}
                  </TableCell>
                  <TableCell>
                    <FlagChips flags={row.flags} />
                  </TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums">
                    {row.due_date ? formatIsoDatePl(row.due_date) : <span className={CALM_EMPTY}>—</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {queue.data && queue.data.total > QUEUE_PAGE ? (
            <div className="flex items-center justify-between gap-3 border-t border-border px-3.5 py-2 text-xs text-muted-foreground">
              <span>
                {filters.offset + 1}–{shown} z {queue.data.total}
              </span>
              <span className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={filters.offset === 0}
                  onClick={() => setFilters((current) => ({ ...current, offset: Math.max(0, current.offset - QUEUE_PAGE) }))}
                >
                  Poprzednie
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={shown >= queue.data.total}
                  onClick={() => setFilters((current) => ({ ...current, offset: current.offset + QUEUE_PAGE }))}
                >
                  Następne
                </Button>
              </span>
            </div>
          ) : null}
        </div>
      )}
      {confirmDialog}
    </div>
  );
}
