"use client";

/**
 * Ekran zespołu po naszej stronie (`/zespoly/{id}`,
 * `docs/claude/klienci/zespol-dla-klienta.md`). Zespół to kontener nad
 * zwykłymi rekrutacjami: każde stanowisko ma własnego Championa i Tablicę, tu
 * widać całość — obsadę, alternatywy, cenę dla klienta, marżę i link dla
 * klienta. Marża i stawki kandydatów nie wychodzą z NEXUSA.
 */

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Copy, ExternalLink, Link2, Plus, RefreshCw, X } from "lucide-react";

import { PageHeader } from "@/components/ds/PageHeader";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  fetchTeam,
  jobTeamKeys,
  rotateTeamLink,
  updateTeam,
  updateTeamPanel,
  type TeamCandidate,
  type TeamDetail,
} from "@/lib/api/jobTeams";
import { formatPanelDate } from "@/components/v2/client-panel/panel-logic";
import { cn } from "@/lib/utils";

import { TeamVariantsCard } from "./TeamVariantsCard";
import {
  DEFAULT_HOURS_PER_MONTH,
  formatHourly,
  formatPln,
  formatThousands,
  hourlyValue,
  peopleLabel,
  positionsLabel,
  teamHourlyRange,
  type SeatGroup,
} from "./team-logic";

const CARD = "rounded-xl border border-border bg-card";
/** Stanowisko jest gotowe do pokazania, gdy ma co najmniej tyle alternatyw na miejsce. */
const MIN_ALTERNATIVES = 2;

const clientRate = (c: TeamCandidate) => hourlyValue(c.client_rate);

function marginOf(c: TeamCandidate): number | null {
  const rate = hourlyValue(c.client_rate);
  const expected = hourlyValue(c.expected_rate);
  return rate != null && expected != null ? rate - expected : null;
}

function groupsOf(team: TeamDetail): SeatGroup<TeamCandidate>[] {
  return team.positions
    .filter((p) => !p.closed)
    .map((p) => ({ key: String(p.job_id), headcount: Math.max(1, p.headcount), candidates: p.candidates }));
}

function Stat({
  label,
  value,
  sub,
  warn,
}: {
  label: string;
  value: string;
  sub?: string;
  warn?: boolean;
}) {
  return (
    <div className={cn(CARD, "min-w-0 px-3.5 py-2.5")}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-display text-lg font-bold tabular-nums">{value}</div>
      {sub ? (
        <div className={cn("text-xs", warn ? "text-warning-muted-foreground" : "text-muted-foreground")}>{sub}</div>
      ) : null}
    </div>
  );
}

function PanelCard({ team }: { team: TeamDetail }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const openPositions = team.positions.filter((p) => !p.closed).length;
  const onDone = (next: TeamDetail) => queryClient.setQueryData(jobTeamKeys.detail(team.id), next);
  const onFail = (error: unknown) =>
    showError(apiErrorMessage(error, "Nie udało się zmienić linku zespołu. Spróbuj ponownie."));
  const toggle = useMutation({
    mutationFn: (body: { enabled?: boolean; show_rate?: boolean }) => updateTeamPanel(team.id, body),
    onSuccess: onDone,
    onError: onFail,
  });
  const rotate = useMutation({
    mutationFn: () => rotateTeamLink(team.id),
    onSuccess: (next) => {
      onDone(next);
      showSuccess("Nowy link gotowy, stary przestał działać");
    },
    onError: onFail,
  });

  const enable = async () => {
    const yes = await askConfirm({
      title: "Włączyć link zespołu?",
      description: `Klient zobaczy ${positionsLabel(openPositions)} i osoby z „CV wysłane” na każdym z nich. Włączą się też panele tych stanowisk, bo przez nie klient ogląda dowody z CV i prosi o rozmowy. Nic nie wysyła się samo: link przekazujesz Ty.`,
      confirmLabel: "Włącz link",
    });
    if (yes) toggle.mutate({ enabled: true });
  };
  const disable = async () => {
    const yes = await askConfirm({
      title: "Wyłączyć link zespołu?",
      description: "Link zespołu i panele jego stanowisk przestaną działać, także w CV, które klient już ma.",
      confirmLabel: "Wyłącz link",
      variant: "destructive",
    });
    if (yes) toggle.mutate({ enabled: false });
  };
  const askRotate = async () => {
    const yes = await askConfirm({
      title: "Odwołać link zespołu?",
      description: "Obecny link zespołu i linki jego stanowisk przestaną działać. Nowy przekażesz klientowi sam.",
      confirmLabel: "Odwołaj link",
      variant: "destructive",
    });
    if (yes) rotate.mutate();
  };
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      showSuccess("Link skopiowany");
    } catch {
      showError("Nie udało się skopiować linku. Zaznacz go i skopiuj ręcznie.");
    }
  };
  const busy = toggle.isPending || rotate.isPending;

  return (
    <div className={cn(CARD, "grid min-w-0 gap-2 px-3.5 py-3")} data-testid="team-panel-card">
      {confirmDialog}
      <h2 className="font-display text-sm font-semibold">Link dla klienta</h2>
      {team.panel.enabled && team.panel.url ? (
        <>
          <div className="flex min-w-0 items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md bg-muted px-2 py-1 text-xs">{team.panel.short_url}</code>
            <Button size="sm" variant="outline" onClick={() => void copy(team.panel.url!)}>
              <Copy className="h-3.5 w-3.5" />
              Kopiuj
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {team.panel.expires_at ? `Ważny do ${formatPanelDate(team.panel.expires_at)}. ` : ""}
            Jeden link na cały zespół; klient wybiera skład i widzi cenę zespołu.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-primary"
              checked={team.panel.show_rate}
              disabled={busy}
              onChange={(e) => toggle.mutate({ show_rate: e.target.checked })}
            />
            Pokazuj stawki i cenę zespołu
          </label>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild>
              <a href={team.panel.url} target="_blank" rel="noreferrer">
                <ExternalLink className="h-3.5 w-3.5" />
                Otwórz jak klient
              </a>
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void askRotate()}>
              <RefreshCw className="h-3.5 w-3.5" />
              Odwołaj link
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void disable()}>
              Wyłącz
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            Link jest wyłączony. Po włączeniu klient dostaje jedną stronę z całym zespołem zamiast
            osobnych linków do stanowisk.
          </p>
          <div>
            <Button size="sm" disabled={busy || openPositions === 0} onClick={() => void enable()}>
              <Link2 className="h-3.5 w-3.5" />
              Włącz link zespołu
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function SelectionsCard({ team }: { team: TeamDetail }) {
  const titles = new Map(team.positions.map((p) => [p.job_id, p.title]));
  return (
    <div className={cn(CARD, "grid min-w-0 gap-2 px-3.5 py-3")}>
      <h2 className="font-display text-sm font-semibold">Składy od klienta</h2>
      {team.selections.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Klient nie przysłał jeszcze składu. Gdy to zrobi, dostaniesz dzwonek.
        </p>
      ) : (
        team.selections.map((selection) => (
          <div key={selection.id} className="grid gap-1 rounded-lg border border-border px-3 py-2 text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">{selection.author_name}</span>
              <span className="text-xs text-muted-foreground">{formatPanelDate(selection.created_at)}</span>
            </div>
            <span className="truncate text-xs text-muted-foreground">{selection.author_email}</span>
            <ul className="grid gap-0.5">
              {selection.picks.map((pick) => (
                <li key={pick.job_id} className="min-w-0 truncate">
                  <span className="text-muted-foreground">{titles.get(pick.job_id) ?? `#${pick.job_id}`}: </span>
                  {pick.candidates.map((c) => c.name).join(", ")}
                </li>
              ))}
            </ul>
            {selection.note ? <p className="whitespace-pre-wrap text-xs">{selection.note}</p> : null}
          </div>
        ))
      )}
    </div>
  );
}

function AddPosition({ team }: { team: TeamDetail }) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [value, setValue] = useState("");
  const add = useMutation({
    mutationFn: (jobId: number) => updateTeam(team.id, { add_job_ids: [jobId] }),
    onSuccess: (next) => {
      queryClient.setQueryData(jobTeamKeys.detail(team.id), next);
      setValue("");
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać rekrutacji do zespołu.")),
  });
  const jobId = Number(value.replace(/^#/, "").trim());
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (Number.isInteger(jobId) && jobId > 0) add.mutate(jobId);
      }}
    >
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="numer rekrutacji, np. 123456"
        className="h-8 w-56"
        aria-label="Numer rekrutacji do dodania"
      />
      <Button size="sm" variant="outline" type="submit" disabled={add.isPending || !(jobId > 0)}>
        <Plus className="h-3.5 w-3.5" />
        Dodaj stanowisko
      </Button>
      <Button size="sm" variant="ghost" asChild>
        <Link href={`/jobs/new?client=${team.client_id}&team=${team.id}`}>Nowa rekrutacja w zespole</Link>
      </Button>
    </form>
  );
}

function PositionsTable({ team }: { team: TeamDetail }) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const remove = useMutation({
    mutationFn: (jobId: number) => updateTeam(team.id, { remove_job_ids: [jobId] }),
    onSuccess: (next) => queryClient.setQueryData(jobTeamKeys.detail(team.id), next),
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zdjąć stanowiska.")),
  });
  const askRemove = async (jobId: number, title: string) => {
    const yes = await askConfirm({
      title: "Zdjąć stanowisko z zespołu?",
      description: `Rekrutacja „${title}” zostaje bez zmian, tylko przestaje należeć do zespołu i znika z linku zespołu.`,
      confirmLabel: "Zdejmij",
    });
    if (yes) remove.mutate(jobId);
  };

  return (
    <div className={cn(CARD, "min-w-0 overflow-x-auto")}>
      {confirmDialog}
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Stanowisko</th>
            <th className="px-2 py-2 text-center font-medium">Miejsca</th>
            <th className="px-2 py-2 text-center font-medium">Wysłani</th>
            <th className="px-2 py-2 text-right font-medium">Do klienta</th>
            <th className="px-2 py-2 text-right font-medium">Budżet kandydata</th>
            <th className="px-2 py-2 text-right font-medium">Śr. marża</th>
            <th className="px-3 py-2 text-left font-medium">Delivery Lead</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {team.positions.map((position) => {
            const rates = position.candidates.map(clientRate).filter((r): r is number => r != null);
            const margins = position.candidates.map(marginOf).filter((m): m is number => m != null);
            const avg = margins.length ? margins.reduce((a, b) => a + b, 0) / margins.length : null;
            const seats = Math.max(1, position.headcount);
            const enough = position.candidates.length >= MIN_ALTERNATIVES * seats;
            const min = rates.length ? Math.min(...rates) : null;
            const max = rates.length ? Math.max(...rates) : null;
            return (
              <tr
                key={position.job_id}
                className={cn("border-b border-border align-top last:border-b-0", position.closed && "text-muted-foreground")}
              >
                <td className="px-3 py-2">
                  <Link href={`/jobs/${position.job_id}`} className="font-medium underline-offset-2 hover:underline">
                    {position.title}
                  </Link>
                  <div className="text-xs text-muted-foreground">
                    #{position.job_id}
                    {position.closed ? " · zamknięta, klient jej nie widzi" : ""}
                  </div>
                </td>
                <td className="px-2 py-2 text-center tabular-nums">{seats}</td>
                <td className="px-2 py-2 text-center tabular-nums">
                  <span className={cn(!enough && !position.closed && "text-warning-muted-foreground")}>
                    {position.candidates.length}
                  </span>
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">
                  {min == null ? "—" : min === max ? formatHourly(min) : `${formatHourly(min)}–${formatHourly(max!)}`}
                  {position.rate_hint ? (
                    <div
                      className="text-[11px] text-muted-foreground"
                      title={`Stawki do klienta u tego klienta w tej kategorii, 365 dni, ${position.rate_hint.count} par`}
                    >
                      historia: {Math.round(position.rate_hint.p25)}–{Math.round(position.rate_hint.p75)} zł/h
                    </div>
                  ) : null}
                  {rates.length < position.candidates.length ? (
                    <div className="text-[11px] text-warning-muted-foreground">
                      bez stawki: {position.candidates.length - rates.length}
                    </div>
                  ) : null}
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums text-muted-foreground">
                  {position.budget_max != null
                    ? position.budget_min != null
                      ? `${position.budget_min}–${position.budget_max} zł/h`
                      : `do ${position.budget_max} zł/h`
                    : "brak"}
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">
                  {avg != null ? formatHourly(avg) : <span className="text-muted-foreground">—</span>}
                  <div className="text-[11px] text-muted-foreground">
                    z {margins.length}/{position.candidates.length}
                  </div>
                </td>
                <td className="px-3 py-2 text-xs">{position.delivery_lead?.name ?? "—"}</td>
                <td className="px-1 py-2">
                  <button
                    type="button"
                    aria-label={`Zdejmij z zespołu: ${position.title}`}
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => void askRemove(position.job_id, position.title)}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="border-t border-border px-3 py-2">
        <AddPosition team={team} />
      </div>
    </div>
  );
}

export function TeamBoard({ teamId }: { teamId: number }) {
  const query = useQuery({ queryKey: jobTeamKeys.detail(teamId), queryFn: () => fetchTeam(teamId) });

  if (query.isPending) {
    return <div className="p-6 text-sm text-muted-foreground" role="status">Wczytuję zespół…</div>;
  }
  if (query.isError) {
    return (
      <div role="alert" className="m-4 rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-sm">
        <p>{apiErrorMessage(query.error, "Nie udało się wczytać zespołu.")}</p>
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="mt-2 font-medium text-primary underline-offset-4 hover:underline"
        >
          Ponów
        </button>
      </div>
    );
  }

  const team = query.data;
  const hours = team.hours_per_month || DEFAULT_HOURS_PER_MONTH;
  const groups = groupsOf(team);
  const open = team.positions.filter((p) => !p.closed);
  const seats = groups.reduce((n, g) => n + g.headcount, 0);
  const sent = open.reduce((n, p) => n + p.candidates.length, 0);
  const ready = open.filter((p) => p.candidates.length >= MIN_ALTERNATIVES * Math.max(1, p.headcount)).length;
  const range = teamHourlyRange(groups, clientRate);
  const withExpected = open.reduce(
    (n, p) => n + p.candidates.filter((c) => hourlyValue(c.expected_rate) != null).length,
    0,
  );
  const unpricedTitles = open.filter((p) => range.unpriced.includes(String(p.job_id))).map((p) => p.title);

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-3 md:px-2 md:pt-2">
      <PageHeader
        title={team.name}
        description={`${team.client_name ?? "Klient"} · ${positionsLabel(open.length)}, ${peopleLabel(seats)}. Każde stanowisko to zwykła rekrutacja z Championem i Tablicą.`}
        breadcrumb={[{ label: "Rekrutacje", href: "/jobs" }, { label: "Zespoły" }, { label: team.name }]}
      />

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Miejsca w zespole" value={`${seats}`} sub={positionsLabel(open.length)} />
        <Stat
          label="CV wysłane"
          value={`${sent}`}
          sub={`${ready}/${open.length} stanowisk z co najmniej ${MIN_ALTERNATIVES} osobami na miejsce`}
          warn={ready < open.length}
        />
        <Stat
          label="Cena dla klienta / mies."
          value={range.max > 0 ? `${Math.round((range.min * hours) / 1000)}–${formatThousands(range.max * hours)}` : "—"}
          sub={
            range.max > 0
              ? `${formatHourly(range.min)} – ${formatHourly(range.max)} · ${hours} h${unpricedTitles.length ? ` · bez stawki: ${unpricedTitles.length}` : ""}`
              : "Brak stawek do klienta przy wysłanych CV"
          }
          warn={unpricedTitles.length > 0}
        />
        <Stat
          label="Stawka kandydata znana"
          value={`${withExpected}/${sent}`}
          sub="bez niej nie policzymy marży"
          warn={withExpected < sent}
        />
      </div>

      {unpricedTitles.length > 0 ? (
        <p className="inline-flex items-start gap-1.5 text-xs text-warning-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Bez stawki do klienta: {unpricedTitles.join(", ")}. Cena zespołu ich nie liczy.
        </p>
      ) : null}

      <div className="grid items-start gap-3 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <PositionsTable team={team} />
        <div className="grid items-start gap-3 md:grid-cols-2 2xl:grid-cols-1">
          <PanelCard team={team} />
          <TeamVariantsCard team={team} />
          <SelectionsCard team={team} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Cena zespołu to suma stawek do klienta: na każdym miejscu najtańsza albo najdroższa wysłana
        osoba, {hours} godzin w miesiącu, bez rabatu. Przykład: skład za {formatPln(range.min * hours)}{" "}
        to najtańszy możliwy.
      </p>
    </div>
  );
}
