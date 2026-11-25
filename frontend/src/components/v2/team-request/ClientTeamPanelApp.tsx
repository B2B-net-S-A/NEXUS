"use client";

/**
 * Panel klienta dla całego zespołu (`/k/z/{token}`,
 * `docs/claude/klienci/zespol-dla-klienta.md`). Jeden link, kilka stanowisk,
 * na każdym alternatywy z wysłanych CV. Klient układa skład, a cena (suma
 * stawek do klienta, bez rabatu) i start zespołu liczą się na bieżąco.
 * Szczegóły stanowiska to dzisiejszy panel rekrutacji (`ClientPanelApp`) na
 * tokenie stanowiska, więc dowody z CV, pytania i terminy działają jak dotąd.
 *
 * Ekran pokazuje wyłącznie to, co oddał serwer: bez stawki (`show_rate=false`)
 * nie ma ceny. Awaria i link nieaktualny to osobne ekrany, nigdy pusta lista.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Users,
} from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ClientPanelApp,
  panelFailureKind,
} from "@/components/v2/client-panel/ClientPanelApp";
import { SlotWeekGrid } from "@/components/v2/client-panel/PanelDialogs";
import {
  PANEL_CARD,
  PanelTabs,
  Pill,
  StatePill,
} from "@/components/v2/client-panel/parts";
import {
  MAX_SLOTS,
  SLOT_DURATIONS,
  formatPanelDate,
  isValidEmail,
  loadAuthor,
  saveAuthor,
  slotKeyLabel,
  slotWeeks,
  togglePicked,
  warsawLocalToIso,
  type SlotKey,
} from "@/components/v2/client-panel/panel-logic";
import { apiErrorMessage } from "@/lib/api-error";
import type { PanelCandidate } from "@/lib/api/clientPanel";
import {
  httpTeamPanelTransport,
  teamPanelKey,
  type TeamPanelPosition,
  type TeamPanelTransport,
  type TeamPanelVariant,
  type TeamPanelView,
} from "@/lib/api/clientTeamPanel";
import { warsawClock, warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

import {
  DEFAULT_HOURS_PER_MONTH,
  candidateHourly,
  formatHourly,
  formatPln,
  formatThousands,
  formatYmd,
  peopleLabel,
  pickedOf,
  positionsLabel,
  profileTiers,
  rateRange,
  selectionHourly,
  startingPicks,
  teamHourlyRange,
  teamHourlyRangeWithEstimates,
  teamStart,
  togglePick,
  type Picks,
  type SeatGroup,
} from "./team-logic";

/**
 * Klient pisze adres sam, a FastAPI odrzuca zły e-mail walidacją Pydantica:
 * `apiErrorMessage` oddałby wtedy „author_email: value is not a valid email
 * address…” po angielsku. Panel jest publiczny, więc klient dostaje zdanie
 * po polsku (rejestr testera 8032315d2a, 16.11.2026).
 */
function panelErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)
    ?.response;
  const detail = response?.data?.detail;
  if (response?.status === 422 && Array.isArray(detail)) {
    const badEmail = detail.some((item) => {
      const loc = (item as { loc?: unknown } | null)?.loc;
      return Array.isArray(loc) && loc.includes("author_email");
    });
    return badEmail ? "Sprawdź adres e-mail — nie wygląda na poprawny." : fallback;
  }
  return apiErrorMessage(error, fallback);
}

type Tab = "team" | "variants" | "request";

function tabsFor(view: TeamPanelView): { id: Tab; label: string }[] {
  const count = view.variants?.length ?? 0;
  return [
    { id: "team", label: "Skład zespołu" },
    ...(count > 0
      ? [{ id: "variants" as const, label: `Gotowe składy (${count})` }]
      : []),
    { id: "request", label: "Twoje zapytanie" },
  ];
}

const VISIBLE_ALTERNATIVES = 4;
const NOTE_LIMIT = 2000;

const publicId = (c: PanelCandidate) => c.public_id;

function groupsOf(view: TeamPanelView): SeatGroup<PanelCandidate>[] {
  return view.positions.map((p) => ({
    key: p.key,
    headcount: Math.max(1, p.headcount),
    candidates: p.view.candidates,
  }));
}

const STALE = {
  heading: "Ten link jest nieaktualny, napisz do opiekuna procesu",
  body: "Opiekun procesu to osoba z B2Bnetwork, która przesłała Ci link do zespołu. Prześle aktualny.",
};
const FAILED = {
  heading: "Nie udało się otworzyć panelu",
  body: "To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.",
};

function TeamFailure({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const failed = panelFailureKind(error) === "failed";
  const copy = failed ? FAILED : STALE;
  return (
    <main className="mx-auto w-full max-w-xl p-4 pt-12 sm:p-6 sm:pt-16">
      <div
        role="alert"
        className="rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-center sm:p-6"
      >
        <AlertCircle className="mx-auto mb-3 h-8 w-8 text-destructive" />
        <h1 className="mb-1 font-display text-lg font-semibold">
          {copy.heading}
        </h1>
        <p className="text-sm text-muted-foreground">{copy.body}</p>
        {failed ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Ponów
          </button>
        ) : null}
      </div>
    </main>
  );
}

function TopBar({ view }: { view: TeamPanelView }) {
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-border bg-card px-4 py-2">
      <span
        aria-hidden
        className="grid h-7 w-7 place-items-center rounded-md bg-primary font-display text-[11px] font-bold text-primary-foreground"
      >
        B2B
      </span>
      <span className="text-sm font-semibold">B2Bnetwork</span>
      {view.team.client_name ? (
        <span className="text-sm text-muted-foreground">
          zespół dla {view.team.client_name}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground sm:ml-auto">
        {view.team.expires_at ? (
          <span>Link ważny do {formatPanelDate(view.team.expires_at)}</span>
        ) : null}
        {view.team.owner?.name ? (
          <span>Opiekun: {view.team.owner.name}</span>
        ) : null}
      </div>
    </header>
  );
}

function PriceBand({
  view,
  picks,
  today,
}: {
  view: TeamPanelView;
  picks: Picks;
  today: string;
}) {
  const hours = view.hours_per_month || DEFAULT_HOURS_PER_MONTH;
  const groups = groupsOf(view);
  const estimates = Object.fromEntries(view.positions.map((p) => [p.key, p.estimate ?? null]));
  const range = teamHourlyRangeWithEstimates(groups, candidateHourly, estimates);
  const chosen = selectionHourly(groups, picks, publicId, candidateHourly);
  const start = teamStart(groups, picks, today);
  const estimatedNames = view.positions.filter((p) => range.estimated.includes(p.key)).map((p) => p.short);
  const span = range.max - range.min;
  const marker =
    span > 0
      ? Math.min(100, Math.max(0, ((chosen.total - range.min) / span) * 100))
      : 100;
  const unpricedNames = view.positions
    .filter((p) => range.unpriced.includes(p.key))
    .map((p) => p.short);
  const priced = range.max > 0;

  return (
    <div
      className={cn(
        PANEL_CARD,
        "grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 px-3.5 py-3",
      )}
      data-testid="team-price-band"
    >
      {priced ? (
        <>
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="font-display text-sm font-semibold">Cena zespołu</h2>
            <span className="text-[11px] text-muted-foreground">
              netto, B2B, {hours} h/mies.
            </span>
          </div>
          <p className="font-display text-lg font-bold tabular-nums leading-tight">
            {range.min === range.max
              ? formatThousands(range.min * hours)
              : `od ${formatThousands(range.min * hours)} do ${formatThousands(range.max * hours)}`}
            <span className="text-sm font-medium text-muted-foreground">
              {" "}
              / mies.
            </span>
          </p>
          {span > 0 ? (
            <>
              <div className="relative h-2 rounded-full bg-muted" aria-hidden>
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-primary/25"
                  style={{ width: `${marker}%` }}
                />
                <div
                  className="absolute -top-1 h-4 w-1 rounded-full bg-primary"
                  style={{ left: `calc(${marker}% - 2px)` }}
                />
              </div>
              <div className="flex justify-between text-[11px] tabular-nums text-muted-foreground">
                <span>{formatHourly(range.min)}</span>
                <span>{formatHourly(range.max)}</span>
              </div>
            </>
          ) : null}
        </>
      ) : (
        <h2 className="font-display text-sm font-semibold">Twój zespół</h2>
      )}
      <div
        className={cn(
          "grid gap-1 text-sm",
          priced && "mt-1 border-t border-border pt-2",
        )}
      >
        {priced ? (
          <>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Twój skład</span>
              <span
                className="font-semibold tabular-nums"
                data-testid="team-selection-month"
              >
                {formatPln(chosen.total * hours)} / mies.
              </span>
            </div>
            <div className="flex justify-between gap-2 text-xs">
              <span className="text-muted-foreground">
                za godzinę całego zespołu
              </span>
              <span className="tabular-nums">{formatHourly(chosen.total)}</span>
            </div>
          </>
        ) : null}
        <div className="flex justify-between gap-2 text-xs">
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <CalendarClock className="h-3.5 w-3.5" />
            start całego zespołu
          </span>
          <span className="text-right">
            {start.date <= today ? "od zaraz" : `od ${formatYmd(start.date)}`}
            {start.unknown > 0 ? (
              <span className="block text-[11px] text-muted-foreground">
                {peopleLabel(start.unknown)} z terminem do ustalenia
              </span>
            ) : null}
          </span>
        </div>
        {chosen.openSeats > 0 ? (
          <p className="text-xs text-warning-muted-foreground">
            Bez osoby:{" "}
            {chosen.openSeats === 1
              ? "1 miejsce"
              : `${chosen.openSeats} miejsca`}
            {priced ? ", cena ich nie liczy." : "."}
          </p>
        ) : null}
        {priced && chosen.unpriced > 0 ? (
          <p className="text-xs text-muted-foreground">
            {peopleLabel(chosen.unpriced)} bez stawki w panelu: cenę poda
            opiekun.
          </p>
        ) : null}
        {priced && estimatedNames.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            W cenie od–do szacunek dla: {estimatedNames.join(", ")} (jeszcze bez CV, na podstawie stawek dla
            podobnych ról).
          </p>
        ) : null}
        {priced && unpricedNames.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Bez stawki: {unpricedNames.join(", ")}.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function AlternativeCard({
  candidate,
  fallbackTitle,
  showRate,
  selected,
  onToggle,
}: {
  candidate: PanelCandidate;
  fallbackTitle: string;
  showRate: boolean;
  selected: boolean;
  onToggle: () => void;
}) {
  const rate = candidateHourly(candidate);
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      className={cn(
        "relative grid min-w-0 gap-0.5 rounded-lg border px-2.5 py-2 text-left transition-colors",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary bg-primary/5 ring-1 ring-primary"
          : "border-border bg-card hover:bg-muted",
        candidate.state === "not_fit" && "opacity-60",
      )}
      data-testid={`alt-${candidate.public_id}`}
    >
      {selected ? (
        <span className="absolute right-2 top-2 grid h-4 w-4 place-items-center rounded-full bg-primary text-primary-foreground">
          <Check className="h-3 w-3" />
        </span>
      ) : null}
      <span className="truncate pr-5 text-sm font-semibold">
        {candidate.name}
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {candidate.title ?? fallbackTitle}
      </span>
      <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
        {showRate ? (
          <span className="font-medium tabular-nums">
            {rate != null ? formatHourly(rate) : "stawka u opiekuna"}
          </span>
        ) : null}
        <span className="text-muted-foreground">
          {candidate.available_label}
        </span>
      </span>
      {candidate.state !== "none" ? (
        <span className="mt-0.5">
          <StatePill state={candidate.state} />
        </span>
      ) : null}
    </button>
  );
}

function PositionRow({
  position,
  picks,
  onToggle,
  onOpen,
}: {
  position: TeamPanelPosition;
  picks: Picks;
  onToggle: (id: string) => void;
  onOpen: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const candidates = position.view.candidates;
  const showRate = position.view.panel.show_rate;
  const range = showRate
    ? rateRange(
        { key: position.key, headcount: 1, candidates },
        candidateHourly,
      )
    : null;
  const tiers = showRate ? profileTiers(candidates) : [];
  const chosen = picks[position.key] ?? [];
  const seats = Math.max(1, position.headcount);
  // Kolejność stała (z serwera): karta pod kursorem nie przeskakuje po kliku.
  // Wybrana osoba spoza pierwszych kart jest zawsze widoczna.
  const shown = expanded
    ? candidates
    : candidates.filter(
        (c, index) =>
          index < VISIBLE_ALTERNATIVES || chosen.includes(c.public_id),
      );
  const hidden = candidates.length - shown.length;

  return (
    <section
      className={cn(PANEL_CARD, "px-3.5 py-2.5")}
      data-testid={`position-${position.key}`}
    >
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-display text-sm font-semibold">
          {position.short}
          <span className="ml-1.5 font-sans text-xs font-medium text-muted-foreground">
            {peopleLabel(seats)} · wybrano {chosen.length}/{seats}
          </span>
        </h3>
        {tiers.length > 1 ? (
          <span className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            Profile:
            {tiers.map((tier) => (
              <Pill key={tier.rate}>
                {formatHourly(tier.rate)} · {tier.count}
                {tier.availableNow > 0
                  ? ` (${tier.availableNow} od zaraz)`
                  : ""}
              </Pill>
            ))}
          </span>
        ) : range ? (
          <span className="text-xs text-muted-foreground">
            {formatHourly(range.min)} u wszystkich
          </span>
        ) : null}
        <button
          type="button"
          onClick={onOpen}
          className="ml-auto inline-flex items-center gap-0.5 text-xs font-medium text-primary underline-offset-4 hover:underline"
        >
          Wszyscy ({candidates.length}) i dowody z CV
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      {candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Na to stanowisko nie wysłaliśmy jeszcze CV. Opiekun da znać, gdy się
          pojawią.
          {showRate && position.estimate
            ? ` Szacunek stawki: ${formatHourly(position.estimate.min)} – ${formatHourly(position.estimate.max)}.`
            : ""}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {shown.map((candidate) => (
            <AlternativeCard
              key={candidate.public_id}
              candidate={candidate}
              fallbackTitle={position.short}
              showRate={showRate}
              selected={chosen.includes(candidate.public_id)}
              onToggle={() => onToggle(candidate.public_id)}
            />
          ))}
        </div>
      )}
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-1.5 text-xs font-medium text-muted-foreground underline-offset-4 hover:underline"
        >
          + {hidden === 1 ? "1 kolejna osoba" : `${hidden} kolejne osoby`} na
          tym stanowisku
        </button>
      ) : null}
    </section>
  );
}

function SelectionSummary({
  view,
  picks,
  onSend,
  onInterviews,
}: {
  view: TeamPanelView;
  picks: Picks;
  onSend: () => void;
  onInterviews: () => void;
}) {
  const groups = groupsOf(view);
  const count = groups.reduce(
    (n, g) => n + pickedOf(g, picks, publicId).length,
    0,
  );
  const canAct = view.positions.some((p) => p.view.panel.allow_actions);
  return (
    <div
      className={cn(
        PANEL_CARD,
        "grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5 px-3.5 py-3",
      )}
    >
      <h2 className="font-display text-sm font-semibold">
        Twój skład · {peopleLabel(count)}
      </h2>
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-1 text-sm">
        {view.positions.flatMap((position, index) => {
          const chosen = pickedOf(groups[index], picks, publicId);
          return Array.from(
            { length: Math.max(1, position.headcount) },
            (_, seat) => {
              const person = chosen[seat];
              const rate =
                person && position.view.panel.show_rate
                  ? candidateHourly(person)
                  : null;
              return (
                <li
                  key={`${position.key}-${seat}`}
                  className="flex min-w-0 items-baseline justify-between gap-2"
                >
                  <span className="min-w-0 truncate">
                    <span className="text-muted-foreground">
                      {position.short}:{" "}
                    </span>
                    {person ? (
                      person.name
                    ) : (
                      <span className="text-warning-muted-foreground">
                        wybierz
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {rate != null ? formatHourly(rate) : ""}
                  </span>
                </li>
              );
            },
          );
        })}
      </ul>
      {canAct ? (
        <>
          <Button
            className="mt-1.5"
            onClick={onInterviews}
            disabled={count === 0}
          >
            Poproś o rozmowy z tym składem ({count})
          </Button>
          <Button variant="outline" onClick={onSend} disabled={count === 0}>
            Wyślij skład opiekunowi
          </Button>
          <p className="text-[11px] text-muted-foreground">
            Nic nie jest wiążące. Opiekun odpisze i umówi rozmowy z wybranymi
            osobami.
          </p>
        </>
      ) : null}
    </div>
  );
}

function RequestTab({ view }: { view: TeamPanelView }) {
  return (
    <div className={cn(PANEL_CARD, "overflow-x-auto")}>
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Stanowisko</th>
            <th className="px-3 py-2 text-center font-medium">Osoby</th>
            <th className="px-3 py-2 text-center font-medium">Wymagania</th>
            <th className="px-3 py-2 text-center font-medium">Kandydaci</th>
            <th className="px-3 py-2 text-right font-medium">Stawki</th>
          </tr>
        </thead>
        <tbody>
          {view.positions.map((position) => {
            const range = position.view.panel.show_rate
              ? rateRange(
                  {
                    key: position.key,
                    headcount: 1,
                    candidates: position.view.candidates,
                  },
                  candidateHourly,
                )
              : null;
            return (
              <tr
                key={position.key}
                className="border-b border-border last:border-b-0"
              >
                <td className="px-3 py-2">
                  <div className="font-medium">{position.short}</div>
                  {position.view.job.title !== position.short ? (
                    <div className="text-xs text-muted-foreground">
                      {position.view.job.title}
                    </div>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-center tabular-nums">
                  {Math.max(1, position.headcount)}
                </td>
                <td className="px-3 py-2 text-center tabular-nums">
                  {position.view.requirements.length}
                </td>
                <td className="px-3 py-2 text-center tabular-nums">
                  {position.view.candidates.length}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                  {range
                    ? range.min === range.max
                      ? formatHourly(range.min)
                      : `${formatHourly(range.min)} – ${formatHourly(range.max)}`
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
        Treść zapytania i wymagania stanowiska są w „Wszyscy i dowody z CV”,
        zakładka „Twoje zapytanie”.
      </p>
    </div>
  );
}

function SendSelectionDialog({
  view,
  picks,
  transport,
  onClose,
}: {
  view: TeamPanelView;
  picks: Picks;
  transport: TeamPanelTransport;
  onClose: () => void;
}) {
  const { showSuccess } = useToast();
  const [author, setAuthor] = useState(() => loadAuthor());
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const groups = groupsOf(view);
  const people = view.positions.flatMap((p, i) =>
    pickedOf(groups[i], picks, publicId).map((c) => ({
      id: `${p.key}-${c.public_id}`,
      position: p.short,
      name: c.name,
    })),
  );
  const mutation = useMutation({
    mutationFn: () =>
      transport.sendSelection({
        author_name: author.name.trim(),
        author_email: author.email.trim(),
        picks: Object.fromEntries(
          Object.entries(picks).filter(([, ids]) => ids.length > 0),
        ),
        note: note.trim() || undefined,
      }),
    onSuccess: () => {
      saveAuthor({ name: author.name.trim(), email: author.email.trim() });
      showSuccess("Skład wysłany do opiekuna");
      onClose();
    },
    onError: (error) => {
      const response = (
        error as { response?: { status?: number; data?: { detail?: unknown } } }
      )?.response;
      setProblem(
        response?.status === 429 && typeof response.data?.detail === "string"
          ? response.data.detail
          : panelErrorMessage(error, "Nie udało się wysłać składu. Spróbuj ponownie."),
      );
    },
  });
  const send = () => {
    const found = !author.name.trim()
      ? "Podaj imię, żeby opiekun wiedział, z kim rozmawia."
      : !isValidEmail(author.email)
        ? "Podaj poprawny adres e-mail."
        : null;
    setProblem(found);
    if (!found) mutation.mutate();
  };
  const label = "grid gap-1 text-xs text-muted-foreground";

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Wyślij skład opiekunowi"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={mutation.isPending} onClick={send}>
            {mutation.isPending ? "Wysyłam…" : "Wyślij skład"}
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5">
        <ul className="grid gap-0.5 rounded-lg border border-border px-3 py-2 text-sm">
          {people.map((person) => (
            <li key={person.id} className="truncate">
              <span className="text-muted-foreground">{person.position}: </span>
              {person.name}
            </li>
          ))}
        </ul>
        <label className={label}>
          Coś do dodania (opcjonalnie)
          <Textarea
            value={note}
            maxLength={NOTE_LIMIT}
            rows={3}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className={label}>
            Twoje imię
            <Input
              value={author.name}
              autoComplete="name"
              maxLength={120}
              onChange={(e) => setAuthor({ ...author, name: e.target.value })}
            />
          </label>
          <label className={label}>
            Twój e-mail
            <Input
              type="email"
              value={author.email}
              autoComplete="email"
              maxLength={200}
              onChange={(e) => setAuthor({ ...author, email: e.target.value })}
            />
          </label>
        </div>
        <p className="text-xs text-muted-foreground">
          Skład trafi do opiekuna procesu
          {view.team.owner?.name ? ` (${view.team.owner.name})` : ""}. Nic nie
          jest wiążące.
        </p>
        {problem ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-2.5 py-1.5 text-sm text-destructive"
          >
            {problem}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

function VariantsTab({
  view,
  current,
  today,
  onPick,
}: {
  view: TeamPanelView;
  current: string | null;
  today: string;
  onPick: (variant: TeamPanelVariant) => void;
}) {
  const hours = view.hours_per_month || DEFAULT_HOURS_PER_MONTH;
  const groups = groupsOf(view);
  const priced = teamHourlyRange(groups, candidateHourly).max > 0;
  return (
    <div className="grid items-start gap-3 md:grid-cols-3">
      {(view.variants ?? []).map((variant, index) => {
        const chosen = selectionHourly(
          groups,
          variant.picks,
          publicId,
          candidateHourly,
        );
        const start = teamStart(groups, variant.picks, today);
        const active = current === variant.key;
        return (
          <div
            key={variant.key}
            className={cn(
              PANEL_CARD,
              "flex min-w-0 flex-col gap-2 px-3.5 py-3",
              active && "ring-2 ring-primary",
            )}
            data-testid={`variant-${variant.key}`}
          >
            <div className="flex items-center gap-2">
              {index === 0 ? (
                <Sparkles className="h-4 w-4 text-primary" />
              ) : null}
              <h2 className="font-display text-base font-semibold">
                {variant.name}
              </h2>
            </div>
            {priced ? (
              <p className="font-display text-xl font-bold tabular-nums">
                {formatPln(chosen.total * hours)}
                <span className="text-sm font-medium text-muted-foreground">
                  {" "}
                  / mies.
                </span>
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              {priced ? `${formatHourly(chosen.total)} · ` : ""}start{" "}
              {start.date <= today ? "od zaraz" : `od ${formatYmd(start.date)}`}
              {start.unknown > 0
                ? ` · ${peopleLabel(start.unknown)} z terminem do ustalenia`
                : ""}
            </p>
            {variant.why ? <p className="text-sm">{variant.why}</p> : null}
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5 border-t border-border pt-2 text-sm">
              {view.positions.flatMap((position, i) =>
                pickedOf(groups[i], variant.picks, publicId).map((person) => (
                  <li
                    key={`${position.key}-${person.public_id}`}
                    className="flex min-w-0 justify-between gap-2"
                  >
                    <span className="min-w-0 truncate">
                      <span className="text-muted-foreground">
                        {position.short}:{" "}
                      </span>
                      {person.name}
                    </span>
                    {priced && candidateHourly(person) != null ? (
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                        {formatHourly(candidateHourly(person)!)}
                      </span>
                    ) : null}
                  </li>
                )),
              )}
            </ul>
            <Button
              className="mt-auto"
              variant={active ? "primary" : "outline"}
              onClick={() => onPick(variant)}
            >
              {active ? "Ten skład jest wybrany" : "Wybierz ten skład"}
            </Button>
          </div>
        );
      })}
    </div>
  );
}

function InterviewsDialog({
  view,
  picks,
  transport,
  onClose,
}: {
  view: TeamPanelView;
  picks: Picks;
  transport: TeamPanelTransport;
  onClose: () => void;
}) {
  const { showSuccess } = useToast();
  const weeks = useMemo(() => slotWeeks(warsawToday(), warsawClock()), []);
  const [weekIndex, setWeekIndex] = useState(0);
  const [slots, setSlots] = useState<SlotKey[]>([]);
  const [duration, setDuration] = useState<number>(SLOT_DURATIONS[0]);
  const [interviewers, setInterviewers] = useState("");
  const [author, setAuthor] = useState(() => loadAuthor());
  const [problem, setProblem] = useState<string | null>(null);
  const groups = groupsOf(view);
  const people = view.positions.flatMap((p, i) =>
    pickedOf(groups[i], picks, publicId).map((c) => ({
      key: p.key,
      id: c.public_id,
      position: p.short,
      name: c.name,
    })),
  );
  const [included, setIncluded] = useState<Set<string>>(
    () => new Set(people.map((p) => `${p.key}:${p.id}`)),
  );
  const chosen = people.filter((p) => included.has(`${p.key}:${p.id}`));
  const mutation = useMutation({
    mutationFn: () => {
      const byKey: Record<string, string[]> = {};
      for (const person of chosen)
        byKey[person.key] = [...(byKey[person.key] ?? []), person.id];
      return transport.sendInterviews({
        author_name: author.name.trim(),
        author_email: author.email.trim(),
        duration_minutes: duration,
        slots: slots.map((key) => ({ start: warsawLocalToIso(key) })),
        ...(interviewers.trim() ? { interviewers: interviewers.trim() } : {}),
        picks: byKey,
      });
    },
    onSuccess: (result) => {
      saveAuthor({ name: author.name.trim(), email: author.email.trim() });
      showSuccess(
        result.skipped.length > 0
          ? `Wysłano prośby o ${result.created} rozmów. ${peopleLabel(result.skipped.length)} ma już otwartą prośbę.`
          : `Wysłano prośby o ${result.created} rozmów do opiekuna`,
      );
      onClose();
    },
    onError: (error) => {
      const response = (
        error as { response?: { status?: number; data?: { detail?: unknown } } }
      )?.response;
      setProblem(
        response?.status === 429 && typeof response.data?.detail === "string"
          ? response.data.detail
          : panelErrorMessage(error, "Nie udało się wysłać próśb o rozmowy. Spróbuj ponownie."),
      );
    },
  });
  const send = () => {
    const found =
      chosen.length === 0
        ? "Zaznacz co najmniej jedną osobę."
        : slots.length === 0
          ? "Zaznacz co najmniej jeden termin."
          : !author.name.trim()
            ? "Podaj imię, żeby opiekun wiedział, z kim rozmawia."
            : !isValidEmail(author.email)
              ? "Podaj poprawny adres e-mail."
              : null;
    setProblem(found);
    if (!found) mutation.mutate();
  };
  const label = "grid gap-1 text-xs text-muted-foreground";

  return (
    <AppModal
      open
      size="xl"
      onOpenChange={(open) => !open && onClose()}
      title="Rozmowy z całym składem"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={mutation.isPending} onClick={send}>
            {mutation.isPending
              ? "Wysyłam…"
              : `Wyślij prośbę o ${chosen.length} rozmów`}
          </Button>
        </>
      }
    >
      <div className="grid gap-3.5 md:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <SlotWeekGrid
            weeks={weeks}
            weekIndex={weekIndex}
            onWeekChange={setWeekIndex}
            picked={slots}
            onToggle={(key) =>
              setSlots((current) => togglePicked(current, key))
            }
          />
          <p className="mt-1.5 text-xs text-muted-foreground">
            Zaznacz okna raz dla wszystkich ({slots.length} z {MAX_SLOTS}).
            Opiekun ułoży rozmowy po kolei i potwierdzi je z każdą osobą.
            {slots.length > 0
              ? ` Wybrane: ${slots.map(slotKeyLabel).join(", ")}.`
              : ""}
          </p>
        </div>
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2">
          <span className="text-xs text-muted-foreground">Kogo dotyczy</span>
          {people.map((person) => {
            const id = `${person.key}:${person.id}`;
            return (
              <label
                key={id}
                className="flex min-w-0 items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 accent-primary"
                  checked={included.has(id)}
                  onChange={() =>
                    setIncluded((current) => {
                      const next = new Set(current);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return next;
                    })
                  }
                />
                <span className="min-w-0 truncate">
                  {person.name}{" "}
                  <span className="text-muted-foreground">
                    · {person.position}
                  </span>
                </span>
              </label>
            );
          })}
          <label className={label}>
            Długość jednej rozmowy
            <select
              className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
            >
              {SLOT_DURATIONS.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} min
                </option>
              ))}
            </select>
          </label>
          <label className={label}>
            Kto rozmawia (opcjonalnie)
            <Input
              value={interviewers}
              maxLength={200}
              onChange={(e) => setInterviewers(e.target.value)}
            />
          </label>
          <label className={label}>
            Twoje imię
            <Input
              value={author.name}
              autoComplete="name"
              maxLength={120}
              onChange={(e) => setAuthor({ ...author, name: e.target.value })}
            />
          </label>
          <label className={label}>
            Twój e-mail
            <Input
              type="email"
              value={author.email}
              autoComplete="email"
              maxLength={200}
              onChange={(e) => setAuthor({ ...author, email: e.target.value })}
            />
          </label>
          {problem ? (
            <p
              role="alert"
              className="rounded-md bg-destructive/10 px-2.5 py-1.5 text-sm text-destructive"
            >
              {problem}
            </p>
          ) : null}
        </div>
      </div>
    </AppModal>
  );
}

function readUrlPosition(): string | null {
  return new URLSearchParams(window.location.search).get("p");
}

export interface ClientTeamPanelAppProps {
  token: string;
  /** Harness i testy: dane fikcyjne, zero zapytań. */
  transport?: TeamPanelTransport;
  initialPosition?: string | null;
}

export function ClientTeamPanelApp({
  token,
  transport,
  initialPosition = null,
}: ClientTeamPanelAppProps) {
  const client = useMemo(
    () => transport ?? httpTeamPanelTransport(token),
    [transport, token],
  );
  const [tab, setTab] = useState<Tab>("team");
  const [openKey, setOpenKey] = useState<string | null>(initialPosition);
  const [picks, setPicks] = useState<Picks | null>(null);
  const [variantKey, setVariantKey] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [interviews, setInterviews] = useState(false);
  const today = warsawToday();

  const query = useQuery({
    queryKey: teamPanelKey(token),
    queryFn: () => client.fetchTeam(),
    staleTime: 30_000,
  });

  useEffect(() => {
    const onPop = () => setOpenKey(readUrlPosition());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const open = useCallback((key: string | null) => {
    setOpenKey(key);
    const url = new URL(window.location.href);
    url.searchParams.delete("c");
    if (key) url.searchParams.set("p", key);
    else url.searchParams.delete("p");
    window.history.pushState(null, "", url.toString());
  }, []);

  if (query.isPending) {
    return (
      <div
        className="grid h-dvh place-items-center text-sm text-muted-foreground"
        role="status"
      >
        Wczytuję panel zespołu…
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <TeamFailure error={query.error} onRetry={() => void query.refetch()} />
    );
  }

  const view = query.data;
  const groups = groupsOf(view);
  // Bez wyboru klienta: pierwszy zatwierdzony skład opiekuna, a bez niego skład startowy.
  const firstVariant = view.variants?.[0] ?? null;
  const current = picks ?? firstVariant?.picks ?? startingPicks(groups);
  const shownVariant = picks ? variantKey : (firstVariant?.key ?? null);
  const opened = view.positions.find((p) => p.key === openKey) ?? null;
  const seats = groups.reduce((n, g) => n + g.headcount, 0);
  const sent = groups.reduce((n, g) => n + g.candidates.length, 0);

  if (opened) {
    return (
      <ClientPanelApp
        key={opened.key}
        token={opened.key}
        header={
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-card px-4 py-1.5 text-sm">
            <Button variant="outline" size="sm" onClick={() => open(null)}>
              <ChevronLeft className="h-3.5 w-3.5" />
              Zespół
            </Button>
            <span className="text-muted-foreground">{view.team.name} ›</span>
            <span className="font-medium">{opened.short}</span>
          </div>
        }
      />
    );
  }

  return (
    <div
      className="flex h-dvh flex-col bg-background text-foreground"
      data-testid="client-team-panel"
    >
      <TopBar view={view} />
      <main className="min-h-0 flex-1 overflow-auto px-4 py-3">
        <div className="mb-2 flex min-w-0 flex-wrap items-end gap-x-4 gap-y-1">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">
              {[
                view.team.client_name,
                positionsLabel(view.positions.length),
                `${sent} kandydatów wysłanych`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <h1 className="font-display text-xl font-bold tracking-tight">
              {view.team.name}, {peopleLabel(seats)}
            </h1>
          </div>
          {(view.variants?.length ?? 0) > 0 ? (
            <span className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Users className="h-3.5 w-3.5" />
              {shownVariant
                ? `Skład: ${view.variants?.find((v) => v.key === shownVariant)?.name ?? ""}`
                : "Skład ułożony przez Ciebie"}
            </span>
          ) : null}
        </div>
        <PanelTabs
          tabs={tabsFor(view)}
          active={tab}
          onChange={setTab}
          label="Widok zespołu"
        />
        {tab === "request" ? (
          <RequestTab view={view} />
        ) : tab === "variants" ? (
          <VariantsTab
            view={view}
            current={shownVariant}
            today={today}
            onPick={(variant) => {
              setPicks(variant.picks);
              setVariantKey(variant.key);
              setTab("team");
            }}
          />
        ) : view.positions.length === 0 ? (
          <div className={cn(PANEL_CARD, "p-4 text-sm text-muted-foreground")}>
            W tym zespole nie ma teraz otwartych stanowisk. Napisz do opiekuna
            procesu.
          </div>
        ) : (
          <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="grid gap-2.5">
              {view.positions.map((position) => (
                <PositionRow
                  key={position.key}
                  position={position}
                  picks={current}
                  onToggle={(id) => {
                    setVariantKey(null);
                    setPicks(
                      togglePick(current, position.key, position.headcount, id),
                    );
                  }}
                  onOpen={() => open(position.key)}
                />
              ))}
            </div>
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 lg:sticky lg:top-0">
              <PriceBand view={view} picks={current} today={today} />
              <SelectionSummary
                view={view}
                picks={current}
                onSend={() => setSending(true)}
                onInterviews={() => setInterviews(true)}
              />
            </div>
          </div>
        )}
      </main>
      {interviews ? (
        <InterviewsDialog
          view={view}
          picks={current}
          transport={client}
          onClose={() => setInterviews(false)}
        />
      ) : null}
      {sending ? (
        <SendSelectionDialog
          view={view}
          picks={current}
          transport={client}
          onClose={() => setSending(false)}
        />
      ) : null}
    </div>
  );
}
