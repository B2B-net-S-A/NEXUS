"use client";

/**
 * „Wnioski”: co się powtarza w danych, które NEXUS już zbiera, i decyzja, co z tym zrobić
 * (decyzje Artura 04.11.2026). „Tak” zapisuje decyzję, działania systemu nie zmienia.
 * Reguła: `docs/claude/finanse-insights/zakladka-wnioski.md`.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";

import {
  WnioskiPeoplePanel,
  type WnioskiPeopleSelection,
} from "@/components/insights/sections/WnioskiPeoplePanel";
import { SectionError } from "@/components/insights/sections/_shared";
import { Panel, PanelLoading, Takeaway, Tile, TileRow, ViewHeader } from "@/components/insights/views/ViewKit";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { holdsCapabilityGrant } from "@/lib/capabilities";
import {
  insightsApi,
  insightsQueryKeys,
  type WnioskiCase,
  type WnioskiHistoryResponse,
  type WnioskiRuleCohort,
  type WnioskiState,
} from "@/lib/insights-api";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

type Section = "decyzje" | "powody" | "zbieramy" | "historia";

const STATUS_VARIANT: Record<string, "success" | "info" | "warning" | "neutral"> = {
  "Działa samo": "success",
  "Tylko raport": "info",
  "Nikt nie czyta": "warning",
  "Nikt nie używa": "neutral",
};

const DAY_MONTH = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Warsaw",
});
const TIME = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

const onDay = (iso: string): string => DAY_MONTH.format(new Date(iso));
const fmt = (value: number): string => value.toLocaleString("pl-PL");

function DecisionRow({
  item,
  open,
  mayDecide,
  busy,
  onToggle,
  onDecide,
}: {
  item: WnioskiCase;
  open: boolean;
  mayDecide: boolean;
  busy: boolean;
  onToggle: () => void;
  onDecide: (state: WnioskiState) => void;
}) {
  return (
    <li className="grid gap-4 p-4 sm:grid-cols-[104px_minmax(0,1fr)]" data-testid={`decision-${item.key}`}>
      <div>
        <div className="text-2xl font-semibold tabular-nums text-foreground">{item.number}</div>
        <div className="text-xs text-muted-foreground">{item.number_note}</div>
      </div>
      <div className="min-w-0 space-y-1">
        <h3 className="text-sm font-semibold text-foreground">{item.title}</h3>
        <p className="text-sm text-muted-foreground">{item.why}</p>
        <p className="text-sm text-foreground">
          <span className="font-medium">Jeśli tak:</span> {item.if_yes}
        </p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {mayDecide ? (
            <>
              <Button size="sm" disabled={busy} onClick={() => onDecide("approved")}>
                {item.yes_label}
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecide("later")}>
                Nie teraz
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecide("rejected")}>
                Nie
              </Button>
            </>
          ) : null}
          <button
            type="button"
            aria-expanded={open}
            onClick={onToggle}
            className="ml-1 inline-flex items-center gap-1 rounded-md text-sm text-primary hover:underline"
          >
            {open ? <ChevronDown className="h-4 w-4" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}
            Skąd to wiemy
          </button>
          <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant={item.certainty === "Policzone" ? "success" : "neutral"}>{item.certainty}</Badge>
            Decyduje: {item.owner}
          </span>
        </div>
        {open ? (
          <div className="mt-2 space-y-2 rounded-md bg-muted/50 px-3 py-2 text-sm">
            <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
              {item.evidence.map((row) => (
                <div key={row.label} className="flex items-baseline justify-between gap-3">
                  <dt className="min-w-0 text-muted-foreground">{row.label}</dt>
                  <dd className="shrink-0 font-medium tabular-nums text-foreground">{row.value}</dd>
                </div>
              ))}
            </dl>
            <p className="text-foreground">
              <span className="font-medium">Ryzyko:</span> {item.risk}
            </p>
          </div>
        ) : null}
      </div>
    </li>
  );
}

const CONFIRM_COPY: Partial<Record<WnioskiState, { title: string; description: string; confirmLabel: string }>> = {
  approved: {
    title: "Zapisać decyzję „Tak”?",
    description:
      "Zapisujemy, kto i kiedy zdecydował. Działanie systemu się nie zmienia: zmiana przechodzi zwykłą drogę, a po 30 dniach zobaczysz ocenę.",
    confirmLabel: "Zapisz decyzję",
  },
  rejected: {
    title: "Zapisać decyzję „Nie”?",
    description: "Sprawa zniknie z listy i wróci dopiero wtedy, gdy liczba wzrośnie dwukrotnie.",
    confirmLabel: "Zapisz decyzję",
  },
};

function DecisionsSection() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasRole(user, "admin");
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.wnioski(),
    queryFn: insightsApi.wnioski,
  });

  const decide = useMutation({
    mutationFn: ({ key, state }: { key: string; state: WnioskiState }) => insightsApi.wnioskiDecide(key, state),
    onSuccess: () => {
      setMessage(null);
      void queryClient.invalidateQueries({ queryKey: insightsQueryKeys.wnioski() });
    },
    onError: (err) => {
      setMessage(apiErrorMessage(err, "Nie udało się zapisać decyzji."));
      void queryClient.invalidateQueries({ queryKey: insightsQueryKeys.wnioski() });
    },
  });

  const handleDecide = async (key: string, state: WnioskiState) => {
    const copy = CONFIRM_COPY[state];
    if (copy && !(await askConfirm(copy))) return;
    decide.mutate({ key, state });
  };

  return (
    <div className="space-y-4">
      {confirmDialog}
      {message ? (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {message}
        </p>
      ) : null}
      {isPending ? (
        <PanelLoading />
      ) : isError ? (
        <SectionError label="Wnioski" error={error} onRetry={() => void refetch()} />
      ) : isSuccess && data.cases.length > 0 ? (
        <ul className="divide-y divide-border rounded-xl border border-border bg-card shadow-xs">
          {data.cases.map((item) => (
            <DecisionRow
              key={item.key}
              item={item}
              open={openKey === item.key}
              mayDecide={isAdmin || item.owner_role !== "admin"}
              busy={decide.isPending}
              onToggle={() => setOpenKey(openKey === item.key ? null : item.key)}
              onDecide={(state) => void handleDecide(item.key, state)}
            />
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Nic nie czeka na decyzję. Nowa sprawa pojawi się tu, gdy dane przekroczą próg.
        </p>
      )}
      {isSuccess && data.watching.length > 0 ? (
        <Panel title="Obserwujemy" hint="Za mało danych na decyzję">
          <ul className="grid gap-x-6 gap-y-1 text-sm lg:grid-cols-3">
            {data.watching.map((item) => (
              <li key={item.text} className="flex min-w-0 items-baseline justify-between gap-3 lg:block">
                <span className="text-muted-foreground">{item.text}: </span>
                <span className="whitespace-nowrap font-medium tabular-nums text-foreground">{item.value}</span>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

function CountButton({
  value,
  label,
  onPick,
  className,
}: {
  value: number;
  label: string;
  onPick: (() => void) | null;
  className?: string;
}) {
  if (!onPick || value === 0) {
    return <span className={className}>{fmt(value)}</span>;
  }
  return (
    <button
      type="button"
      onClick={onPick}
      aria-label={`${label}: ${fmt(value)}, pokaż osoby`}
      className={cn(
        "rounded underline decoration-dotted decoration-muted-foreground/50 underline-offset-2 hover:text-primary",
        className,
      )}
    >
      {fmt(value)}
    </button>
  );
}

function ReasonsSection({ seesPeople }: { seesPeople: boolean }) {
  const [selection, setSelection] = useState<WnioskiPeopleSelection | null>(null);
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.wnioskiReasons(),
    queryFn: insightsApi.wnioskiReasons,
  });

  if (isPending) return <PanelLoading />;
  if (isError) return <SectionError label="Powody odrzuceń" error={error} onRetry={() => void refetch()} />;

  const max = Math.max(1, ...data.why_out.map((row) => Math.max(row.today, row.after)));
  return (
    <div className="space-y-4">
      <Panel
        title="Dlaczego ludzie odpadają"
        actions={
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-primary/60" aria-hidden />
              Dziś w raporcie
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-primary" aria-hidden />
              Po odczytaniu opisów
            </span>
            <Badge variant="neutral">Szacunek</Badge>
          </div>
        }
      >
        <div className="space-y-2">
          {data.why_out.map((row) => (
            <div key={row.key} className="grid items-center gap-x-3 sm:grid-cols-[240px_minmax(0,1fr)]">
              <div className="text-sm text-foreground">{row.reason}</div>
              <div className="space-y-0.5">
                {[
                  { value: row.today, color: "bg-primary/60", label: "dziś", basis: "today" as const },
                  { value: row.after, color: "bg-primary", label: "po odczytaniu", basis: "after" as const },
                ].map((bar) => (
                  <div key={bar.label} className="flex items-center gap-2" title={`${row.reason}, ${bar.label}: ${bar.value}`}>
                    <div
                      className={cn("h-2 rounded-r", bar.color)}
                      style={{ width: bar.value ? `${(bar.value / max) * 80}%` : 0 }}
                    />
                    <CountButton
                      value={bar.value}
                      label={`${row.reason}, ${bar.label}`}
                      className="text-xs tabular-nums text-muted-foreground"
                      onPick={
                        seesPeople
                          ? () =>
                              setSelection({
                                bucket: row.key,
                                basis: bar.basis,
                                title: `${row.reason}, ${bar.label}`,
                                total: bar.value,
                              })
                          : null
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        {data.why_out_takeaway ? <Takeaway>{data.why_out_takeaway}</Takeaway> : null}
      </Panel>
      <Panel title="U każdego klienta wygląda to inaczej" hint="Odsetek odrzuceń u klienta, po odczytaniu opisów">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-separate border-spacing-0.5 text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="sticky left-0 z-10 bg-card px-2 py-1 text-left font-medium">Klient</th>
                <th className="px-2 py-1 text-right font-medium">Odrzuceń</th>
                {data.columns.map((column) => (
                  <th key={column.key} className="px-2 py-1 text-center font-medium">
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.heatmap.map((row) => (
                <tr key={`${row.client_id}-${row.client}`}>
                  <td className="sticky left-0 z-10 bg-card whitespace-nowrap px-2 py-1 text-foreground">{row.client}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">{fmt(row.total)}</td>
                  {row.values.map((value, index) => {
                    const column = data.columns[index];
                    const pct = Math.round((100 * value) / row.total);
                    const strength = Math.min(pct / 55, 1);
                    const pickable = seesPeople && value > 0;
                    const open = () =>
                      setSelection({
                        bucket: column.key,
                        basis: "after",
                        client_id: row.client_id,
                        title: `${row.client}, ${column.label}`,
                        total: value,
                      });
                    return (
                      <td
                        key={column.key}
                        title={`${row.client}, ${column.label}: ${value} z ${row.total}`}
                        className={cn(
                          "rounded px-2 py-1 text-center tabular-nums",
                          strength > 0.6 ? "text-primary-foreground" : "text-foreground",
                        )}
                        style={{ backgroundColor: `hsl(var(--primary) / ${strength.toFixed(2)})` }}
                      >
                        {pickable ? (
                          <button
                            type="button"
                            onClick={open}
                            aria-label={`${row.client}, ${column.label}: ${value}, pokaż osoby`}
                            className="w-full rounded underline decoration-dotted underline-offset-2"
                          >
                            {pct}%
                          </button>
                        ) : (
                          `${pct}%`
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.heatmap_takeaway ? <Takeaway>{data.heatmap_takeaway}</Takeaway> : null}
      </Panel>
      <p className="text-xs text-muted-foreground">
        {fmt(data.total)} odrzuceń od {data.counted_from_label}.{" "}
        Odczyt opisów to słowa kluczowe, nie prawda: na ręcznie sprawdzonych 90 wpisach zgadzało się ok. 90%. Oryginalne wpisy zostają nietknięte.
        {seesPeople ? " Podkreślona liczba otwiera listę osób." : ""}
      </p>
      {selection ? (
        <WnioskiPeoplePanel
          key={`${selection.bucket}-${selection.basis}-${selection.client_id ?? "all"}`}
          selection={selection}
          onClose={() => setSelection(null)}
        />
      ) : null}
    </div>
  );
}

function CollectedSection() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.wnioskiCollected(),
    queryFn: insightsApi.wnioskiCollected,
  });
  if (isPending) return <PanelLoading />;
  if (isError) return <SectionError label="Co zbieramy" error={error} onRetry={() => void refetch()} />;
  return (
    <div className="space-y-4">
      <TileRow>
        {data.statuses.map((status) => (
          <Tile key={status} label={status} value={String(data.rows.filter((row) => row.status === status).length)} />
        ))}
      </TileRow>
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="sticky left-0 z-10 bg-card px-4 py-2 font-medium">Co zbieramy</th>
              <th className="px-4 py-2 text-right font-medium">Ile</th>
              <th className="px-4 py-2 font-medium">Co się z tym dzieje dziś</th>
              <th className="px-4 py-2 font-medium">Stan</th>
              <th className="px-4 py-2 font-medium">Co dalej</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.rows.map((row) => (
              <tr key={row.signal}>
                <td className="sticky left-0 z-10 bg-card px-4 py-2 text-foreground">{row.signal}</td>
                <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">{row.amount}</td>
                <td className="px-4 py-2 text-muted-foreground">{row.today}</td>
                <td className="whitespace-nowrap px-4 py-2">
                  <Badge variant={STATUS_VARIANT[row.status] ?? "neutral"}>{row.status}</Badge>
                </td>
                <td className="px-4 py-2 text-muted-foreground">{row.next}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function perHundred(cohort: WnioskiRuleCohort): string {
  if (cohort.per_100 === null) return "—";
  return cohort.per_100.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function ApprovedList({ rows }: { rows: WnioskiHistoryResponse["approved"] }) {
  return (
    <ul className="space-y-2 text-sm">
      {rows.map((row) => (
        <li key={`${row.key}-${row.decided_at}`} className="flex gap-2" data-testid={`history-approved-${row.key}`}>
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <p className="text-foreground">{row.title}</p>
            <p className="text-xs text-muted-foreground">
              Zatwierdzone {onDay(row.decided_at)}
              {row.decided_by ? `, ${row.decided_by}` : ""}. Przy decyzji: {row.number}.
              {row.measure ? ` Mierzymy: ${row.measure}.` : ""}
              {row.change ? ` Zmiana: ${row.change}.` : " Czeka na realizację."}
              {row.measure_now
                ? ` Po 30 dniach: ${row.measure_now}.`
                : row.review_on
                  ? ` Ocena ${onDay(row.review_on)}.`
                  : ""}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

function HistorySection() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.wnioskiHistory(),
    queryFn: insightsApi.wnioskiHistory,
  });
  if (isPending) return <PanelLoading />;
  if (isError) return <SectionError label="Historia decyzji" error={error} onRetry={() => void refetch()} />;
  return (
    <div className="space-y-4">
      <Panel title="Zatwierdzone" hint="Zatwierdzone → zmiana w kodzie → działa → ocena po 30 dniach">
        <ApprovedList rows={data.approved} />
      </Panel>
      {data.deferred.length > 0 ? (
        <Panel title="Odłożone i odrzucone">
          <ul className="space-y-1.5 text-sm" data-testid="history-deferred">
            {data.deferred.map((row) => (
              <li key={`${row.key}-${row.decided_at}`} className="min-w-0">
                <span className="text-foreground">{row.title}</span>{" "}
                <span className="text-xs text-muted-foreground">
                  {row.state === "later" ? "Nie teraz" : "Nie"}, {onDay(row.decided_at)}
                  {row.decided_by ? `, ${row.decided_by}` : ""}.{" "}
                  {row.state === "later" && row.return_on
                    ? `Wraca ${onDay(row.return_on)}.`
                    : row.return_count !== null
                      ? `Wraca, gdy liczba z 30 dni dojdzie do ${fmt(row.return_count)}.`
                      : ""}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <Panel title="Czy pomogło" hint="Odrzucenia w pierwszych 3 dniach na 100 osób dodanych przez system">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="sticky left-0 z-10 bg-card py-2 pr-4 font-medium">Reguła</th>
                <th className="py-2 pr-4 font-medium">Od</th>
                <th className="py-2 pr-4 font-medium">Powód</th>
                <th className="py-2 pr-4 text-right font-medium">Przed, na 100</th>
                <th className="py-2 pr-4 text-right font-medium">Po, na 100</th>
                <th className="py-2 font-medium">Wynik</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.rules.map((row) => (
                <tr key={row.rule}>
                  <td className="sticky left-0 z-10 bg-card py-2 pr-4 text-foreground">{row.rule}</td>
                  <td className="py-2 pr-4 tabular-nums text-muted-foreground">{row.since}</td>
                  <td className="whitespace-nowrap py-2 pr-4 text-muted-foreground">{row.metric}</td>
                  <td
                    className="whitespace-nowrap py-2 pr-4 text-right tabular-nums"
                    title={`${row.before.hits} z ${row.before.added} dodanych`}
                  >
                    {perHundred(row.before)}
                  </td>
                  <td
                    className="whitespace-nowrap py-2 pr-4 text-right tabular-nums"
                    title={`${row.after.hits} z ${row.after.added} dodanych`}
                  >
                    {perHundred(row.after)}
                  </td>
                  <td className="whitespace-nowrap py-2">
                    <Badge variant="neutral">{row.verdict ?? `Za wcześnie, ocena ${onDay(row.review_on)}`}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.rules_takeaway ? <Takeaway>{data.rules_takeaway}</Takeaway> : null}
      </Panel>
    </div>
  );
}

export function WnioskiView() {
  const [section, setSection] = useState<Section>("decyzje");
  const user = useAuthStore((s) => s.user);
  // Lustro `CandidatePIIAccess`, jak `seesSources` w `InsightsView`.
  const seesPeople = Boolean(
    user &&
      holdsCapabilityGrant(user, "nav.candidates") &&
      (hasSectionAccess(user, "sourcing") || hasSectionAccess(user, "pipeline")),
  );
  const summary = useQuery({
    queryKey: insightsQueryKeys.wnioski(),
    queryFn: insightsApi.wnioski,
  });
  const openCount = summary.data?.open_count ?? null;
  const sections: { value: Section; label: string }[] = [
    { value: "decyzje", label: openCount === null ? "Do decyzji" : `Do decyzji (${openCount})` },
    { value: "powody", label: "Powody odrzuceń" },
    { value: "zbieramy", label: "Co zbieramy" },
    { value: "historia", label: "Historia decyzji" },
  ];
  const stamp = summary.data
    ? `Dane na dziś, policzone o ${TIME.format(new Date(summary.data.computed_at))}.`
    : "Dane na dziś.";
  return (
    <div className="space-y-4">
      <ViewHeader
        question="Co zmienić, żeby praca szła lepiej?"
        lede={`Wnioski z tego, co zespół i klienci już robią w NEXUSIE, od ${summary.data?.counted_from_label ?? "12.10"}. ${stamp}`}
        actions={
          <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1" role="group" aria-label="Część widoku">
            {sections.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={section === item.value}
                onClick={() => setSection(item.value)}
                className={cn(
                  "whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  section === item.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
      />
      {section === "decyzje" && <DecisionsSection />}
      {section === "powody" && <ReasonsSection seesPeople={seesPeople} />}
      {section === "zbieramy" && <CollectedSection />}
      {section === "historia" && <HistorySection />}
    </div>
  );
}
