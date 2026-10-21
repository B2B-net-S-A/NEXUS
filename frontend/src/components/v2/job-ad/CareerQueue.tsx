"use client";

/**
 * „Strona kariery do uzupełnienia” (21.10.2026) — otwarte rekrutacje bez
 * strony kariery, jedna po drugiej: przeczytaj treść, „Opublikuj i następna”.
 *
 * 21.10.2026 203 z 205 otwartych rekrutacji nie miało strony kariery. Treść
 * przygotowuje noc (`tasks/job_ad_prepare.py`), publikuje zawsze człowiek —
 * decyzja Artura: każdą treść ktoś czyta, nic nie wychodzi hurtem.
 * Makiety: https://claude.ai/artifact/1wcS1zr1hc73nFMKSPwm7P (plansza R-2).
 * Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenie-jedna-tresc-strona-kariery.md`.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { JobAdWindow } from "@/components/v2/job-ad/JobAdWindow";
import { apiErrorMessage } from "@/lib/api-error";
import {
  advisoryFindings,
  blockingFindings,
  careerQueueQueryKey,
  isAdChangedError,
  jobAdApi,
  jobAdQueryKey,
  type CareerQueueItem,
  type CareerQueueScope,
} from "@/lib/api/jobAd";
import { cn, formatRelativeTime } from "@/lib/utils";

import { JOBS_LIST_QUERY_ROOT } from "./AdPublications";

export type CareerQueueApi = Pick<
  typeof jobAdApi,
  | "careerQueue"
  | "get"
  | "generate"
  | "save"
  | "markPublished"
  | "markRemoved"
  | "publishCareer"
>;

const MODE_LABEL: Record<string, string> = {
  remote: "zdalnie",
  hybrid: "hybrydowo",
  onsite: "stacjonarnie",
};

function itemMeta(item: CareerQueueItem): string {
  return [
    item.city,
    item.remote_policy ? (MODE_LABEL[item.remote_policy] ?? null) : null,
    item.delivery_lead_name ? `DL ${item.delivery_lead_name}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

const AD_CHIP: Record<CareerQueueItem["ad"], { label: string; className: string }> = {
  ready: { label: "Treść gotowa", className: "bg-info-muted text-info-muted-foreground" },
  template: {
    label: "Treść bez redakcji",
    className: "bg-warning-muted text-warning-muted-foreground",
  },
  missing: { label: "Brak treści", className: "bg-muted text-muted-foreground" },
};

export function CareerQueue({ api = jobAdApi }: { api?: CareerQueueApi }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [scope, setScope] = useState<CareerQueueScope>("mine");
  const [selected, setSelected] = useState<number | null>(null);
  const [published, setPublished] = useState<ReadonlySet<number>>(new Set());
  const [windowOpen, setWindowOpen] = useState(false);

  const queue = useQuery({
    queryKey: careerQueueQueryKey(scope),
    queryFn: () => api.careerQueue(scope),
  });
  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);

  // Head of Recruitment i admin zwykle nie mają „swoich” rekrutacji — pokazuj
  // od razu wszystkie, zamiast pustej listy.
  useEffect(() => {
    if (scope === "mine" && queue.data && queue.data.mine_count === 0 && queue.data.all_count > 0) {
      setScope("all");
    }
  }, [scope, queue.data]);

  // Zaznaczona rekrutacja: wybrana albo pierwsza z listy.
  const current =
    items.find((item) => item.job_id === selected) ??
    (items.length > 0 ? items[0] : null);
  const jobId = current?.job_id ?? null;

  const ad = useQuery({
    queryKey: jobAdQueryKey(jobId ?? 0),
    queryFn: () => api.get(jobId as number),
    enabled: jobId != null,
  });

  const nextAfter = (id: number): number | null => {
    const index = items.findIndex((item) => item.job_id === id);
    const rest = [...items.slice(index + 1), ...items.slice(0, index)];
    return rest.find((item) => !published.has(item.job_id))?.job_id ?? null;
  };

  const refreshQueue = () => {
    void queryClient.invalidateQueries({ queryKey: ["job-ad", "career-queue"] });
    void queryClient.invalidateQueries({ queryKey: [JOBS_LIST_QUERY_ROOT] });
  };

  const publish = useMutation({
    mutationFn: (input: { jobId: number; version: string | null }) =>
      api.publishCareer(input.jobId, input.version),
    onSuccess: (state, input) => {
      queryClient.setQueryData(jobAdQueryKey(input.jobId), state);
      setPublished((prev) => new Set(prev).add(input.jobId));
      setSelected(nextAfter(input.jobId));
      refreshQueue();
      showSuccess("Wisi na stronie kariery. Następna rekrutacja.");
    },
    onError: (err, input) => {
      if (isAdChangedError(err)) {
        void queryClient.invalidateQueries({ queryKey: jobAdQueryKey(input.jobId) });
      }
      showError(apiErrorMessage(err, "Nie udało się opublikować. Spróbuj ponownie."));
    },
  });

  const prepare = useMutation({
    mutationFn: (id: number) => api.generate(id, "pl", null),
    onSuccess: (state, id) => {
      queryClient.setQueryData(jobAdQueryKey(id), state);
      refreshQueue();
    },
    onError: (err, id) => {
      if (isAdChangedError(err)) {
        void queryClient.invalidateQueries({ queryKey: jobAdQueryKey(id) });
      }
      showError(apiErrorMessage(err, "Nie udało się przygotować treści. Spróbuj ponownie."));
    },
  });

  const state = ad.data;
  const content = state?.ad?.content ?? null;
  const blocking = blockingFindings(state?.findings ?? []);
  const advisory = advisoryFindings(state?.findings ?? []);
  const canPublish =
    !!state?.ad && state.can_copy && !publish.isPending && !prepare.isPending;

  return (
    <div className="flex flex-col gap-4" data-testid="career-queue">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Zakres" className="flex gap-1">
          {(["mine", "all"] as const).map((key) => (
            <Button
              key={key}
              type="button"
              size="sm"
              variant={scope === key ? "primary" : "outline"}
              aria-pressed={scope === key}
              onClick={() => {
                setScope(key);
                setSelected(null);
              }}
            >
              {key === "mine" ? "Moje" : "Wszystkie"}
              {queue.data ? ` · ${key === "mine" ? queue.data.mine_count : queue.data.all_count}` : ""}
            </Button>
          ))}
        </div>
        {published.size > 0 ? (
          <span className="rounded-full bg-success-muted px-3 py-1 text-[13px] text-success-muted-foreground">
            Opublikowane teraz: {published.size}
          </span>
        ) : null}
      </div>

      {queue.isError ? (
        <div className="flex max-w-md flex-col gap-3">
          <Alert
            variant="error"
            title="Nie udało się wczytać listy"
            description={apiErrorMessage(queue.error, "Spróbuj ponownie za chwilę.")}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="self-start"
            onClick={() => void queue.refetch()}
          >
            Spróbuj ponownie
          </Button>
        </div>
      ) : !queue.isSuccess ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Wczytuję rekrutacje…
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          {scope === "mine"
            ? "Wszystkie Twoje otwarte rekrutacje mają stronę kariery."
            : "Wszystkie otwarte rekrutacje mają stronę kariery."}
        </p>
      ) : (
        <div className="flex min-h-0 flex-col gap-4 md:flex-row">
          <ul
            aria-label="Rekrutacje bez strony kariery"
            className="flex max-h-[calc(100dvh-220px)] w-full flex-none flex-col gap-1.5 overflow-y-auto md:w-[380px]"
          >
            {items.map((item) => {
              const active = item.job_id === jobId;
              const done = published.has(item.job_id);
              const chip = done
                ? { label: "Wisi", className: "bg-success-muted text-success-muted-foreground" }
                : AD_CHIP[item.ad];
              return (
                <li key={item.job_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.job_id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-1 rounded-lg border px-3 py-2 text-left",
                      active ? "border-primary/40 bg-primary/5" : "border-border bg-card",
                    )}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">{item.title}</span>
                      {item.opened_at ? (
                        <span className="flex-none text-xs text-muted-foreground">
                          {formatRelativeTime(item.opened_at)}
                        </span>
                      ) : null}
                    </span>
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs text-muted-foreground">{itemMeta(item)}</span>
                      <span
                        className={cn(
                          "flex-none rounded-full px-2 py-0.5 text-[11px] font-medium",
                          chip.className,
                        )}
                      >
                        {chip.label}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <section
            aria-label="Treść na stronę kariery"
            className="flex max-h-[calc(100dvh-220px)] min-w-0 flex-1 flex-col gap-3 overflow-y-auto"
          >
            {current == null ? null : ad.isError ? (
              <Alert
                variant="error"
                title="Nie udało się wczytać treści"
                description={apiErrorMessage(ad.error, "Spróbuj ponownie za chwilę.")}
              />
            ) : !ad.isSuccess || !state ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Wczytuję treść…
              </p>
            ) : !content ? (
              <div className="flex flex-col items-start gap-3 rounded-lg border border-border bg-card p-5">
                <h2 className="text-base font-semibold text-foreground">{current.title}</h2>
                <p className="text-sm text-muted-foreground">
                  Ta rekrutacja nie ma jeszcze treści. Ułożę ją z Profilu Championa — bez nazwy
                  klienta i stawek. To może potrwać do minuty.
                </p>
                <Button
                  type="button"
                  loading={prepare.isPending}
                  onClick={() => prepare.mutate(current.job_id)}
                >
                  Przygotuj treść
                </Button>
              </div>
            ) : (
              <>
                {published.has(current.job_id) ? (
                  <p
                    role="status"
                    className="rounded-md bg-success-muted px-3 py-2 text-[13px] text-success-muted-foreground"
                  >
                    Wisi na stronie kariery.
                  </p>
                ) : null}
                {blocking.length > 0 ? (
                  <div
                    role="alert"
                    className="flex flex-col gap-1 rounded-md border border-destructive/20 bg-destructive-muted px-3 py-2 text-[13px] text-destructive-muted-foreground"
                  >
                    <strong className="font-semibold">
                      Przed publikacją popraw treść („Popraw treść”):
                    </strong>
                    <ul className="list-disc pl-5">
                      {blocking.map((finding, index) => (
                        <li key={`${finding.code}-${index}`}>{finding.message}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {state.ad?.source === "template" ? (
                  <p className="rounded-md bg-info-muted px-3 py-2 text-[13px] text-info-muted-foreground">
                    Treść złożona z pól rekrutacji bez redakcji — przeczytaj ją uważniej albo popraw.
                  </p>
                ) : null}

                <article className="flex flex-col gap-3 rounded-lg border border-border bg-card px-5 py-4">
                  <div className="flex flex-col gap-1">
                    <h2 className="text-lg font-semibold text-foreground">
                      {state.rendered?.title ?? current.title}
                    </h2>
                    {itemMeta(current) ? (
                      <p className="text-xs text-muted-foreground">{itemMeta(current)}</p>
                    ) : null}
                  </div>
                  {content.lead ? <p className="text-sm text-foreground">{content.lead}</p> : null}
                  {content.about ? (
                    <div className="flex flex-col gap-1">
                      <h3 className="text-[13px] font-semibold text-foreground">O projekcie</h3>
                      {content.about.split(/\n\s*\n/).map((paragraph, index) => (
                        <p key={index} className="text-sm leading-relaxed text-foreground">
                          {paragraph}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  {content.responsibilities.length > 0 ? (
                    <div className="flex flex-col gap-1">
                      <h3 className="text-[13px] font-semibold text-foreground">Czym się zajmiesz</h3>
                      <ul className="list-disc pl-5 text-sm leading-relaxed text-foreground">
                        {content.responsibilities.map((item, index) => (
                          <li key={index}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {content.requirements.length > 0 ? (
                    <div className="flex flex-col gap-1">
                      <h3 className="text-[13px] font-semibold text-foreground">Wymagania</h3>
                      <ul className="list-disc pl-5 text-sm leading-relaxed text-foreground">
                        {content.requirements.map((item, index) => (
                          <li key={index}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </article>

                {advisory.length > 0 ? (
                  <p className="text-xs text-warning-muted-foreground">
                    Warto poprawić: {advisory.map((finding) => finding.message).join(" ")}
                  </p>
                ) : null}

                {/* Przyklejone do dołu panelu: na laptopie 720 px treść jest dłuższa
                    niż ekran, a „Opublikuj i następna” musi być pod ręką. */}
                <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-border bg-background py-2">
                  {!published.has(current.job_id) ? (
                    <Button
                      type="button"
                      loading={publish.isPending}
                      disabled={!canPublish}
                      title={
                        blocking.length > 0
                          ? "Najpierw usuń z treści fragmenty wskazane wyżej."
                          : undefined
                      }
                      onClick={() =>
                        publish.mutate({
                          jobId: current.job_id,
                          version: state.ad?.updated_at ?? null,
                        })
                      }
                    >
                      Opublikuj i następna
                    </Button>
                  ) : null}
                  <Button type="button" variant="outline" onClick={() => setWindowOpen(true)}>
                    Popraw treść
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setSelected(nextAfter(current.job_id) ?? current.job_id)}
                  >
                    Pomiń
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Na stronę idzie wstęp, opis projektu i obowiązki. Wymagania, miasto i tryb pracy
                  strona bierze z rekrutacji. Nazwy klienta i stawek tam nie ma.
                </p>
              </>
            )}
          </section>
        </div>
      )}

      {windowOpen && current ? (
        <JobAdWindow
          jobId={current.job_id}
          jobTitle={current.title}
          open
          api={api}
          onClose={() => {
            setWindowOpen(false);
            void queryClient.invalidateQueries({ queryKey: jobAdQueryKey(current.job_id) });
            refreshQueue();
          }}
        />
      ) : null}
    </div>
  );
}
