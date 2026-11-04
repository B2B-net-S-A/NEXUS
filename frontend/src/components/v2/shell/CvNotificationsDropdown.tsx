"use client";

// Ikona „CV” w górnym pasku (16.10.2026, zamiast pigułki „Do wysłania”).
//
// Liczy STAN, nie zdarzenia (`GET /api/board-tasks/cv`): wiersz znika, gdy
// karta pójdzie dalej. Rekruter widzi swoje CV w rekrutacjach (do sprawdzenia,
// do poprawy, u Delivery Leada, wysłane), Delivery Lead — tę samą kolejkę „Do
// wysłania do klienta” co dotychczasowa pigułka i jej kolor pilności.
// Okienko nie importuje przeglądu — wiersze prowadzą na Tablicę.

import { useState, type ButtonHTMLAttributes } from "react";
import Link from "next/link";
import { ArrowRight, FileUser } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  CPRO_ROW_BADGE,
  CPRO_ROW_HINT,
  useCvTopic,
  waitingFor,
  type CvCheckRow,
  type CvTopicResponse,
  type CvTransitRow,
  type DlSendRow,
  type DlSendUrgency,
} from "@/lib/api/boardTasks";
import {
  CV_TRANSIT_RETURNED_LABEL,
  transitAgo,
  transitFixList,
  transitJobLabel,
  transitRemark,
  transitReturnedDetail,
  transitRowWho,
} from "@/lib/cv-in-transit";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";
import { useRealtimeStatus } from "@/store/realtime";
import {
  DL_SEND_DASHBOARD_HREF,
  DL_SEND_SEQUENCE_HREF,
  dlSendReviewHref,
} from "./DlSendTopbarButton";

const PILL_TONE: Record<DlSendUrgency, string> = {
  fresh: "bg-primary text-primary-foreground",
  due: "bg-warning text-warning-foreground",
  late: "bg-destructive text-destructive-foreground",
};

const WAIT_TONE: Record<DlSendUrgency, string> = {
  fresh: "text-muted-foreground",
  due: "font-semibold text-warning",
  late: "font-semibold text-destructive",
};

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

function cardHref(row: { job_id: number; candidate_id: number }, panel?: "cv"): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}${panel ? `&panel=${panel}` : ""}`;
}

function jobLabel(row: CvCheckRow | DlSendRow): string {
  const title = row.job_working_title?.trim() || row.job_title;
  return row.client_name ? `${title} · ${row.client_name}` : title;
}

interface CvTopbarButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  badge: number;
  /** Pilność kolejki Delivery Leada — wtedy ikona ma formę pigułki. */
  urgency: DlSendUrgency | null;
  open?: boolean;
}

/** Sam przycisk paska — bez zapytań (także w harnessie). */
export function CvTopbarButton({
  badge,
  urgency,
  open = false,
  className,
  ref,
  ...props
}: CvTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  const label = badge > 0 ? `CV — czekają na Ciebie: ${badge}` : "CV";
  if (urgency && badge > 0) {
    return (
      <button
        ref={ref}
        type="button"
        aria-label={label}
        title="CV — Twoje CV w rekrutacjach"
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold tabular-nums transition-shadow pointer-coarse:min-h-10",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          PILL_TONE[urgency],
          open && "ring-2 ring-ring ring-offset-2 ring-offset-background",
          className,
        )}
        {...props}
      >
        <FileUser className="h-3.5 w-3.5" aria-hidden />
        <span>{countLabel(badge)}</span>
      </button>
    );
  }
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title="CV — Twoje CV w rekrutacjach"
      className={cn(
        "relative rounded-lg p-2 transition-colors",
        open
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
        className,
      )}
      {...props}
    >
      <FileUser className="h-5 w-5" aria-hidden />
      {badge > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-xs font-bold text-primary-foreground tabular-nums">
          {countLabel(badge)}
        </span>
      ) : null}
    </button>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title}>
      <h3 className="flex items-center gap-1.5 px-4 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
        {count ? (
          <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[11px] font-bold normal-case tracking-normal text-primary-foreground tabular-nums">
            {countLabel(count)}
          </span>
        ) : null}
      </h3>
      <ul className="divide-y divide-border">{children}</ul>
    </section>
  );
}

function Row({
  href,
  onNavigate,
  name,
  badge,
  lines,
  meta,
  metaClassName,
}: {
  href: string;
  onNavigate: () => void;
  name: string;
  /** Plakietka przy nazwisku (Nordea „do Cpro”) — dopisek na końcu linii
   *  rekrutacji ucinał się w okienku 384 px (14.10.2026). */
  badge?: React.ReactNode;
  lines: (string | null)[];
  meta: string;
  metaClassName?: string;
}) {
  return (
    <li>
      <Link
        href={href}
        onClick={onNavigate}
        className="flex items-start gap-3 px-4 py-2 transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
      >
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-sm font-medium text-foreground" title={name}>
              {name}
            </span>
            {badge}
          </span>
          {lines
            .filter((line): line is string => Boolean(line))
            .map((line) => (
              <span key={line} className="block truncate text-xs text-muted-foreground">
                {line}
              </span>
            ))}
        </span>
        <span className={cn("shrink-0 pt-0.5 text-xs tabular-nums text-muted-foreground", metaClassName)}>
          {meta}
        </span>
      </Link>
    </li>
  );
}

function fixLines(row: CvTransitRow): (string | null)[] {
  if (row.kind === "in_review") {
    return [transitJobLabel(row), "QC CV do poprawy"];
  }
  const label =
    row.kind === "sent_back" || row.kind === "cpro_returned"
      ? CV_TRANSIT_RETURNED_LABEL[row.kind]
      : null;
  const detail = transitReturnedDetail(row);
  return [
    transitJobLabel(row),
    [label, detail].filter(Boolean).join(" · ") || null,
    transitRemark(row) ?? transitFixList(row),
  ];
}

export interface CvPanelProps {
  data: CvTopicResponse;
  onNavigate: () => void;
}

/** Treść okienka „CV” — bez zapytań, dane w propsach (także w harnessie). */
export function CvPanel({ data, onNavigate }: CvPanelProps) {
  const { recruiter, dl } = data;
  const empty =
    (!dl || (dl.to_send_total === 0 && dl.sent_today.length === 0)) &&
    (!recruiter ||
      recruiter.to_check.length +
        recruiter.to_fix.length +
        recruiter.with_dl.length +
        recruiter.sent.length ===
        0);
  return (
    <div className="flex max-h-[min(560px,calc(100dvh-6rem))] flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">CV</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {dl ? "CV w rekrutacjach, które prowadzisz" : "Twoje CV w rekrutacjach"}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-2">
        {empty ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            Żadne CV nie czeka na Ciebie. Tu zobaczysz CV do sprawdzenia, do poprawy
            i wysłane do klienta.
          </p>
        ) : null}

        {dl && dl.to_send_total > 0 ? (
          <Section title="Do wysłania do klienta" count={dl.to_send_total}>
            {dl.to_send.map((row) => (
              <Row
                key={`send:${row.stage_id}`}
                href={dlSendReviewHref(row)}
                onNavigate={onNavigate}
                name={row.candidate_name}
                badge={
                  row.cpro ? (
                    <Badge size="sm" variant="info" title={CPRO_ROW_HINT} className="shrink-0">
                      {CPRO_ROW_BADGE}
                    </Badge>
                  ) : null
                }
                lines={[
                  jobLabel(row),
                  row.handed_over_by_name ? `przekazał(a) ${row.handed_over_by_name}` : null,
                ]}
                meta={waitingFor(row.ready_since)}
                metaClassName={WAIT_TONE[row.urgency]}
              />
            ))}
          </Section>
        ) : null}
        {dl && dl.to_send_total > dl.to_send.length ? (
          <p className="px-4 pt-1 text-xs text-muted-foreground">
            Pokazano {dl.to_send.length} z {dl.to_send_total} — najdłużej czekające.
          </p>
        ) : null}
        {dl && dl.with_recruiters_total > 0 ? (
          <p className="px-4 pt-2 text-xs text-muted-foreground">
            {countPl(dl.with_recruiters_total, "osoba", "osoby", "osób")} w „QC CV” jeszcze
            u rekruterów (QC do poprawy).
          </p>
        ) : null}

        {recruiter && recruiter.to_check.length > 0 ? (
          <Section title="Do sprawdzenia" count={recruiter.to_check.length}>
            {recruiter.to_check.map((row) => (
              <Row
                key={`check:${row.stage_id}`}
                href={cardHref(row, "cv")}
                onNavigate={onNavigate}
                name={row.candidate_name}
                lines={[jobLabel(row), "Automat zrobił CV firmowe"]}
                meta={transitAgo(row.since)}
              />
            ))}
          </Section>
        ) : null}
        {recruiter && recruiter.to_fix.length > 0 ? (
          <Section title="Do poprawy" count={recruiter.to_fix.length}>
            {recruiter.to_fix.map((row) => (
              <Row
                key={`fix:${row.stage_id}`}
                href={cardHref(row, "cv")}
                onNavigate={onNavigate}
                name={row.candidate_name}
                lines={fixLines(row)}
                meta={transitAgo(row.since)}
              />
            ))}
          </Section>
        ) : null}
        {recruiter && recruiter.with_dl.length > 0 ? (
          <Section title="U Delivery Leada">
            {recruiter.with_dl.map((row) => (
              <Row
                key={`dl:${row.stage_id}`}
                href={cardHref(row)}
                onNavigate={onNavigate}
                name={row.candidate_name}
                lines={[transitJobLabel(row), transitRowWho(row)]}
                meta={transitAgo(row.since)}
              />
            ))}
          </Section>
        ) : null}
        {dl && dl.sent_today.length > 0 ? (
          <Section title="Wysłane dziś">
            {dl.sent_today.map((row) => (
              <Row
                key={`today:${row.stage_id}`}
                href={cardHref(row)}
                onNavigate={onNavigate}
                name={row.candidate_name}
                lines={[transitJobLabel(row), transitRowWho(row)]}
                meta={transitAgo(row.since)}
              />
            ))}
          </Section>
        ) : null}
        {recruiter && recruiter.sent.length > 0 ? (
          <Section title="Wysłane do klienta">
            {recruiter.sent.map((row) => (
              <Row
                key={`sent:${row.stage_id}`}
                href={cardHref(row)}
                onNavigate={onNavigate}
                name={row.candidate_name}
                lines={[transitJobLabel(row), transitRowWho(row)]}
                meta={transitAgo(row.since)}
              />
            ))}
          </Section>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-muted/40 px-4 py-2.5 text-xs font-medium">
        {dl && dl.to_send_total >= 2 ? (
          <Link
            href={DL_SEND_SEQUENCE_HREF}
            onClick={onNavigate}
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            Przejrzyj po kolei ({dl.to_send_total})
          </Link>
        ) : null}
        <Link
          href={dl ? DL_SEND_DASHBOARD_HREF : "/dashboard"}
          onClick={onNavigate}
          className="text-primary hover:underline"
        >
          Całość na pulpicie
        </Link>
      </div>
    </div>
  );
}

/**
 * Ikona „CV” w górnym pasku — u rekrutera i Delivery Leada. Bez danych nie
 * ma ikony (brak wiedzy to nie zero); przy zerze ikona zostaje, bez liczby.
 */
export function CvNotificationsDropdown() {
  const user = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const setOpenTopic = useRealtimeStatus((s) => s.setOpenTopic);
  const enabled = hasRole(user, "recruiter", "delivery_lead");
  const data = useCvTopic(enabled).data;
  if (!data || (!data.recruiter && !data.dl)) return null;

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    setOpenTopic(next ? "cv" : null);
  };
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <CvTopbarButton
          badge={data.badge}
          urgency={data.dl && data.dl.to_send_total > 0 ? data.dl.worst_urgency : null}
          open={open}
        />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 overflow-hidden p-0">
        <CvPanel data={data} onNavigate={() => onOpenChange(false)} />
      </PopoverContent>
    </Popover>
  );
}
