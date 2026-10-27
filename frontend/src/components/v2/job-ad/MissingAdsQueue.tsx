"use client";

/**
 * „Ogłoszenia do nadrobienia” (27.10.2026) — otwarte rekrutacje, w których
 * osobie brakuje strony kariery, Pracuj.pl albo JustJoin.IT. Tu prowadzi
 * zbiorczy mail o rekrutacjach sprzed startu przypomnień („Nadrabiaj po
 * kolei”). Ten sam stan co poranne maile (`GET /api/job-ads/missing`).
 * Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenia-przypomnienia-mailem.md`.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { JobAdWindow } from "@/components/v2/job-ad/JobAdWindow";
import { apiErrorMessage } from "@/lib/api-error";
import {
  AD_CHANNEL_LABEL,
  jobAdApi,
  missingAdsQueryKey,
  type AdChannel,
  type AdChannelView,
  type MissingAdsItem,
} from "@/lib/api/jobAd";
import { cn, formatDate } from "@/lib/utils";

import type { JobAdWindowApi } from "./JobAdWindow";
import { ownersText } from "./AdReminderControls";

export type MissingAdsQueueApi = Pick<typeof jobAdApi, "missing"> & JobAdWindowApi;

// Kolejność jak w mailu: najpierw portale, potem strona kariery.
const FOCUS_ORDER: readonly AdChannel[] = ["jjit", "pracuj", "kariera"];

/** Pierwszy brak, który robi osoba — na nim otwiera się okno. */
export function firstMine(item: MissingAdsItem): AdChannel | null {
  for (const channel of FOCUS_ORDER) {
    const view = item.channels.find((c) => c.channel === channel);
    if (view?.state === "missing" && view.mine) return channel;
  }
  return null;
}

export function channelText(view: AdChannelView): string {
  if (view.state === "live") {
    return view.since ? `Wisi od ${formatDate(view.since)}` : "Wisi";
  }
  if (view.state === "skipped") return `Nie publikujemy: ${view.skip_reason ?? ""}`;
  if (view.mine) return "Brak · robisz Ty";
  const owners = ownersText(view);
  return owners ? `Brak · robi ${owners}` : "Brak";
}

const CHIP: Record<AdChannelView["state"], string> = {
  live: "bg-success-muted text-success-muted-foreground",
  missing: "bg-warning-muted text-warning-muted-foreground",
  skipped: "bg-muted text-muted-foreground",
};

const SHORT: Record<AdChannel, string> = {
  kariera: "Kariera",
  pracuj: "Pracuj",
  jjit: "JJIT",
};

function ChannelChips({ item }: { item: MissingAdsItem }) {
  return (
    <span className="flex flex-wrap gap-1">
      {item.channels.map((view) => (
        <span
          key={view.channel}
          title={`${AD_CHANNEL_LABEL[view.channel]}: ${channelText(view)}`}
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-medium",
            CHIP[view.state],
            view.state === "missing" && view.mine && "ring-1 ring-warning",
          )}
        >
          {view.state === "live" ? "✓ " : view.state === "missing" ? "✗ " : "— "}
          {SHORT[view.channel]}
        </span>
      ))}
    </span>
  );
}

export function MissingAdsQueue({ api = jobAdApi }: { api?: MissingAdsQueueApi }) {
  const queryClient = useQueryClient();
  const [onlyMine, setOnlyMine] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  const [windowOpen, setWindowOpen] = useState(false);

  const query = useQuery({ queryKey: missingAdsQueryKey, queryFn: () => api.missing() });
  const all = useMemo(() => query.data ?? [], [query.data]);
  const mineCount = all.filter((item) => firstMine(item) !== null).length;
  const items = onlyMine ? all.filter((item) => firstMine(item) !== null) : all;
  const current = items.find((item) => item.job_id === selected) ?? items[0] ?? null;

  const nextAfter = (jobId: number): number | null => {
    const index = items.findIndex((item) => item.job_id === jobId);
    const rest = [...items.slice(index + 1), ...items.slice(0, index)];
    return rest[0]?.job_id ?? null;
  };

  return (
    <div className="flex flex-col gap-4" data-testid="missing-ads-queue">
      <div role="group" aria-label="Zakres" className="flex flex-wrap gap-1">
        <Button
          type="button"
          size="sm"
          variant={onlyMine ? "primary" : "outline"}
          aria-pressed={onlyMine}
          onClick={() => {
            setOnlyMine(true);
            setSelected(null);
          }}
        >
          Do zrobienia przeze mnie{query.isSuccess ? ` · ${mineCount}` : ""}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={onlyMine ? "outline" : "primary"}
          aria-pressed={!onlyMine}
          onClick={() => {
            setOnlyMine(false);
            setSelected(null);
          }}
        >
          Także pilnowane{query.isSuccess ? ` · ${all.length}` : ""}
        </Button>
      </div>

      {query.isError ? (
        <div className="flex max-w-md flex-col gap-3">
          <Alert
            variant="error"
            title="Nie udało się wczytać listy"
            description={apiErrorMessage(query.error, "Spróbuj ponownie za chwilę.")}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="self-start"
            onClick={() => void query.refetch()}
          >
            Spróbuj ponownie
          </Button>
        </div>
      ) : !query.isSuccess ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Wczytuję rekrutacje…
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          {onlyMine
            ? "Nic nie czeka na Ciebie — Twoje kanały mają ogłoszenia."
            : "Wszystkie Twoje otwarte rekrutacje mają komplet ogłoszeń."}
        </p>
      ) : (
        <div className="flex min-h-0 flex-col gap-4 md:flex-row">
          <ul
            aria-label="Rekrutacje bez kompletu ogłoszeń"
            className="flex max-h-[calc(100dvh-230px)] w-full flex-none flex-col gap-1.5 overflow-y-auto md:w-[380px]"
          >
            {items.map((item) => {
              const active = item.job_id === current?.job_id;
              return (
                <li key={item.job_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.job_id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-1.5 rounded-lg border px-3 py-2 text-left",
                      active ? "border-primary/40 bg-primary/5" : "border-border bg-card",
                    )}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">{item.title}</span>
                      {item.opened_at ? (
                        <span className="flex-none text-xs text-muted-foreground">
                          {formatDate(item.opened_at)}
                        </span>
                      ) : null}
                    </span>
                    <span className="flex items-center justify-between gap-2">
                      <ChannelChips item={item} />
                      {item.client ? (
                        <span className="truncate text-xs text-muted-foreground">
                          {item.client}
                        </span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          {current ? (
            <section
              aria-label="Kanały rekrutacji"
              className="flex min-w-0 flex-1 flex-col gap-3"
            >
              <article className="flex flex-col gap-3 rounded-lg border border-border bg-card px-5 py-4">
                <div className="flex flex-col gap-0.5">
                  <h2 className="text-lg font-semibold text-foreground">{current.title}</h2>
                  <p className="text-xs text-muted-foreground">
                    {[
                      current.client,
                      current.opened_at ? `otwarta ${formatDate(current.opened_at)}` : null,
                      current.backlog ? "sprzed startu przypomnień" : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <dl className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
                  {current.channels.map((view) => (
                    <div key={view.channel} className="contents">
                      <dt className="text-muted-foreground">{AD_CHANNEL_LABEL[view.channel]}</dt>
                      <dd
                        className={cn(
                          "min-w-0",
                          view.state === "missing"
                            ? "text-warning-muted-foreground"
                            : "text-foreground",
                          view.state === "missing" && view.mine && "font-medium",
                        )}
                      >
                        {channelText(view)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </article>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" onClick={() => setWindowOpen(true)}>
                  {firstMine(current)
                    ? `Otwórz: ${AD_CHANNEL_LABEL[firstMine(current) as AdChannel]}`
                    : "Otwórz ogłoszenie"}
                </Button>
                <Button type="button" variant="outline" asChild>
                  <Link href={`/jobs/${current.job_id}`}>Przejdź do rekrutacji</Link>
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setSelected(nextAfter(current.job_id) ?? current.job_id)}
                >
                  Następna
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Gdy kanał zacznie wisieć albo zapiszesz „nie publikujemy”, rekrutacja zniknie
                z tej listy i z porannych maili.
              </p>
            </section>
          ) : null}
        </div>
      )}

      {windowOpen && current ? (
        <JobAdWindow
          jobId={current.job_id}
          jobTitle={current.title}
          open
          api={api}
          focusChannel={firstMine(current)}
          onClose={() => {
            setWindowOpen(false);
            void queryClient.invalidateQueries({ queryKey: missingAdsQueryKey });
          }}
        />
      ) : null}
    </div>
  );
}
