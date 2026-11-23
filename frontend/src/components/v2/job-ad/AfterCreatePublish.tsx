"use client";

/**
 * Krok „Ogłoszenie” zaraz po utworzeniu rekrutacji (wariant 1 „Porządki”,
 * 23.11.2026, makiety https://claude.ai/artifact/5CT33qwDPP5vurc1CVY7yV).
 *
 * Pomiar z kopii produkcji: publikacja na portalu miała medianę 23 h po
 * utworzeniu rekrutacji, a stawkę do maila Pracuj.pl DL wpisywał drugi raz.
 * Tu: kanały zaznaczone jak w ostatnich rekrutacjach klienta
 * (`recent_channels`), widełki dla kandydata wpisane RAZ (JustJoin.IT i mail
 * do opiekuna Pracuj.pl) i jedno „Opublikuj w N miejscach”. Widełki wpisuje
 * człowiek — nigdy z budżetu klienta; bez nich JustJoin.IT pyta o powód
 * (`useConfirmV2().askReason`, `lib/postingSalaryGuard.ts`).
 *
 * Panel nie ma własnej ścieżki zapisu: woła te same trasy co karty kanałów
 * (`publishCareer`, `publishJjit`, `sendPracujMail`). Czego nie da się
 * zrobić jednym kliknięciem (brak kategorii JustJoin.IT, brak stawki albo
 * skrzynki dla Pracuj.pl), kończy okno kanału z wpisanymi widełkami.
 * Reguła: `docs/claude/rekrutacja-tworzenie/ogloszenie-przy-utworzeniu.md`.
 */

import { useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Globe, Loader2, Mail, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobAdApi,
  jobAdQueryKey,
  missingAdsQueryKey,
  type AdChannel,
  type JobAdState,
} from "@/lib/api/jobAd";
import {
  fetchListingDefaults,
  listingProblemsFromError,
  validateListingOptions,
  type PortalListingOptions,
  type PortalSalary,
} from "@/lib/api/jobPortals";
import { newClientRequestId } from "@/lib/client-request-id";
import { NEXUS_AD_CONTRACT_FORM, noSalaryReasonRequest } from "@/lib/postingSalaryGuard";
import { cn } from "@/lib/utils";

import { JOBS_LIST_QUERY_ROOT } from "./AdPublications";
import { JjitPublishDialog } from "./JjitPublishDialog";
import { PracujMailDialog } from "./PracujMailDialog";

export type AfterCreateApi = Pick<
  typeof jobAdApi,
  "publishCareer" | "publishJjit" | "sendPracujMail" | "previewPracujMail" | "save"
>;

export interface ChannelRow {
  channel: AdChannel;
  label: string;
  hint: string;
  via: string;
  /** Powód, dla którego kanału nie da się teraz zaznaczyć; `null` = można. */
  unavailable: string | null;
}

const ORDER: readonly AdChannel[] = ["kariera", "jjit", "pracuj"];

/** Kanały kroku i to, czy da się je teraz opublikować. */
export function channelRows(
  state: JobAdState,
  { publishBlockedReason }: { publishBlockedReason: string | null },
): ChannelRow[] {
  const canManage = state.reminders?.can_manage === true;
  const notOpen = state.reminders == null ? "Rekrutacja jest zamknięta." : null;
  const managerOnly = "Publikuje Delivery Lead rekrutacji.";
  const jjitLive =
    state.publications.some((p) => p.portal === "jjit" && !p.removed_at) ||
    ["publishing", "published"].includes(state.jjit_api?.status ?? "");
  const pracujLive = state.publications.some((p) => p.portal === "pracuj" && !p.removed_at);
  const careerRequired = state.jjit_api?.career_required !== false;
  const rows: Record<AdChannel, ChannelRow> = {
    kariera: {
      channel: "kariera",
      label: "Strona kariery",
      hint: "kariera.b2bnetwork.pl",
      via: "od razu",
      unavailable:
        notOpen ??
        (state.career.status !== "none" ? "Już wisi na stronie kariery." : publishBlockedReason),
    },
    jjit: {
      channel: "jjit",
      label: "JustJoin.IT",
      hint: careerRequired
        ? "kandydat aplikuje przez stronę kariery"
        : "formularz JustJoin.IT",
      via: "przez API",
      unavailable:
        notOpen ??
        (!state.jjit_api?.ready
          ? "Publikacja przez API jest wyłączona — wklej z zakładki JustJoin.IT."
          : !canManage
            ? managerOnly
            : jjitLive
              ? "Już wisi na JustJoin.IT."
              : publishBlockedReason),
    },
    pracuj: {
      channel: "pracuj",
      label: "Pracuj.pl",
      hint: "wstawia opiekun konta",
      via: "mail do opiekuna",
      unavailable:
        notOpen ??
        (!canManage
          ? managerOnly
          : pracujLive
            ? "Już wisi na Pracuj.pl."
            : state.pracuj_request?.waiting
              ? "Mail do opiekuna już wyszedł."
              : publishBlockedReason),
    },
  };
  return ORDER.map((channel) => rows[channel]);
}

/** Zaznaczenie startowe: kanały z ostatnich rekrutacji klienta, które da się opublikować. */
export function initialSelection(rows: readonly ChannelRow[], state: JobAdState): AdChannel[] {
  const recent = state.recent_channels?.channels ?? ORDER;
  return rows.filter((r) => r.unavailable == null && recent.includes(r.channel)).map((r) => r.channel);
}

export interface SalaryInput {
  salary: PortalSalary | null;
  error: string | null;
}

/** Widełki B2B zł/h z dwóch pól; jedna granica = stała stawka. */
export function parseSalary(fromText: string, toText: string): SalaryInput {
  const read = (text: string) => {
    const digits = text.replace(/\D/g, "");
    return digits ? Number(digits) : null;
  };
  const from = read(fromText);
  const to = read(toText);
  if (from == null && to == null) return { salary: null, error: null };
  const low = from ?? to!;
  const high = to ?? from!;
  if (!(low > 0)) return { salary: null, error: "Kwota „od” musi być większa od zera." };
  if (high < low) return { salary: null, error: "Kwota „do” nie może być niższa niż „od”." };
  if (high > low * 3)
    return { salary: null, error: "Kwota „do” może być najwyżej trzy razy wyższa niż „od”." };
  return { salary: { from: low, to: high, unit: "hour" }, error: null };
}

export type Outcome =
  | { status: "done" }
  | { status: "finish"; message: string }
  | { status: "error"; message: string };

export interface PublishInput {
  jobId: number;
  state: JobAdState;
  selected: readonly AdChannel[];
  salary: PortalSalary | null;
  /** Powód publikacji JustJoin.IT bez widełek (pytanie zadaje panel). */
  noSalaryReason: string | null;
  api: Pick<AfterCreateApi, "publishCareer" | "publishJjit" | "sendPracujMail">;
  listingDefaults: (jobId: number) => Promise<PortalListingOptions>;
  requestId: string;
}

function status(err: unknown): number | undefined {
  return (err as { response?: { status?: number } } | null)?.response?.status;
}

/**
 * Publikacja po kolei: strona kariery (JustJoin.IT w trybie linku jej
 * potrzebuje), JustJoin.IT przez API, mail do opiekuna Pracuj.pl. Każdy kanał
 * osobno — odmowa jednego nie zatrzymuje pozostałych.
 */
export async function publishAfterCreate(
  input: PublishInput,
): Promise<{ state: JobAdState; outcomes: Partial<Record<AdChannel, Outcome>> }> {
  const { jobId, selected, salary, api } = input;
  let state = input.state;
  const outcomes: Partial<Record<AdChannel, Outcome>> = {};
  const version = () => state.ad?.updated_at ?? null;

  if (selected.includes("kariera")) {
    try {
      state = await api.publishCareer(jobId, version());
      outcomes.kariera = { status: "done" };
    } catch (err) {
      outcomes.kariera = {
        status: "error",
        message: apiErrorMessage(err, "Nie udało się opublikować na stronie kariery."),
      };
    }
  }

  if (selected.includes("jjit")) {
    const careerLive = state.career.status === "live";
    if (state.jjit_api?.career_required !== false && !careerLive) {
      outcomes.jjit = {
        status: "error",
        message: "Najpierw strona kariery — kandydaci z JustJoin.IT aplikują przez nią.",
      };
    } else {
      try {
        const defaults = await input.listingDefaults(jobId);
        const options: PortalListingOptions = {
          ...defaults,
          category: state.recent_channels?.jjit_category ?? defaults.category,
          salary,
          no_salary_reason: salary ? null : input.noSalaryReason,
        };
        if (validateListingOptions(options, { board: "justjoinit" }).length > 0) {
          outcomes.jjit = { status: "finish", message: "Wybierz kategorię i sprawdź ustawienia." };
        } else {
          state = await api.publishJjit(jobId, { expected_updated_at: version(), options });
          outcomes.jjit = { status: "done" };
        }
      } catch (err) {
        outcomes.jjit = listingProblemsFromError(err)
          ? { status: "finish", message: "Portal chce poprawek w ustawieniach." }
          : {
              status: "error",
              message: apiErrorMessage(err, "Nie udało się wysłać na JustJoin.IT."),
            };
      }
    }
  }

  if (selected.includes("pracuj")) {
    if (!salary) {
      outcomes.pracuj = { status: "finish", message: "Mail do opiekuna wymaga stawki — wpisz ją w oknie maila." };
    } else {
      try {
        state = await api.sendPracujMail(jobId, {
          rate_from: salary.from,
          rate_to: salary.to,
          expected_updated_at: version(),
          client_request_id: input.requestId,
        });
        outcomes.pracuj = { status: "done" };
      } catch (err) {
        const message = apiErrorMessage(err, "Nie udało się wysłać maila do opiekuna Pracuj.pl.");
        // 412: brak podłączonej skrzynki — okno maila daje „Kopiuj treść maila”.
        outcomes.pracuj =
          status(err) === 412 ? { status: "finish", message } : { status: "error", message };
      }
    }
  }
  return { state, outcomes };
}

const ICONS: Record<AdChannel, typeof Globe> = { kariera: Globe, jjit: Send, pracuj: Mail };

export interface AfterCreatePublishProps {
  jobId: number;
  state: JobAdState;
  /** Treść jeszcze się pisze albo czeka na zapis — publikować nie wolno. */
  waitingReason: string | null;
  publishBlockedReason: string | null;
  onLater: () => void;
  /** Przejście do zwykłej kolumny kanałów (szczegóły, oznaczenia). */
  onShowChannels: () => void;
  onStateChange: (next: JobAdState) => void;
  /** Kontrola przed publikacją (`AdChecksPanel`) — nad kanałami, gdy są uwagi. */
  checks?: ReactNode;
  api?: AfterCreateApi;
  listingDefaults?: (jobId: number) => Promise<PortalListingOptions>;
}

export function AfterCreatePublish({
  jobId,
  state,
  waitingReason,
  publishBlockedReason,
  onLater,
  onShowChannels,
  onStateChange,
  checks = null,
  api = jobAdApi,
  listingDefaults = fetchListingDefaults,
}: AfterCreatePublishProps) {
  const queryClient = useQueryClient();
  const { askReason, confirmDialog } = useConfirmV2();
  const rows = useMemo(
    () => channelRows(state, { publishBlockedReason }),
    [state, publishBlockedReason],
  );
  const [selected, setSelected] = useState<AdChannel[] | null>(null);
  const chosen = selected ?? initialSelection(rows, state);
  const [fromText, setFromText] = useState("");
  const [toText, setToText] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcomes, setOutcomes] = useState<Partial<Record<AdChannel, Outcome>> | null>(null);
  const [dialog, setDialog] = useState<"jjit" | "pracuj" | null>(null);
  const requestId = useRef(newClientRequestId());

  const { salary, error: salaryError } = parseSalary(fromText, toText);
  const needsSalary = chosen.some((c) => c === "jjit" || c === "pracuj");
  const careerForced =
    chosen.includes("jjit") &&
    state.jjit_api?.career_required !== false &&
    state.career.status !== "live";
  const toPublish = careerForced && !chosen.includes("kariera") ? [...chosen, "kariera" as const] : chosen;
  const count = toPublish.length;
  const historyNote =
    state.recent_channels && state.recent_channels.jobs > 0
      ? `Zaznaczone jak w ${state.recent_channels.jobs} ostatnich rekrutacjach tego klienta.`
      : "Ten klient nie ma jeszcze ogłoszeń — zaznaczone wszystkie kanały.";

  const toggle = (channel: AdChannel, on: boolean) =>
    setSelected((prev) => {
      const base = prev ?? chosen;
      return on ? [...base, channel] : base.filter((c) => c !== channel);
    });

  const start = async () => {
    if (salaryError) return;
    let reason: string | null = null;
    if (toPublish.includes("jjit") && !salary) {
      reason = await askReason(noSalaryReasonRequest(NEXUS_AD_CONTRACT_FORM));
      if (!reason) return;
    }
    setBusy(true);
    const result = await publishAfterCreate({
      jobId,
      state,
      selected: toPublish,
      salary,
      noSalaryReason: reason,
      api,
      listingDefaults,
      requestId: requestId.current,
    });
    setBusy(false);
    setOutcomes(result.outcomes);
    onStateChange(result.state);
    queryClient.setQueryData(jobAdQueryKey(jobId), result.state);
    void queryClient.invalidateQueries({ queryKey: [JOBS_LIST_QUERY_ROOT] });
    void queryClient.invalidateQueries({ queryKey: missingAdsQueryKey });
  };

  const finished = (channel: "jjit" | "pracuj", next: JobAdState) => {
    onStateChange(next);
    queryClient.setQueryData(jobAdQueryKey(jobId), next);
    setOutcomes((prev) => ({ ...prev, [channel]: { status: "done" } }));
    setDialog(null);
  };

  return (
    <aside
      aria-label="Gdzie publikujemy"
      data-testid="after-create-publish"
      className="flex w-[340px] flex-none flex-col gap-3 overflow-y-auto border-l border-border bg-card px-4 py-3"
    >
      {checks}
      <div className="flex flex-col gap-0.5">
        <h2 className="text-sm font-semibold text-foreground">Gdzie publikujemy</h2>
        <p className="text-xs text-muted-foreground">{historyNote}</p>
      </div>

      <ul className="flex flex-col gap-2">
        {rows.map((row) => {
          const Icon = ICONS[row.channel];
          const forced = row.channel === "kariera" && careerForced && row.unavailable == null;
          const checked = toPublish.includes(row.channel);
          const outcome = outcomes?.[row.channel];
          return (
            <li key={row.channel}>
              <label
                className={cn(
                  "flex items-start gap-2.5 rounded-md border px-3 py-2 text-sm",
                  checked && !outcome ? "border-primary/50 bg-primary/5" : "border-border",
                  row.unavailable != null ? "cursor-default opacity-70" : "cursor-pointer",
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 accent-[var(--primary)]"
                  checked={checked}
                  disabled={row.unavailable != null || forced || busy || outcomes != null}
                  data-testid={`after-create-${row.channel}`}
                  onChange={(e) => toggle(row.channel, e.target.checked)}
                />
                <Icon className="mt-0.5 h-4 w-4 flex-none text-muted-foreground" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-medium text-foreground">{row.label}</span>
                    <span className="text-[11px] text-muted-foreground">{row.via}</span>
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {row.unavailable ??
                      (forced ? "Potrzebna, żeby kandydaci z JustJoin.IT mieli gdzie aplikować." : row.hint)}
                  </span>
                  {outcome ? <OutcomeLine outcome={outcome} /> : null}
                  {outcome?.status === "finish" && (row.channel === "jjit" || row.channel === "pracuj") ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="mt-1.5 h-7 px-2.5"
                      data-testid={`after-create-finish-${row.channel}`}
                      onClick={(e) => {
                        e.preventDefault();
                        setDialog(row.channel as "jjit" | "pracuj");
                      }}
                    >
                      Dokończ
                    </Button>
                  ) : null}
                </span>
              </label>
            </li>
          );
        })}
      </ul>

      {needsSalary && outcomes == null ? (
        <section
          aria-label="Widełki dla kandydata"
          className="flex flex-col gap-1.5 rounded-md border border-border px-3 py-2.5"
        >
          <h3 className="text-[13px] font-medium text-foreground">
            Widełki dla kandydata (B2B, zł/h netto)
          </h3>
          <div className="flex items-center gap-2">
            <Input
              aria-label="Widełki od"
              inputMode="numeric"
              placeholder="od"
              value={fromText}
              disabled={busy}
              data-testid="after-create-salary-from"
              onChange={(e) => setFromText(e.target.value.replace(/\D/g, "").slice(0, 4))}
              className="h-8"
            />
            <span className="text-muted-foreground">–</span>
            <Input
              aria-label="Widełki do"
              inputMode="numeric"
              placeholder="do"
              value={toText}
              disabled={busy}
              data-testid="after-create-salary-to"
              onChange={(e) => setToText(e.target.value.replace(/\D/g, "").slice(0, 4))}
              className="h-8"
            />
          </div>
          {salaryError ? (
            <p role="alert" className="text-xs text-destructive">
              {salaryError}
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Wpisujesz raz — idą do JustJoin.IT i do maila Pracuj.pl. Nie z budżetu klienta.
          </p>
        </section>
      ) : null}

      {outcomes == null ? (
        <div className="flex flex-col gap-2">
          {waitingReason ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              {waitingReason}
            </p>
          ) : null}
          <Button
            type="button"
            loading={busy}
            disabled={count === 0 || !!waitingReason || !!salaryError}
            data-testid="after-create-publish-start"
            onClick={() => void start()}
          >
            {count === 0
              ? "Zaznacz kanał"
              : count === 1
                ? "Opublikuj w 1 miejscu"
                : `Opublikuj w ${count} miejscach`}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={busy}
            data-testid="after-create-later"
            onClick={onLater}
          >
            Później (przypomnimy rano)
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <Button type="button" variant="outline" onClick={onShowChannels}>
            Pokaż wszystkie kanały
          </Button>
          <Button type="button" variant="ghost" onClick={onLater}>
            Zamknij
          </Button>
        </div>
      )}

      <JjitPublishDialog
        open={dialog === "jjit"}
        jobId={jobId}
        state={state}
        api={api}
        prefill={{
          salary,
          ...(state.recent_channels?.jjit_category
            ? { category: state.recent_channels.jjit_category }
            : {}),
        }}
        onClose={() => setDialog(null)}
        onPublished={(next) => finished("jjit", next)}
      />
      <PracujMailDialog
        open={dialog === "pracuj"}
        jobId={jobId}
        state={state}
        api={api}
        initialRates={salary ? { rate_from: salary.from, rate_to: salary.to } : null}
        onClose={() => setDialog(null)}
        onSent={(next) => finished("pracuj", next)}
        onSaved={onStateChange}
      />
      {confirmDialog}
    </aside>
  );
}

function OutcomeLine({ outcome }: { outcome: Outcome }) {
  if (outcome.status === "done") {
    return (
      <span className="mt-1 flex items-center gap-1 text-xs font-medium text-success-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
        Zrobione
      </span>
    );
  }
  return (
    <span
      role={outcome.status === "error" ? "alert" : "status"}
      className={cn(
        "mt-1 flex items-start gap-1 text-xs",
        outcome.status === "error" ? "text-destructive" : "text-warning-muted-foreground",
      )}
    >
      <CircleAlert className="mt-px h-3.5 w-3.5 flex-none" aria-hidden="true" />
      {outcome.message}
    </span>
  );
}
