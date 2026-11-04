"use client";

// Licznik „Do wysłania” w górnym pasku (13.10.2026) — ile osób czeka na
// wysyłkę do klienta u patrzącego Delivery Leada.
//
// To NIE jest drugi dzwonek. Dzwonek liczy zdarzenia: wpis „CV do przeglądu”
// przychodzi raz i znika po przeczytaniu, choć osoba dalej czeka (pomiar
// 13.10.2026: 34 wpisy w 30 dni, przeczytane 2). Ten licznik liczy STAN
// kolejki (`GET /api/board-tasks/dl-send`): maleje dopiero po wysłaniu,
// odrzuceniu albo cofnięciu karty do poprawy. Przy pustej kolejce i u kont
// bez roli Delivery Leada go nie ma.
//
// Okienko nie importuje przeglądu (pdf.js, podgląd DOCX) — wiersz prowadzi na
// Tablicę z otwartym przeglądem (`?review=1`), a „po kolei” na pulpit.

import { forwardRef, useState, type ButtonHTMLAttributes } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight, Send } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  CPRO_ROW_BADGE,
  CPRO_ROW_HINT,
  useDlSendQueue,
  waitingFor,
  type DlSendQueueResponse,
  type DlSendRow,
  type DlSendUrgency,
} from "@/lib/api/boardTasks";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

/** Start przeglądu „po kolei” na pulpicie (`DlSendQueueBand` czyta parametr raz). */
export const DL_SEND_SEQUENCE_HREF = "/dashboard?wysylka=po-kolei";
export const DL_SEND_DASHBOARD_HREF = "/dashboard#do-wyslania";
/** Zakres „Otwarte”, nie „Moje”: przegląd z portfela klienta dotyczy też
 *  rekrutacji, w których Delivery Lead nie jest wpisany. */
export const DL_SEND_JOBS_HREF = "/jobs?open=1&tosend=mine";

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

const URGENCY_HINT: Record<DlSendUrgency, string> = {
  fresh: "",
  due: " — ktoś czeka od wczoraj",
  late: " — ktoś czeka 2+ dni robocze",
};

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

export function dlSendReviewHref(row: Pick<DlSendRow, "job_id" | "candidate_id">): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}&review=1`;
}

interface DlSendPillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  total: number;
  urgency: DlSendUrgency | null;
  open?: boolean;
}

/** Sam przycisk paska — bez zapytań (także w harnessie). */
export const DlSendPill = forwardRef<HTMLButtonElement, DlSendPillProps>(function DlSendPill(
  { total, urgency, open = false, className, ...props },
  ref,
) {
  const tone = urgency ?? "fresh";
  return (
    <button
      ref={ref}
      type="button"
      aria-label={`Do wysłania do klienta: ${countPl(total, "osoba", "osoby", "osób")}${URGENCY_HINT[tone]}`}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold tabular-nums transition-shadow pointer-coarse:min-h-10",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        PILL_TONE[tone],
        open && "ring-2 ring-ring ring-offset-2 ring-offset-background",
        className,
      )}
      {...props}
    >
      <Send className="h-3.5 w-3.5" aria-hidden />
      {/* Pełna etykieta dopiero od 1680 px. Zmierzone 13.10.2026 na replice
          paska (`/preview/kpi-topbar`): przy 1536 px z przypiętym menu, długimi
          okruszkami i pigułką „Rozmowy” etykieta przelewała pasek o 6 px. Niżej
          zostaje ikona z liczbą. */}
      <span className="hidden min-[1680px]:inline">Do wysłania ·</span>
      <span>{countLabel(total)}</span>
    </button>
  );
});

export interface DlSendPanelProps {
  queue: DlSendQueueResponse;
  onNavigate: () => void;
  /** Patrzący jest już na liście rekrutacji. Lista czyta filtry z adresu tylko
   *  przy wejściu, więc link „miękki” zmieniłby sam adres — wtedy idzie zwykłe
   *  przejście z przeładowaniem. */
  onJobsList?: boolean;
}

/** Treść okienka — bez zapytań, dane w propsach (także w harnessie). */
export function DlSendPanel({ queue, onNavigate, onJobsList = false }: DlSendPanelProps) {
  const others = [
    queue.not_ready_total > 0 ? `${queue.not_ready_total} jeszcze u rekrutera` : null,
    queue.imported_total > 0 ? `${queue.imported_total} z Traffita` : null,
  ].filter((part): part is string => part !== null);
  return (
    <div className="flex max-h-[min(520px,calc(100dvh-6rem))] flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">Do wysłania do klienta</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {countPl(queue.ready_total, "gotowa", "gotowe", "gotowych")}
          {others.length > 0 ? ` · ${others.join(" · ")}` : ""}
        </p>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        {queue.ready.map((row) => (
          <li key={row.stage_id}>
            <Link
              href={dlSendReviewHref(row)}
              onClick={onNavigate}
              className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
            >
              <span className="min-w-0 flex-1">
                {/* Nordea (14.10.2026): plakietka przy nazwisku — dopisek na
                    końcu linii rekrutacji ucinał się w okienku 384 px. */}
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-foreground" title={row.candidate_name}>
                    {row.candidate_name}
                  </span>
                  {row.cpro ? (
                    <Badge size="sm" variant="info" title={CPRO_ROW_HINT} className="shrink-0">
                      {CPRO_ROW_BADGE}
                    </Badge>
                  ) : null}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {row.job_working_title?.trim() || row.job_title}
                  {row.client_name ? ` · ${row.client_name}` : ""}
                  {row.handed_over_by_name ? ` · przekazał(a) ${row.handed_over_by_name}` : ""}
                </span>
              </span>
              <span className={cn("shrink-0 text-xs tabular-nums", WAIT_TONE[row.urgency])}>
                {waitingFor(row.ready_since)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {queue.ready_total > queue.ready.length ? (
        <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
          Pokazano {queue.ready.length} z {queue.ready_total} — najdłużej czekające.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-muted/40 px-4 py-2.5 text-xs font-medium">
        {queue.ready_total >= 2 ? (
          <Link
            href={DL_SEND_SEQUENCE_HREF}
            onClick={onNavigate}
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            Przejrzyj po kolei ({queue.ready_total})
          </Link>
        ) : null}
        <Link href={DL_SEND_DASHBOARD_HREF} onClick={onNavigate} className="text-primary hover:underline">
          Cała lista na pulpicie
        </Link>
        {onJobsList ? (
          <a href={DL_SEND_JOBS_HREF} className="text-primary hover:underline">
            Pokaż rekrutacje
          </a>
        ) : (
          <Link href={DL_SEND_JOBS_HREF} onClick={onNavigate} className="text-primary hover:underline">
            Pokaż rekrutacje
          </Link>
        )}
      </div>
    </div>
  );
}

export function DlSendTopbarButton() {
  const user = useAuthStore((s) => s.user);
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const queue = useDlSendQueue(hasRole(user, "delivery_lead")).data;
  // Bez danych nie ma licznika — brak wiedzy to nie zero. Zero też go chowa:
  // pasek ma mówić „masz kogo wysłać”, nie „sprawdź, czy masz”.
  if (!queue || queue.ready_total <= 0) return null;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <DlSendPill total={queue.ready_total} urgency={queue.worst_urgency} open={open} />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 overflow-hidden p-0">
        <DlSendPanel queue={queue} onNavigate={() => setOpen(false)} onJobsList={pathname === "/jobs"} />
      </PopoverContent>
    </Popover>
  );
}
