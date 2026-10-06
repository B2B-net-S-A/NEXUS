"use client";

// Historia stawek kandydata (0414, makieta B z 04.10.2026).
//
// Każda stawka, którą kandydat podał (karty rekomendacji, okno
// „Zweryfikowany”, profil, formularz), z rekrutacją i powodem, dla którego
// liczy się — albo nie — do „Stawki od”. Obok stawki z umów (co płaciliśmy).
// Liczy serwer; tu pokazujemy i pozwalamy wyłączyć pojedynczą stawkę.

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiErrorMessage } from "@/lib/api-error";
import {
  candidateRatesApi,
  useRateOverview,
  type RateObservation,
  type RateOverview,
} from "@/lib/api/candidateRates";
import {
  dayText,
  hourlyText,
  monthYear,
  rateFromContextLine,
  rateReasonLabel,
  rateSourceLabel,
  toAmount,
} from "@/lib/candidate-rate";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { useCapability } from "@/hooks/useCapability";

const CHART_W = 640;
const CHART_H = 200;
const PAD = { left: 44, right: 16, top: 16, bottom: 30 };

type Tone = "primary" | "warning" | "info";

function toneOf(source: string): Tone {
  if (source.startsWith("profile")) return "warning";
  if (
    source === "application" ||
    source === "rate_requested" ||
    source === "note"
  ) {
    return "info";
  }
  return "primary";
}

const TONE_FILL: Record<Tone, string> = {
  primary: "fill-primary",
  warning: "fill-warning",
  info: "fill-info",
};

export function RateHistoryChart({ overview }: { overview: RateOverview }) {
  const points = overview.observations
    .map((o) => ({ o, amount: toAmount(o.amount_hourly), at: o.at ? Date.parse(o.at) : NaN }))
    .filter((p) => p.amount !== null && Number.isFinite(p.at));
  const paid = overview.paid
    .map((p) => ({
      p,
      amount: toAmount(p.amount_hourly),
      start: p.start_date ? Date.parse(p.start_date) : NaN,
      end: p.end_date ? Date.parse(p.end_date) : Date.now(),
    }))
    .filter((p) => p.amount !== null && Number.isFinite(p.start));
  if (points.length === 0 && paid.length === 0) return null;

  const windowStart = Date.parse(overview.window_start);
  const now = Date.now();
  const xs = [...points.map((p) => p.at), ...paid.map((p) => p.start), windowStart];
  const minX = Math.min(...xs);
  const maxX = Math.max(now, ...points.map((p) => p.at));
  const amounts = [
    ...points.map((p) => p.amount as number),
    ...paid.map((p) => p.amount as number),
  ];
  const rawMin = Math.min(...amounts);
  const rawMax = Math.max(...amounts);
  const step = rawMax - rawMin > 100 ? 40 : 20;
  const minY = Math.max(0, Math.floor((rawMin - step / 2) / step) * step);
  const maxY = Math.ceil((rawMax + step / 2) / step) * step;
  const plotW = CHART_W - PAD.left - PAD.right;
  const plotH = CHART_H - PAD.top - PAD.bottom;
  const x = (t: number) =>
    PAD.left + (maxX === minX ? plotW / 2 : ((t - minX) / (maxX - minX)) * plotW);
  const y = (v: number) => PAD.top + ((maxY - v) / (maxY - minY)) * plotH;
  const ticks: number[] = [];
  for (let v = minY; v <= maxY; v += step) ticks.push(v);
  const years: number[] = [];
  for (
    let year = new Date(minX).getFullYear() + 1;
    year <= new Date(maxX).getFullYear();
    year += 1
  ) {
    years.push(Date.UTC(year, 0, 1));
  }
  const minimum = toAmount(overview.rate_from?.amount);
  const bandStart = Math.max(windowStart, minX);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="h-auto w-full min-w-[480px]"
        role="img"
        aria-label="Stawki kandydata w czasie"
      >
        <rect
          x={x(bandStart)}
          y={PAD.top}
          width={Math.max(0, x(maxX) - x(bandStart))}
          height={plotH}
          className="fill-success/10"
        />
        {ticks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={CHART_W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              className="stroke-border"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 6}
              y={y(v) + 3}
              textAnchor="end"
              className="fill-muted-foreground text-[10px] tabular-nums"
            >
              {v}
            </text>
          </g>
        ))}
        {years.map((t) => (
          <text
            key={t}
            x={x(t)}
            y={CHART_H - 10}
            textAnchor="middle"
            className="fill-muted-foreground text-[10px]"
          >
            {new Date(t).getUTCFullYear()}
          </text>
        ))}
        <text
          x={x(bandStart) + 4}
          y={PAD.top + 11}
          className="fill-success text-[10px]"
        >
          ostatnie 18 mies.
        </text>
        {paid.map(({ p, amount, start, end }, index) => (
          <line
            key={`paid-${index}`}
            x1={x(start)}
            x2={x(Math.min(end, maxX))}
            y1={y(amount as number)}
            y2={y(amount as number)}
            className="stroke-foreground/50"
            strokeWidth={5}
            strokeLinecap="round"
          >
            <title>{`Umowa ${p.client_name ?? ""}: ${hourlyText(amount)}`}</title>
          </line>
        ))}
        {minimum !== null ? (
          <line
            x1={x(bandStart)}
            x2={CHART_W - PAD.right}
            y1={y(minimum)}
            y2={y(minimum)}
            className="stroke-success"
            strokeWidth={1.5}
            strokeDasharray="5 4"
          />
        ) : null}
        {points.map(({ o, amount, at }) => (
          <circle
            key={o.key}
            cx={x(at)}
            cy={y(amount as number)}
            r={o.reason === "minimum" ? 7 : 5.5}
            className={`${TONE_FILL[toneOf(o.source)]} ${
              o.reason === "excluded" || o.reason === "outside_window"
                ? "opacity-40"
                : ""
            }`}
          >
            <title>{`${hourlyText(amount)} · ${rateSourceLabel(o.source)}${
              o.job_title ? ` · ${o.job_title}` : ""
            }`}</title>
          </circle>
        ))}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-full bg-primary" />
          rozmowa o rekrutacji
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-full bg-warning" />
          profil
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-full bg-info" />
          formularz zgłoszenia
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-1 w-4 rounded bg-foreground/50" />
          umowa u nas (co płaciliśmy)
        </li>
      </ul>
    </div>
  );
}

function reasonVariant(reason: string) {
  if (reason === "minimum") return "success" as const;
  if (reason === "counts") return "neutral" as const;
  return "outline" as const;
}

function ObservationRow({
  observation,
  canEdit,
  pending,
  onDecide,
}: {
  observation: RateObservation;
  canEdit: boolean;
  pending: boolean;
  onDecide: (key: string, decision: "exclude" | null) => void;
}) {
  const o = observation;
  const comparable = o.reason !== "not_comparable";
  const where = [o.job_title, o.client_name].filter(Boolean).join(" · ");
  return (
    <tr className="border-b border-border last:border-0">
      <td className="whitespace-nowrap py-2 pr-3 align-top tabular-nums">
        {dayText(o.at) ?? "—"}
      </td>
      <td className="whitespace-nowrap py-2 pr-3 align-top font-medium tabular-nums">
        {hourlyText(o.amount_hourly) ?? o.raw ?? "—"}
        {o.raw && hourlyText(o.amount_hourly) && o.raw !== hourlyText(o.amount_hourly) ? (
          <span className="block text-xs font-normal text-muted-foreground">
            „{o.raw}”
          </span>
        ) : null}
      </td>
      <td className="min-w-0 py-2 pr-3 align-top">
        {where || <span className="text-muted-foreground">—</span>}
      </td>
      <td className="py-2 pr-3 align-top text-xs text-muted-foreground">
        {rateSourceLabel(o.source)}
        {o.author_name ? ` · ${o.author_name}` : ""}
        {o.explicit_minimum ? " · jawne minimum" : ""}
      </td>
      <td className="py-2 pr-3 align-top">
        <Badge variant={reasonVariant(o.reason)} className="whitespace-normal">
          {rateReasonLabel(o.reason, o.excluded_by_name)}
        </Badge>
      </td>
      <td className="py-2 align-top text-right">
        {canEdit && comparable ? (
          <Button
            type="button"
            size="sm"
            variant="quiet"
            disabled={pending}
            onClick={() =>
              onDecide(o.key, o.reason === "excluded" ? null : "exclude")
            }
          >
            {o.reason === "excluded" ? "Przywróć" : "Nie licz jako minimum"}
          </Button>
        ) : null}
      </td>
    </tr>
  );
}

export function RateHistoryDialog({
  open,
  onOpenChange,
  candidateId,
  canEdit,
  onSetMinimum,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  canEdit: boolean;
  onSetMinimum?: () => void;
}) {
  const query = useRateOverview(candidateId, open);
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const decide = useMutation({
    mutationFn: ({ key, decision }: { key: string; decision: "exclude" | null }) =>
      candidateRatesApi.decide(candidateId, key, decision),
    onSuccess: (_data, variables) => {
      invalidateCandidateMutation(queryClient, candidateId, "rate");
      showSuccess(
        variables.decision === "exclude"
          ? "Stawka nie liczy się już do minimum"
          : "Stawka znowu liczy się do minimum",
      );
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji")),
  });

  const overview = query.data;
  const context = rateFromContextLine(overview?.rate_from ?? null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl" aria-describedby="rate-history-description">
        <DialogHeader>
          <DialogTitle>Historia stawek</DialogTitle>
          <DialogDescription id="rate-history-description">
            {context
              ? `${context}. Filtry i AI porównują budżet z najniższą stawką z ostatnich 18 miesięcy.`
              : "Filtry i AI porównują budżet z najniższą stawką z ostatnich 18 miesięcy."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4 overflow-y-auto">
          {query.isPending ? (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
              Ładowanie historii…
            </p>
          ) : query.isError ? (
            <div role="alert" className="flex items-center gap-3 text-sm">
              Nie udało się pobrać historii stawek.
              <Button type="button" size="sm" variant="outline" onClick={() => query.refetch()}>
                Ponów
              </Button>
            </div>
          ) : overview && overview.observations.length === 0 && overview.paid.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Kandydat nie podał jeszcze żadnej stawki.
            </p>
          ) : overview ? (
            <>
              <RateHistoryChart overview={overview} />
              {overview.observations.length ? (
                <div className="relative overflow-x-auto">
                  <table className="w-full min-w-[640px] text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted-foreground">
                        <th className="py-2 pr-3 font-medium">Data</th>
                        <th className="py-2 pr-3 font-medium">Stawka</th>
                        <th className="py-2 pr-3 font-medium">Rekrutacja · klient</th>
                        <th className="py-2 pr-3 font-medium">Skąd</th>
                        <th className="py-2 pr-3 font-medium">Do minimum</th>
                        <th className="py-2 font-medium">
                          <span className="sr-only">Akcje</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.observations.map((o) => (
                        <ObservationRow
                          key={o.key}
                          observation={o}
                          canEdit={canEdit}
                          pending={decide.isPending}
                          onDecide={(key, decision) => decide.mutate({ key, decision })}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {overview.paid.length ? (
                <section aria-label="Umowy u nas">
                  <h3 className="mb-1 text-sm font-medium">Umowy u nas (co płaciliśmy)</h3>
                  <ul className="space-y-1 text-sm">
                    {overview.paid.map((p, index) => (
                      <li key={index} className="flex flex-wrap gap-x-2 text-muted-foreground">
                        <span className="font-medium text-foreground tabular-nums">
                          {p.redacted
                            ? "kwota ukryta (brak dostępu do finansów)"
                            : (hourlyText(p.amount_hourly) ?? "—")}
                        </span>
                        <span>{p.client_name ?? "—"}</span>
                        <span>
                          {[monthYear(p.start_date), p.end_date ? monthYear(p.end_date) : "teraz"]
                            .filter(Boolean)
                            .join("–")}
                        </span>
                        {p.kind === "legacy" ? <span>(stary wpis)</span> : null}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Stawki z umów nie liczą się do „Stawki od” — to cena, nie oczekiwanie.
                  </p>
                </section>
              ) : null}
            </>
          ) : null}
        </DialogBody>
        <DialogFooter>
          {canEdit && onSetMinimum ? (
            <Button type="button" variant="outline" onClick={onSetMinimum}>
              Ustaw minimum ręcznie
            </Button>
          ) : null}
          <Button type="button" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Skrót w zakładce „Rekrutacje” (zastępuje stary widżet stawek z umów,
 * edytowany tylko przez admina): „Stawka od 80 zł/h · Historia stawek (7)”.
 * Bez żadnej stawki w historii — nic się nie renderuje.
 */
export function RateHistorySummary({ candidateId }: { candidateId: number }) {
  const canManage = useCapability("candidate.profile_fact.manage");
  const [open, setOpen] = React.useState(false);
  const query = useRateOverview(candidateId, canManage);
  const overview = query.data;
  if (!canManage || !overview) return null;
  if (overview.observations.length === 0 && overview.paid.length === 0) return null;
  const context = rateFromContextLine(overview.rate_from);
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-sm">
      <p className="font-medium">{context ?? "Brak porównywalnej stawki"}</p>
      <button
        type="button"
        className="mt-1 text-xs text-primary hover:underline"
        onClick={() => setOpen(true)}
      >
        Historia stawek ({overview.observations.length})
      </button>
      <RateHistoryDialog
        open={open}
        onOpenChange={setOpen}
        candidateId={candidateId}
        canEdit={canManage}
      />
    </div>
  );
}
