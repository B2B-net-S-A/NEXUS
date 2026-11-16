"use client";

import Link from "next/link";
import { useCallback, useDeferredValue, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { InlineStats, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useAutoSettle,
  usePostValuation,
  useSettle,
  useSettlementAccount,
  useSettlements,
  useUnsettle,
  useValuation,
  type AccountFxDocument,
  type SettlementAccount,
  type SettlementAccountRow,
  type SettlementItem,
  type SettlementSide,
  type SettlementsOverview,
} from "@/lib/api/accounting-settlements";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { curAmount, rateLabel } from "./bank-model";
import { datePl, gr, short } from "./ledger-model";
import {
  agingRows,
  amountCents,
  amountProblem,
  autoLabel,
  autoMessage,
  autoTotal,
  daysLabel,
  docLabel,
  isForeign,
  pairsLabel,
  periodAsOf,
  positionsLabel,
  readAccount,
  readAsOf,
  selection,
  settleBlocker,
  settleMessage,
  valuationMessage,
} from "./settlements-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const SIDES = [
  { value: "all", label: "Wszystkie" },
  { value: "receivable", label: "Należności" },
  { value: "payable", label: "Zobowiązania" },
] as const;

function writeParams(values: Record<string, string | null>) {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(values)) {
    if (value == null) params.delete(key);
    else params.set(key, value);
  }
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

function Amount({ value }: { value: number }) {
  return value ? <>{gr(value)}</> : <span className={CALM_EMPTY}>—</span>;
}

/**
 * Zakładka „Rozrachunki” (K4b): otwarte pozycje kontrahentów na dzień,
 * wiekowanie i rozliczanie pozycji. Automat łączy zapłatę z wyciągu z fakturą
 * dopasowaną w E3/E8, korektę z fakturą pierwotną i pozycje, które razem dają
 * zero; resztę rozlicza się ręcznie na karcie konta.
 */
export function SettlementsView() {
  const { config, period } = useAccounting();
  const open = config.modules.find((module) => module.key === "bank")?.open ?? false;
  // „Na dzień” = koniec miesiąca z nagłówka, a w bieżącym miesiącu „dziś” z serwera
  // (kalendarz firmy). Data wpisana w polu albo z adresu wygrywa do zmiany miesiąca.
  const [picked, setPicked] = useState<string | null>(null);
  const asOf = picked ?? periodAsOf(period.year, period.month, config.today);
  const [side, setSide] = useState<SettlementSide>("all");
  const [overdue, setOverdue] = useState(false);
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const [account, setAccount] = useState<string | null>(null);
  useEffect(() => {
    setAccount(readAccount(window.location.search));
    setPicked(readAsOf(window.location.search));
  }, []);
  // Porównanie z poprzednim miesiącem, nie flaga „pierwszy raz” — efekt w trybie
  // ścisłym Reacta biegnie dwa razy i flaga skasowałaby datę z adresu.
  const shownPeriod = useRef(`${period.year}-${period.month}`);
  useEffect(() => {
    const key = `${period.year}-${period.month}`;
    if (shownPeriod.current === key) return;
    shownPeriod.current = key;
    setPicked(null);
    writeParams({ as_of: null });
  }, [period.year, period.month]);
  const select = useCallback((value: string | null) => {
    setAccount(value);
    writeParams({ account: value });
  }, []);
  const changeDay = (value: string) => {
    if (!value) return;
    setPicked(value);
    writeParams({ as_of: value });
  };
  const overview = useSettlements({ asOf, side, overdue, q }, open);

  if (!open) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Rozrachunki są częścią modułu „Bank” — włącza go administrator w Ustawieniach.
      </p>
    );
  }
  return (
    <div className="space-y-3.5">
      <div className="flex flex-wrap items-center gap-2.5 text-[13px]">
        <label className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Na dzień</span>
          <input type="date" className={CONTROL} value={asOf} onChange={(event) => changeDay(event.target.value)} />
        </label>
        <SegmentedRadio label="Strona rozrachunków" size="sm" value={side} onChange={setSide} options={SIDES} />
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={overdue} onChange={(event) => setOverdue(event.target.checked)} />
          Tylko po terminie
        </label>
        <input
          type="search"
          className={cn(CONTROL, "w-56")}
          placeholder="Kontrahent, konto albo NIP"
          aria-label="Szukaj kontrahenta"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      {overview.isError ? (
        <QueryStateNotice state="error" onRetry={() => overview.refetch()} />
      ) : !overview.isSuccess ? (
        <p className="text-sm text-muted-foreground">Wczytywanie rozrachunków…</p>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <InlineStats
              stats={[
                { id: "receivable", label: "Należności otwarte", value: `${short(overview.data.totals.receivable.open)} zł` },
                { id: "receivable-late", label: "w tym po terminie", value: `${short(overview.data.totals.receivable.overdue)} zł` },
                { id: "payable", label: "Zobowiązania otwarte", value: `${short(overview.data.totals.payable.open)} zł` },
                { id: "payable-late", label: "w tym po terminie", value: `${short(overview.data.totals.payable.overdue)} zł` },
              ]}
            />
            <AutoButton overview={overview.data} />
          </div>
          {account ? <AccountCard key={`${account}:${asOf}`} account={account} asOf={asOf} onClose={() => select(null)} /> : null}
          <div className="grid gap-3.5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <AccountsCard overview={overview.data} selected={account} onSelect={select} />
            <AgingCard overview={overview.data} />
          </div>
          <ValuationCard year={period.year} month={period.month} />
        </>
      )}
    </div>
  );
}

function AutoButton({ overview }: { overview: SettlementsOverview }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const auto = useAutoSettle();
  const total = autoTotal(overview.auto);
  const run = async () => {
    const ok = await askConfirm({
      title: `Rozliczyć automatycznie ${positionsLabel(total)}?`,
      description: `${autoLabel(overview.auto)}. Każde rozliczenie można cofnąć na karcie konta.`,
      confirmLabel: "Rozlicz",
    });
    if (!ok) return;
    auto.mutate(undefined, {
      onSuccess: (result) => showToast(autoMessage(result)),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się rozliczyć automatycznie."), "error"),
    });
  };
  if (!overview.can_settle) return null;
  return (
    <div className="flex items-center gap-2">
      <span className="text-[12px] text-muted-foreground">
        {total ? `Automat: ${autoLabel(overview.auto)}` : "Automat nie ma nic do rozliczenia"}
        {overview.auto.fx_waiting ? (
          <span className="block text-warning-muted-foreground">
            W walucie czeka {pairsLabel(overview.auto.fx_waiting)} — konto różnic kursowych w Ustawieniach (Bank)
            albo otwarty okres.
          </span>
        ) : null}
      </span>
      <Button size="sm" disabled={!total} loading={auto.isPending} onClick={() => void run()}>
        Rozlicz automatycznie
      </Button>
      {confirmDialog}
    </div>
  );
}

function AccountsCard({
  overview,
  selected,
  onSelect,
}: {
  overview: SettlementsOverview;
  selected: string | null;
  onSelect: (account: string) => void;
}) {
  const rows = overview.accounts;
  return (
    <SectionCard title="Kontrahenci" aside={`na dzień ${datePl(overview.as_of)} · kwoty w zł`}>
      {!overview.accounts_configured ? (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">
          Plan kont nie ma konta ze słownikiem „kontrahent” — rozrachunki są na jego analityce (np. 200-NNN).{" "}
          <Link className="text-primary hover:underline" href="/accounting/chart">
            Plan kont
          </Link>
        </p>
      ) : rows.length ? (
        <>
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Kontrahent</th>
                <th className={cn(CALM_HEAD, "w-[17%] px-2 py-2 text-right")}>Należności (Wn)</th>
                <th className={cn(CALM_HEAD, "w-[17%] px-2 py-2 text-right")}>Zobowiązania (Ma)</th>
                <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-right")}>Po terminie</th>
                <th
                  className={cn(CALM_HEAD, "w-[9%] py-2 pl-2 pr-3.5 text-right")}
                  title="Dni po terminie najstarszej zaległej pozycji"
                >
                  Dni
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <AccountRow key={row.account} row={row} active={selected === row.account} onSelect={onSelect} />
              ))}
            </tbody>
          </table>
          {overview.truncated ? (
            <p className="border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
              Pokazuję {rows.length} z {overview.accounts_total} kontrahentów — zawęź wyszukiwanie.
            </p>
          ) : null}
        </>
      ) : (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">Brak otwartych pozycji na ten dzień.</p>
      )}
    </SectionCard>
  );
}

function AccountRow({
  row,
  active,
  onSelect,
}: {
  row: SettlementAccountRow;
  active: boolean;
  onSelect: (account: string) => void;
}) {
  const late = row.debit_overdue + row.credit_overdue;
  return (
    <tr
      className={cn(CALM_ROW, "cursor-pointer align-top last:border-0 hover:bg-muted/40", active && "bg-muted/60")}
      onClick={() => onSelect(row.account)}
    >
      <td className="min-w-0 px-3.5 py-2">
        <button
          type="button"
          className="block max-w-full truncate text-left font-medium hover:underline"
          aria-current={active ? "true" : undefined}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(row.account);
          }}
        >
          {row.name || row.account}
        </button>
        <span className={cn(CALM_SUBLINE, "truncate")}>
          {row.name ? row.account : "konto bez kontrahenta w kartotece"}
          {row.nip ? ` · NIP ${row.nip}` : ""} · {positionsLabel(row.open_items)}
        </span>
      </td>
      <td className={cn(CALM_AMOUNT, "px-2 py-2 text-right")}>
        <Amount value={row.debit_open} />
      </td>
      <td className={cn(CALM_AMOUNT, "px-2 py-2 text-right")}>
        <Amount value={row.credit_open} />
      </td>
      <td className={cn(CALM_AMOUNT, "px-2 py-2 text-right", late && "text-warning-muted-foreground")}>
        <Amount value={late} />
      </td>
      <td className="whitespace-nowrap py-2 pl-2 pr-3.5 text-right text-[13px] tabular-nums">
        {row.max_overdue_days ? (
          <span className="text-warning-muted-foreground" title={`termin ${datePl(row.oldest_due)}`}>
            {daysLabel(row.max_overdue_days)}
          </span>
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </td>
    </tr>
  );
}

function AgingCard({ overview }: { overview: SettlementsOverview }) {
  const rows = agingRows(overview.aging);
  return (
    <SectionCard title="Wiekowanie" aside="dni po terminie">
      <table className="w-full table-fixed text-[13px]">
        <thead>
          <tr className="border-b border-border/70">
            <th className={cn(CALM_HEAD, "px-3 py-1.5 text-left")}>Przedział</th>
            <th className={cn(CALM_HEAD, "w-[34%] px-2 py-1.5 text-right")}>Należności</th>
            <th className={cn(CALM_HEAD, "w-[34%] py-1.5 pl-2 pr-3 text-right")}>Zobowiązania</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className={cn(CALM_ROW, "last:border-0")}>
              <td className="whitespace-nowrap px-3 py-1.5">{row.label}</td>
              <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>
                <Amount value={row.receivable} />
              </td>
              <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3 text-right")}>
                <Amount value={row.payable} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
        Termin mają faktury sprzedaży (KSeF) i kosztowe; zapłaty bez faktury i bilans otwarcia są „bez terminu”.
      </p>
    </SectionCard>
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      aria-label="Zamknij kartę konta"
      onClick={onClose}
      className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <X className="h-3.5 w-3.5" />
    </button>
  );
}

function AccountCard({ account, asOf, onClose }: { account: string; asOf: string; onClose: () => void }) {
  const card = useSettlementAccount(account, asOf);
  const anchor = useRef<HTMLDivElement>(null);
  // Lista ma setki kontrahentów — karta otwiera się nad nią i od razu jest na ekranie.
  useEffect(() => {
    anchor.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, []);
  return (
    <div ref={anchor} className="scroll-mt-3">
      <AccountState card={card} account={account} onClose={onClose} />
    </div>
  );
}

function AccountState({
  card,
  account,
  onClose,
}: {
  card: ReturnType<typeof useSettlementAccount>;
  account: string;
  onClose: () => void;
}) {
  if (card.isError) {
    return (
      <SectionCard title={`Konto ${account}`} aside={<CloseButton onClose={onClose} />}>
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => card.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!card.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie konta…</p>;
  return <AccountBody data={card.data} onClose={onClose} />;
}

function AccountBody({ data, onClose }: { data: SettlementAccount; onClose: () => void }) {
  const { showToast } = useToast();
  const settle = useSettle();
  const auto = useAutoSettle();
  const [picked, setPicked] = useState<Set<number>>(() => new Set());
  const [raw, setRaw] = useState("");
  const [showSettled, setShowSettled] = useState(false);
  const chosen = selection(data.open, picked);
  const blocker = settleBlocker(chosen, data.can_settle);
  const problem = chosen.partial ? amountProblem(raw, chosen.amount, chosen.unit) : null;
  const unitAmount = (value: number) => (chosen.unit === "PLN" ? `${gr(value)} zł` : curAmount(value, chosen.unit));
  const typed = chosen.partial ? amountCents(raw) : null;
  const toggle = (lineId: number) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(lineId)) next.delete(lineId);
      else next.add(lineId);
      return next;
    });
  const reset = () => {
    setPicked(new Set());
    setRaw("");
  };
  const submit = () =>
    settle.mutate(
      {
        debit_ids: chosen.debits.map((item) => item.line_id),
        credit_ids: chosen.credits.map((item) => item.line_id),
        ...(typed != null ? { amount: (typed / 100).toFixed(2) } : {}),
      },
      {
        onSuccess: (result) => {
          reset();
          showToast(settleMessage(result.amount, result.created, result.fx_documents));
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się rozliczyć pozycji."), "error"),
      },
    );
  const runAuto = () =>
    auto.mutate(data.account, {
      onSuccess: (result) => {
        reset();
        showToast(autoMessage(result));
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się rozliczyć automatycznie."), "error"),
    });
  const title = data.name ? `${data.name} · ${data.account}` : `Konto ${data.account}`;

  return (
    <SectionCard title={title} aside={<CloseButton onClose={onClose} />}>
      <div className="grid gap-3 border-b border-border/70 px-3.5 py-2.5 text-[13px] lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0 space-y-0.5">
          <p className="tabular-nums">
            Wn otwarte <b className="font-semibold">{gr(data.debit_open)} zł</b> · Ma otwarte{" "}
            <b className="font-semibold">{gr(data.credit_open)} zł</b> · saldo {gr(data.balance)} zł
            {data.nip ? ` · NIP ${data.nip}` : ""}
          </p>
          <p className="text-[12px] text-muted-foreground">
            Zaznacz pozycje po obu stronach — rozliczą się od najstarszych. Przy jednej parze można wpisać kwotę.
          </p>
        </div>
        {data.can_settle ? (
          <div className="flex flex-wrap items-start gap-2 lg:justify-end">
            <Button size="sm" variant="outline" loading={auto.isPending} onClick={runAuto}>
              Automat dla konta
            </Button>
            {chosen.partial ? (
              <label className="flex flex-col gap-0.5">
                <input
                  className={cn(CONTROL, "w-32 text-right tabular-nums")}
                  inputMode="decimal"
                  placeholder={gr(chosen.amount)}
                  aria-label={chosen.unit === "PLN" ? "Kwota rozliczenia" : `Kwota rozliczenia w ${chosen.unit}`}
                  value={raw}
                  onChange={(event) => setRaw(event.target.value)}
                />
                {problem ? <span className="max-w-[220px] text-[12px] text-destructive">{problem}</span> : null}
              </label>
            ) : null}
            <Button
              size="sm"
              disabled={blocker != null || problem != null}
              title={blocker ?? undefined}
              loading={settle.isPending}
              onClick={submit}
            >
              {chosen.amount ? `Rozlicz ${unitAmount(typed ?? chosen.amount)}` : "Rozlicz zaznaczone"}
            </Button>
          </div>
        ) : (
          <p className="text-[12px] text-muted-foreground lg:text-right">
            Pozycje rozlicza osoba z listy „Księgowi” albo administrator.
          </p>
        )}
      </div>
      {data.open.length ? (
        <div className="grid divide-y divide-border/70 lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          {(["debit", "credit"] as const).map((direction) => (
            <ItemsTable
              key={direction}
              title={direction === "debit" ? "Wn — należności, zapłaty dostawcom" : "Ma — zobowiązania, wpłaty"}
              items={data.open.filter((item) => item.direction === direction)}
              picked={picked}
              canPick={data.can_settle}
              onToggle={toggle}
            />
          ))}
        </div>
      ) : (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">
          Na ten dzień konto nie ma otwartych pozycji.
        </p>
      )}
      {data.fx_documents?.length ? <FxDocuments documents={data.fx_documents} /> : null}
      {data.settled_total ? (
        <div className="border-t border-border/70">
          <button
            type="button"
            className="px-3.5 py-2 text-[12px] text-primary hover:underline"
            aria-expanded={showSettled}
            onClick={() => setShowSettled((value) => !value)}
          >
            {showSettled ? "Ukryj rozliczone" : `Rozliczone (${data.settled_total})`}
          </button>
          {showSettled ? <SettledList items={data.settled} canUndo={data.can_settle} /> : null}
        </div>
      ) : null}
    </SectionCard>
  );
}

/**
 * Wycena walut na koniec miesiąca z nagłówka (K4c-2): otwarte pozycje walutowe
 * i salda rachunków walutowych po kursie NBP z ostatniego dnia roboczego
 * miesiąca, PK wyceny i jej odwrócenie 1. dnia następnego miesiąca. Rozrachunki
 * zostają w kursach historycznych. Rachunek z wypłatami dla zespołu i pozycje
 * płacowe idą osobną PK płacową — widzi ją tylko osoba z Płacami (D2).
 */
function ValuationCard({ year, month }: { year: number; month: number }) {
  const { showToast } = useToast();
  const preview = useValuation(year, month);
  const post = usePostValuation();
  if (preview.isError) {
    return (
      <SectionCard title="Wycena walut">
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => preview.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!preview.isSuccess) return null;
  const data = preview.data;
  const rates = data.rates.map((rate) => `${rate.currency} ${rateLabel(rate.rate)} (${datePl(rate.date).slice(0, 5)})`);
  const changed = data.groups.filter((group) => group.changed && group.valuation);
  const run = () =>
    post.mutate(
      { year, month },
      {
        onSuccess: (result) => showToast(valuationMessage(result)),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zaksięgować wyceny."), "error"),
      },
    );
  return (
    <SectionCard
      title={`Wycena walut na ${datePl(data.day)}`}
      aside={rates.length ? `kurs NBP: ${rates.join(" · ")}` : `kurs NBP z ${datePl(data.rate_day)}`}
    >
      {data.positions.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Konto</th>
              <th className={cn(CALM_HEAD, "w-[18%] px-2 py-2 text-right")}>W walucie</th>
              <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-right")}>W księdze</th>
              <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-right")}>Po kursie</th>
              <th className={cn(CALM_HEAD, "w-[14%] py-2 pl-2 pr-3.5 text-right")}>Korekta</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((item) => (
              <tr key={`${item.kind}:${item.account}:${item.currency}:${item.payroll}`} className={cn(CALM_ROW, "last:border-0")}>
                <td className="min-w-0 px-3.5 py-1.5">
                  <span className="block truncate font-medium">{item.name || item.account}</span>
                  <span className={CALM_SUBLINE}>
                    {item.account} · {item.kind === "bank" ? "rachunek walutowy" : "rozrachunki"}
                    {item.payroll ? " · PK płacowa" : ""}
                  </span>
                </td>
                <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{curAmount(item.amount_cur, item.currency)}</td>
                <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{gr(item.book)}</td>
                {item.valued == null || item.diff == null ? (
                  <td colSpan={2} className="py-1.5 pl-2 pr-3.5 text-right text-[12px] text-warning-muted-foreground">
                    brak kursu NBP
                  </td>
                ) : (
                  <>
                    <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{gr(item.valued)}</td>
                    <td
                      className={cn(
                        CALM_AMOUNT,
                        "py-1.5 pl-2 pr-3.5 text-right",
                        item.diff < 0 ? "text-destructive" : item.diff > 0 ? "text-success-muted-foreground" : "",
                      )}
                    >
                      {item.diff > 0 ? "+" : ""}
                      {gr(item.diff)}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 py-4 text-[13px] text-muted-foreground">
          {data.skipped.length || data.payroll_hidden
            ? "Bez pozycji do wyceny automatycznej."
            : "Na ten dzień nie ma otwartych pozycji ani sald w walucie."}
        </p>
      )}
      {data.skipped.length ? (
        <div className="border-t border-border/70 px-3.5 py-2 text-[13px]">
          <p className="text-[12px] font-semibold text-muted-foreground">Poza wyceną — wyceń ręcznie (PK)</p>
          <ul className="mt-1 space-y-0.5">
            {data.skipped.map((item) => (
              <li key={item.account} className="min-w-0">
                <span className="font-medium">{item.name || item.account}</span>{" "}
                <span className="text-muted-foreground">
                  ({item.account}, {item.currency}): {item.reason}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3 border-t border-border/70 px-3.5 py-2.5 text-[13px]">
        <div className="min-w-0 space-y-0.5">
          <p className="tabular-nums">
            Dodatnie różnice <b className="font-semibold">{gr(data.gain)} zł</b> · ujemne{" "}
            <b className="font-semibold">{gr(data.loss)} zł</b>
          </p>
          {data.groups.some((group) => group.valuation || group.reversal) ? (
            data.groups.map((group) => (
              <p key={group.key} className="text-[12px] text-muted-foreground">
                {[group.valuation, group.reversal].map((doc, index) =>
                  doc ? (
                    <span key={doc.id}>
                      {index && group.valuation ? " · " : ""}
                      {index ? "odwrócenie " : group.payroll ? "wycena płacowa " : "wycena "}
                      <Link className="text-primary hover:underline" href={`/accounting/documents?status=${doc.status}&type=PK`}>
                        {doc.number}
                      </Link>{" "}
                      {doc.status === "approved" ? "zatwierdzona" : "w buforze"}
                    </span>
                  ) : null,
                )}
              </p>
            ))
          ) : (
            <p className="text-[12px] text-muted-foreground">
              PK wyceny na ten dzień i odwrócenie 1. dnia następnego miesiąca — rozrachunki zostają w kursach historycznych.
            </p>
          )}
          {changed.map((group) => (
            <p key={group.key} className="text-[12px] text-destructive">
              {group.valuation?.number} jest zatwierdzona, a dziś wychodzi inna — zrób jej storno i zaksięguj wycenę ponownie.
            </p>
          ))}
          {data.payroll_hidden ? (
            <p className="text-[12px] text-muted-foreground">
              Część płacowa (rachunek z wypłatami dla zespołu albo pozycje płacowe) — wycenia osoba z Płacami.
            </p>
          ) : null}
          {data.blocker ? <p className="text-[12px] text-warning-muted-foreground">{data.blocker}</p> : null}
        </div>
        {data.can_post && (data.positions.length || data.groups.length) ? (
          <Button size="sm" disabled={data.blocker != null} title={data.blocker ?? undefined} loading={post.isPending} onClick={run}>
            Zaksięguj wycenę
          </Button>
        ) : null}
      </div>
    </SectionCard>
  );
}

function FxDocuments({ documents }: { documents: readonly AccountFxDocument[] }) {
  return (
    <div className="border-t border-border/70 px-3.5 py-2 text-[13px]">
      <p className="text-[12px] font-semibold text-muted-foreground">Różnice kursowe z rozliczeń w walucie</p>
      <ul className="mt-1 space-y-0.5">
        {documents.map((doc) => (
          <li key={doc.id} className="flex flex-wrap items-baseline gap-x-2">
            <Link
              className="text-primary hover:underline"
              href={`/accounting/documents?status=${doc.status}&type=PK`}
            >
              {doc.number}
            </Link>
            <span className="tabular-nums">
              {doc.kind === "loss" ? "ujemna" : "dodatnia"} {gr(doc.amount)} zł
            </span>
            <span className="text-muted-foreground">
              {doc.status === "draft" ? "w buforze" : "zatwierdzona"} · {datePl(doc.op_date)}
            </span>
            {doc.orphan ? (
              <span className="text-warning-muted-foreground">
                rozliczenie już nie obowiązuje (storno faktury albo wpłaty) — zrób storno tej różnicy
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ItemsTable({
  title,
  items,
  picked,
  canPick,
  onToggle,
}: {
  title: string;
  items: SettlementItem[];
  picked: ReadonlySet<number>;
  canPick: boolean;
  onToggle: (lineId: number) => void;
}) {
  return (
    <div className="min-w-0">
      <p className="px-3.5 pb-1 pt-2.5 text-[12px] font-semibold text-muted-foreground">{title}</p>
      {items.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "w-[36px] px-3.5 py-1.5 text-left")}>
                <span className="sr-only">Zaznacz</span>
              </th>
              <th className={cn(CALM_HEAD, "px-2 py-1.5 text-left")}>Dokument</th>
              <th className={cn(CALM_HEAD, "w-[100px] px-2 py-1.5 text-left")}>Termin</th>
              <th className={cn(CALM_HEAD, "w-[118px] px-3.5 py-1.5 text-right")}>Zostało</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.line_id}
                className={cn(CALM_ROW, "align-top last:border-0", canPick && "cursor-pointer hover:bg-muted/40")}
                onClick={canPick ? () => onToggle(item.line_id) : undefined}
              >
                <td className="px-3.5 py-1.5">
                  <input
                    type="checkbox"
                    aria-label={`Zaznacz ${docLabel(item)}`}
                    checked={picked.has(item.line_id)}
                    disabled={!canPick}
                    onClick={(event) => event.stopPropagation()}
                    onChange={() => onToggle(item.line_id)}
                  />
                </td>
                <td className="min-w-0 px-2 py-1.5">
                  <span className="block truncate font-medium" title={item.description || undefined}>
                    {docLabel(item)}
                  </span>
                  <span className={cn(CALM_SUBLINE, "truncate")}>
                    {datePl(item.op_date)}
                    {item.description ? ` · ${item.description}` : ""}
                  </span>
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-[13px] tabular-nums">
                  {item.due_on ? datePl(item.due_on) : <span className={CALM_EMPTY}>bez terminu</span>}
                  {item.overdue_days ? (
                    <span className={cn(CALM_SUBLINE, "text-warning-muted-foreground")}>
                      po terminie {daysLabel(item.overdue_days)}
                    </span>
                  ) : null}
                </td>
                <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5 text-right")}>
                  {isForeign(item) ? (
                    <>
                      {curAmount(item.remaining_cur ?? 0, item.currency)}
                      <span className={CALM_SUBLINE}>{gr(item.remaining)} zł</span>
                      {item.remaining_cur !== item.amount_cur ? (
                        <span className={CALM_SUBLINE}>z {curAmount(item.amount_cur ?? 0, item.currency)}</span>
                      ) : null}
                    </>
                  ) : (
                    <>
                      {gr(item.remaining)}
                      {item.remaining !== item.value ? <span className={CALM_SUBLINE}>z {gr(item.value)}</span> : null}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 pb-3 pt-1 text-[13px] text-muted-foreground">Brak otwartych pozycji po tej stronie.</p>
      )}
    </div>
  );
}

function SettledList({ items, canUndo }: { items: SettlementItem[]; canUndo: boolean }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const unsettle = useUnsettle();
  const undo = async (id: number, label: string) => {
    const ok = await askConfirm({
      title: "Cofnąć rozliczenie?",
      description: `${label} — obie pozycje wrócą do otwartych. Ślad rozliczenia i cofnięcia zostaje.`,
      confirmLabel: "Cofnij rozliczenie",
      variant: "destructive",
    });
    if (!ok) return;
    unsettle.mutate(id, {
      onSuccess: () => showToast("Cofnięto rozliczenie."),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się cofnąć rozliczenia."), "error"),
    });
  };
  return (
    <ul className="divide-y divide-border/60 border-t border-border/70">
      {items.map((item) => (
        <li key={item.line_id} className="grid gap-1 px-3.5 py-2 text-[13px] sm:grid-cols-[minmax(0,240px)_minmax(0,1fr)]">
          <div className="min-w-0">
            <span className="block truncate font-medium">{docLabel(item)}</span>
            <span className={CALM_SUBLINE}>
              {datePl(item.op_date)} · {item.direction === "debit" ? "Wn" : "Ma"} {gr(item.value)} zł
            </span>
          </div>
          <ul className="min-w-0 space-y-0.5">
            {item.settlements.map((link) => {
              const label = `${docLabel(item)} z ${docLabel(link.other)}, ${gr(link.amount)} zł`;
              return (
                <li key={`${link.id}`} className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-muted-foreground">
                  <span className="text-foreground">{docLabel(link.other)}</span>
                  <span className="tabular-nums">
                    {link.amount_cur && link.currency ? `${curAmount(link.amount_cur, link.currency)} · ` : ""}
                    {gr(link.amount)} zł
                  </span>
                  <span>
                    {link.method_label} · {datePl(link.settled_on)}
                    {link.by ? ` · ${link.by}` : ""}
                  </span>
                  {canUndo ? (
                    <button
                      type="button"
                      className="text-primary hover:underline"
                      onClick={() => void undo(link.id, label)}
                    >
                      Cofnij
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </li>
      ))}
      {confirmDialog}
    </ul>
  );
}
