"use client";
// A · Opieka i rozmowy — łączy dawne „Opieka” (zakładka 7 z 10) i „Notatki /
// Rozmowy”. Pas „Co się dzieje” nad zakładkami pokazuje już powody „Uwaga”
// i następny krok, więc tu nie ma ich powtórki ani imienia i klienta: cienki
// wiersz z opiekunem i rytmem, po lewej jeden strumień rozmów i notatek
// z kompozytorem (pigułki rodzaju zamiast natywnej listy), po prawej plan
// kontaktów, zadowolenie i opinie, sprawy i to, co wiemy o projekcie.
// Zapis nic nie robi (makieta). Hooki opieki i planu eksportujemy dla `OpiekaB`.
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  Handshake,
  MessageSquareText,
  Phone,
  Plus,
  StickyNote,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  caseMeta,
  caseStatusPill,
  caseWhen,
  closedCasesLine,
  managerFeedbackKpi,
  openCases,
  satisfactionKpi,
  teamText,
  type CaseStatusTone,
  type KpiTone,
} from "@/components/care/card/card-format";
import api, { type ContractTimelineItem } from "@/lib/api";
import {
  CHANNEL_LABELS,
  HIRING_SOURCE_LABELS,
  OWNER_SOURCE_LABELS,
  type CardCase,
  type ConsultantCardData,
  type ContractCare,
  type ContractTimeline,
  type HiringSource,
} from "@/lib/api/care";
import {
  EXTENSION_LABELS,
  FEEDBACK_CHANNEL_LABELS,
  formatAverage,
  type ContractFeedbackItem,
} from "@/lib/api/client-people";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { useMkCareCard, useMkContract, useMkNotes, type MkCareCard } from "../shared/data";
import { DNI, daysUntil, fmtDate, fmtMonthYear, personFromEmail, plural, relDays } from "../shared/format";
import type { TabProps } from "./types";

// ── Dane (tylko GET) ──────────────────────────────────────────────────────────

const get = <T,>(url: string) => api.get<T>(url).then((r) => r.data);

/** Ta sama trasa co `useConsultantCard` — pełny typ karty z `lib/api/care`. */
export function asCard(data: MkCareCard | undefined): ConsultantCardData | undefined {
  return data as unknown as ConsultantCardData | undefined;
}

/** Rozmowy, karty technologiczne i plan z `overdue` (`GET /api/care/contracts/{id}`). */
export function useMkCareDetail(id: number) {
  return useQuery<ContractCare>({
    queryKey: ["mk-care-detail", id],
    queryFn: () => get<ContractCare>(`/api/care/contracts/${id}`),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

/** Oś opieki: rozmowy, sprawy, opinie, umowa i zamówienia (te same zdarzenia co „Historia” karty). */
export function useMkCareTimeline(id: number) {
  return useQuery<ContractTimeline>({
    queryKey: ["mk-care-timeline", id],
    queryFn: () => get<ContractTimeline>(`/api/care/contracts/${id}/timeline`),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

/** Opinie klienta o konsultancie (D11) — widzi opiekun, DL, HoR i admin. */
export function useMkCareFeedback(id: number) {
  return useQuery<{ items: ContractFeedbackItem[]; client_id: number; can_write: boolean }>({
    queryKey: ["mk-care-feedback", id],
    queryFn: () => get<{ items: ContractFeedbackItem[]; client_id: number; can_write: boolean }>(`/api/care/contracts/${id}/feedback`),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

// ── Plan kontaktów ────────────────────────────────────────────────────────────

export interface PlanView {
  id: number;
  label: string;
  due: string;
  status: "open" | "done" | "skipped";
  /** Dni po terminie otwartego punktu; `null` = nie jest zaległy. */
  overdueDays: number | null;
}

export function planRows(card: ConsultantCardData): PlanView[] {
  return [...card.plan]
    .sort((a, b) => a.due_on.localeCompare(b.due_on))
    .map((p) => {
      const d = daysUntil(p.due_on) ?? 0;
      return {
        id: p.id,
        label: p.label,
        due: p.due_on,
        status: p.status,
        overdueDays: p.status === "open" && d < 0 ? -d : null,
      };
    });
}

export function planWhen(row: PlanView): { text: string; tone: StatusDotTone } {
  if (row.status === "done") return { text: "zrobiony", tone: "success" };
  if (row.status === "skipped") return { text: "pominięty", tone: "neutral" };
  if (row.overdueDays) return { text: `zaległe ${plural(row.overdueDays, DNI)}`, tone: "danger" };
  return { text: relDays(row.due), tone: "info" };
}

export const KPI_TEXT: Record<KpiTone, string> = {
  neutral: "text-foreground",
  good: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
};

export const CASE_DOT: Record<CaseStatusTone, StatusDotTone> = {
  info: "info",
  warning: "warning",
  neutral: "neutral",
};

// ── Strumień rozmów i notatek ─────────────────────────────────────────────────

type StreamKind = "note" | "call" | "consultant" | "client" | "project";

interface StreamItem {
  key: string;
  on: string;
  kind: StreamKind;
  title: string;
  body: string | null;
  meta: string[];
}

const STREAM_ICON: Record<StreamKind, LucideIcon> = {
  note: StickyNote,
  call: Phone,
  consultant: UserRound,
  client: Handshake,
  project: MessageSquareText,
};

const NOTE_LABEL: Record<string, string> = {
  general: "Notatka",
  call: "Rozmowa",
  meeting: "Spotkanie",
  email: "E-mail",
};

const CALL_LABEL: Record<string, string> = {
  inbound: "Połączenie przychodzące",
  outbound: "Połączenie wychodzące",
};

const compact = (parts: (string | null | undefined)[]) => parts.filter((p): p is string => Boolean(p));
const tidy = (text: string | null | undefined) => (text ? text.replace(/\n{2,}/g, "\n").trim() : null);

function buildStream(
  notes: ContractTimelineItem[],
  care: ContractCare | undefined,
  feedback: ContractFeedbackItem[],
): StreamItem[] {
  const items: StreamItem[] = [];
  for (const n of notes) {
    const author = n.author_name ? personFromEmail(n.author_name) : null;
    if (n.kind === "call") {
      items.push({
        key: `call-${n.id}`,
        on: n.at,
        kind: "call",
        title: CALL_LABEL[n.sub_type ?? ""] ?? "Połączenie",
        body: tidy(n.summary ?? n.content),
        meta: compact([author, n.duration_seconds ? `${Math.max(1, Math.round(n.duration_seconds / 60))} min` : null]),
      });
    } else {
      items.push({
        key: `note-${n.id}`,
        on: n.at,
        kind: "note",
        title: NOTE_LABEL[n.sub_type ?? ""] ?? "Notatka",
        body: tidy(n.content),
        meta: compact([author]),
      });
    }
  }
  for (const cv of care?.conversations ?? []) {
    items.push({
      key: `cv-${cv.id}`,
      on: cv.occurred_on,
      kind: "consultant",
      title: `Rozmowa z konsultantem · ${CHANNEL_LABELS[cv.channel].toLowerCase()}`,
      body: tidy(cv.note),
      meta: compact([
        cv.author?.name,
        cv.satisfaction != null ? `zadowolenie ${cv.satisfaction} / 5` : null,
        cv.attrition_risk ? "ryzyko odejścia" : null,
        cv.wants_change ? "chce zmiany projektu" : null,
        cv.client_hiring ? "klient zatrudnia" : null,
        cv.project_end_on ? `koniec projektu ${fmtDate(cv.project_end_on)}` : null,
      ]),
    });
  }
  for (const tc of care?.tech_cards ?? []) {
    if (tc.is_draft) continue;
    items.push({
      key: `tc-${tc.id}`,
      on: tc.interview_on,
      kind: "project",
      title: "Rozmowa o projekcie · karta technologiczna",
      body: tidy(tc.memorable_quote ?? tc.note),
      meta: compact([tc.author?.name, tc.area ? `dział ${tc.area.name}` : null]),
    });
  }
  for (const f of feedback) {
    items.push({
      key: `fb-${f.session_id}`,
      on: f.held_on,
      kind: "client",
      title: compact([`Rozmowa z klientem · ${FEEDBACK_CHANNEL_LABELS[f.channel].toLowerCase()}`, f.contact?.name]).join(" · "),
      body: tidy(f.note),
      meta: compact([
        f.author?.name,
        f.average != null ? `średnio ${formatAverage(f.average)}` : null,
        f.extension_outlook ? `przedłużenie: ${EXTENSION_LABELS[f.extension_outlook]}` : null,
      ]),
    });
  }
  const day = (iso: string) => warsawDateOf(iso) ?? iso.slice(0, 10);
  return items.sort((a, b) => day(b.on).localeCompare(day(a.on)) || b.on.localeCompare(a.on));
}

// ── Lewa kolumna: kompozytor i strumień ───────────────────────────────────────

type ComposerKind = "note" | "consultant" | "client";

const COMPOSER_KINDS: { value: ComposerKind; label: string; placeholder: string }[] = [
  { value: "note", label: "Notatka", placeholder: "Co warto zapamiętać przy tym kontrakcie?" },
  { value: "consultant", label: "Rozmowa z konsultantem", placeholder: "Co ustalono w rozmowie z konsultantem?" },
  { value: "client", label: "Rozmowa z klientem", placeholder: "Co ustalono z menedżerem u klienta?" },
];

function Composer({ nextPlan }: { nextPlan: PlanView | null }) {
  const [kind, setKind] = useState<ComposerKind>(nextPlan ? "consultant" : "note");
  const [text, setText] = useState("");
  const current = COMPOSER_KINDS.find((k) => k.value === kind) ?? COMPOSER_KINDS[0];
  const hint =
    kind === "consultant" && nextPlan
      ? `Zapis zaliczy punkt planu z ${fmtDate(nextPlan.due)}${nextPlan.overdueDays ? ` (zaległy ${plural(nextPlan.overdueDays, DNI)})` : ""}.`
      : kind === "note"
        ? "Notatka będzie też widoczna w profilu kandydata."
        : null;
  return (
    <div>
      <div className="rounded-lg border border-border bg-card transition-colors focus-within:border-primary">
        <label htmlFor="mk-care-composer" className="sr-only">
          Treść wpisu
        </label>
        <textarea
          id="mk-care-composer"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={current.placeholder}
          className="block w-full resize-none bg-transparent px-3 pt-2.5 text-[13px] leading-5 text-foreground outline-hidden placeholder:text-muted-foreground"
        />
        <div className="flex flex-wrap items-center gap-1.5 px-2 pb-2 pt-1">
          <div role="radiogroup" aria-label="Rodzaj wpisu" className="flex flex-wrap gap-1">
            {COMPOSER_KINDS.map((k) => (
              <button
                key={k.value}
                type="button"
                role="radio"
                aria-checked={kind === k.value}
                onClick={() => setKind(k.value)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[12px] transition-colors",
                  kind === k.value
                    ? "border-primary bg-primary/10 font-medium text-foreground"
                    : "border-border text-muted-foreground hover:bg-muted",
                )}
              >
                {k.label}
              </button>
            ))}
          </div>
          <span className="flex-1" />
          <Button type="button" size="sm">
            Zapisz
          </Button>
        </div>
      </div>
      {hint ? <p className="mt-1.5 text-[12px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Stream({ items }: { items: StreamItem[] }) {
  return (
    <ol className="divide-y divide-border/60" aria-label="Rozmowy i notatki">
      {items.map((item) => {
        const Icon = STREAM_ICON[item.kind];
        return (
          <li key={item.key} className="grid grid-cols-[28px_minmax(0,1fr)_auto] gap-3 py-3">
            <span className="inline-flex size-7 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Icon className="size-3.5" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-[13px] font-medium leading-5 text-foreground">{item.title}</p>
              {item.body ? (
                <p className="mt-0.5 line-clamp-3 whitespace-pre-line text-[13px] leading-5 text-foreground/85">{item.body}</p>
              ) : null}
              {item.meta.length ? <p className="mt-0.5 text-[12px] text-muted-foreground">{item.meta.join(" · ")}</p> : null}
            </div>
            <span className="pt-0.5 text-[12px] tabular-nums text-muted-foreground">{fmtDate(warsawDateOf(item.on))}</span>
          </li>
        );
      })}
    </ol>
  );
}

// ── Prawa kolumna ─────────────────────────────────────────────────────────────

function SideSection({
  title,
  meta,
  action,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2 px-4 py-3">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h3 className="flex items-baseline gap-2 text-[13px] font-semibold text-foreground">
          {title}
          {meta ? <span className="text-[12px] font-normal text-muted-foreground">{meta}</span> : null}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

export function PlanList({ rows, startOn }: { rows: PlanView[]; startOn: string | null }) {
  if (rows.length === 0) {
    return (
      <p className="text-[13px] text-muted-foreground">
        {startOn ? "Plan pojawi się, gdy kontrakt będzie aktywny." : "Kontrakt nie ma daty startu — plan liczy się od niej."}
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border/60">
      {rows.map((r) => {
        const when = planWhen(r);
        return (
          <li key={r.id} className="flex items-center justify-between gap-3 py-1.5">
            <StatusDot tone={when.tone} className={cn(r.status !== "open" && "opacity-70")}>
              {r.label}
            </StatusDot>
            <span className="shrink-0 text-right leading-4">
              <span className="block text-[12.5px] tabular-nums text-foreground">{fmtDate(r.due)}</span>
              <span className={cn("block text-[11.5px]", r.overdueDays ? "font-medium text-destructive" : "text-muted-foreground")}>
                {when.text}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function ValueRow({ label, value, note, tone = "neutral" }: { label: string; value: string; note?: string | null; tone?: KpiTone }) {
  // „—” z dopiskiem „bez oceny” czyta się jak dwa braki — zostaje sam dopisek.
  const empty = value === "—";
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-[13px]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">
        {empty ? (
          <span className="text-muted-foreground">{note ?? "—"}</span>
        ) : (
          <>
            <span className={cn("font-medium", KPI_TEXT[tone])}>{value}</span>
            {note ? <span className="text-muted-foreground"> · {note}</span> : null}
          </>
        )}
      </dd>
    </div>
  );
}

export function CaseRows({ cases }: { cases: CardCase[] }) {
  return (
    <ul className="divide-y divide-border/60">
      {openCases(cases).map((item) => {
        const pill = caseStatusPill(item);
        const when = caseWhen(item);
        const progress = item.checklist_total ? `lista ${item.checklist_done ?? 0}/${item.checklist_total}` : null;
        const body = (
          <>
            <span className="min-w-0">
              <span className="block truncate text-[13px] font-medium text-foreground" title={item.title}>
                {item.title}
              </span>
              <span className={CALM_SUBLINE}>{compact([caseMeta(item), progress]).join(" · ")}</span>
            </span>
            <span className="flex shrink-0 flex-col items-end gap-0.5">
              <StatusDot tone={CASE_DOT[pill.tone]}>{pill.label}</StatusDot>
              {when ? <span className="text-[11.5px] tabular-nums text-muted-foreground">{when}</span> : null}
            </span>
          </>
        );
        return (
          <li key={item.id}>
            {item.content_hidden ? (
              <div className="flex items-start justify-between gap-3 py-1.5">{body}</div>
            ) : (
              <Link
                href={`/people/cases/${item.id}`}
                className="-mx-1.5 flex items-start justify-between gap-3 rounded-md px-1.5 py-1.5 hover:bg-muted/50"
              >
                {body}
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function PickManager() {
  return (
    <button type="button" className="font-medium text-primary hover:underline">
      Wskaż menedżera
    </button>
  );
}

export function KnownProjectText({
  card,
  lineManager,
  quoteInStream = false,
}: {
  card: ConsultantCardData;
  lineManager: string | null;
  /** Cytat z karty technologicznej stoi już w strumieniu rozmów (wariant A) — bez powtórki. */
  quoteInStream?: boolean;
}) {
  const known = card.known_project;
  if (!known) {
    return (
      <div className="space-y-1 text-[13px]">
        <p className="text-muted-foreground">Nic jeszcze nie wiemy o projekcie — zapytaj przy najbliższej rozmowie.</p>
        <p className="text-muted-foreground">
          {lineManager ? (
            <>
              W kontrakcie wpisano line managera: <span className="text-foreground">{lineManager}</span>.{" "}
            </>
          ) : null}
          <PickManager />
        </p>
      </div>
    );
  }
  const team = teamText(known.team_size, known.team_externals, known.vendors);
  const source = known.source
    ? compact([
        known.source.kind === "tech_card" ? "z karty technologicznej" : "z rozmowy",
        fmtDate(known.source.on),
        known.source.author_name,
      ]).join(" · ")
    : "z kontraktu, bez rozmowy o projekcie";
  const hiringSource =
    known.hiring?.source && known.hiring.source in HIRING_SOURCE_LABELS
      ? HIRING_SOURCE_LABELS[known.hiring.source as HiringSource]
      : null;
  return (
    <div className="space-y-1.5 text-[13px]">
      <p className="text-[12px] text-muted-foreground">{source}</p>
      <p className="text-muted-foreground">
        {compact([
          known.area ? `Dział ${known.area.name}` : null,
          known.manager ? `menedżer ${known.manager.name}` : null,
          team,
          known.project_end_month ? `koniec projektu: ${fmtMonthYear(known.project_end_month)}` : null,
        ]).join(" · ")}
        {known.manager ? null : (
          <>
            {" · "}
            <PickManager />
          </>
        )}
      </p>
      {known.technologies.length ? (
        <ul className="flex flex-wrap gap-1" aria-label="Technologie w projekcie">
          {known.technologies.map((t) => (
            <li key={t.skill_id} className="rounded-md border border-border bg-muted/40 px-1.5 py-0.5 text-[12px]">
              {t.name}
            </li>
          ))}
        </ul>
      ) : null}
      {known.hiring ? (
        <p className="text-muted-foreground">
          Klient zatrudnia: <span className="text-foreground">{known.hiring.roles.join(", ") || "tak"}</span>
          {hiringSource ? ` (${hiringSource})` : ""}
        </p>
      ) : null}
      {known.quote && !(quoteInStream && known.source?.kind === "tech_card") ? (
        <p className="line-clamp-3 text-foreground/85">„{known.quote.trim()}”</p>
      ) : null}
    </div>
  );
}

function ChangeMenu({ nextPlan }: { nextPlan: PlanView | null }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline">
          Zmień
          <ChevronDown className="size-3.5" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem>Zmień opiekuna…</DropdownMenuItem>
        <DropdownMenuItem>Zmień rytm kontaktu…</DropdownMenuItem>
        {nextPlan ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem>Pomiń punkt planu z {fmtDate(nextPlan.due)}…</DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ── Zakładka ──────────────────────────────────────────────────────────────────

export function OpiekaA({ contractId }: TabProps) {
  const cardQuery = useMkCareCard(contractId);
  const card = asCard(cardQuery.data);
  const c = useMkContract(contractId).data;
  const notesQuery = useMkNotes(contractId);
  const detail = useMkCareDetail(contractId);
  const feedback = useMkCareFeedback(contractId);

  if (cardQuery.isLoading) return <p className="text-sm text-muted-foreground">Wczytywanie opieki…</p>;
  if (cardQuery.isError || !card) {
    return <p className="text-sm text-destructive">Nie udało się pobrać karty opieki tego kontraktu.</p>;
  }

  const notes = Array.isArray(notesQuery.data) ? (notesQuery.data as ContractTimelineItem[]) : [];
  const feedbackItems = feedback.data?.items ?? [];
  const stream = buildStream(notes, detail.data, feedbackItems);
  const streamLoading = notesQuery.isLoading || detail.isLoading;
  const streamFailed = notesQuery.isError && detail.isError;

  const rows = planRows(card);
  const nextPlan = rows.find((r) => r.status === "open") ?? null;
  const overdue = rows.filter((r) => r.overdueDays).length;
  const openCount = rows.filter((r) => r.status === "open").length;
  const sat = satisfactionKpi(card.kpis.satisfaction);
  const mgr = managerFeedbackKpi(card.kpis.manager_feedback, card.can_see_feedback);
  const latestFeedback = [...feedbackItems].sort((a, b) => b.held_on.localeCompare(a.held_on))[0] ?? null;
  const casesOpen = openCases(card.cases);
  const closedLine = closedCasesLine(card.cases);

  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
        <span>
          Opiekun: <span className="font-medium text-foreground">{card.owner.name ?? "bez opiekuna"}</span>
          {card.owner.source ? <span> ({OWNER_SOURCE_LABELS[card.owner.source]})</span> : null}
        </span>
        <span aria-hidden>·</span>
        <span>
          rytm: <span className="font-medium text-foreground">{card.cadence?.label ?? "nie ustalono"}</span>
          {card.cadence?.until_on ? ` do ${fmtDate(card.cadence.until_on)}` : null}
        </span>
        <span aria-hidden>·</span>
        <ChangeMenu nextPlan={nextPlan} />
      </p>

      <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] items-start gap-4">
        <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
          <div className="mb-3 flex items-baseline justify-between gap-2">
            <h2 className="text-[13.5px] font-semibold text-foreground">
              Rozmowy i notatki
              {stream.length ? <span className="ml-2 text-[12px] font-normal text-muted-foreground">{stream.length}</span> : null}
            </h2>
          </div>
          <Composer nextPlan={nextPlan} />
          <div className="mt-2">
            {streamLoading ? (
              <p className="py-3 text-[13px] text-muted-foreground">Wczytywanie rozmów i notatek…</p>
            ) : streamFailed ? (
              <p className="py-3 text-[13px] text-destructive">Nie udało się pobrać rozmów i notatek.</p>
            ) : stream.length === 0 ? (
              <p className="py-3 text-[13px] text-muted-foreground">
                Jeszcze nikt nie zapisał rozmowy. Rytm: {card.cadence?.label ?? "nie ustalono"}.
              </p>
            ) : (
              <Stream items={stream} />
            )}
          </div>
        </section>

        <aside className="divide-y divide-border/70 rounded-xl border border-border bg-card shadow-xs">
          <SideSection
            title="Plan kontaktów"
            meta={overdue ? `${overdue} zaległe` : openCount ? `${openCount} otwarte` : null}
          >
            <PlanList rows={rows} startOn={card.start_on} />
          </SideSection>

          <SideSection
            title="Zadowolenie i opinie"
            action={
              <Link href={`/clients/${card.client_id}?tab=struktura`} className="text-[12px] font-medium text-primary hover:underline">
                Struktura u klienta
              </Link>
            }
          >
            <dl className="divide-y divide-border/60">
              <ValueRow label="Zadowolenie konsultanta" value={sat.value} note={sat.note} tone={sat.tone} />
              <ValueRow label="Opinia menedżera" value={mgr.value} note={mgr.note} tone={mgr.tone} />
              <ValueRow
                label="Opinie klienta"
                value={
                  feedback.isError
                    ? "niedostępne"
                    : feedbackItems.length
                      ? plural(feedbackItems.length, ["opinia", "opinie", "opinii"])
                      : "brak"
                }
                note={latestFeedback ? `ostatnia ${fmtDate(latestFeedback.held_on)}` : null}
              />
            </dl>
          </SideSection>

          <SideSection
            title="Sprawy"
            meta={casesOpen.length ? `${casesOpen.length} otwarte` : null}
            action={
              <Button type="button" variant="ghost" size="sm" className="-mr-2 h-7">
                <Plus className="size-3.5" aria-hidden />
                Nowa sprawa
              </Button>
            }
          >
            {casesOpen.length ? (
              <CaseRows cases={card.cases} />
            ) : (
              <p className="text-[13px] text-muted-foreground">Brak otwartych spraw przy tym kontrakcie.</p>
            )}
            {closedLine ? <p className="text-[12px] text-muted-foreground">{closedLine}</p> : null}
          </SideSection>

          <SideSection title="Co wiemy o projekcie">
            <KnownProjectText card={card} lineManager={c?.line_manager ?? null} quoteInStream />
          </SideSection>
        </aside>
      </div>
    </div>
  );
}
