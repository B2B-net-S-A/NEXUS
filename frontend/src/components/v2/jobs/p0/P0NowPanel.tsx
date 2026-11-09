"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Flame } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { RequestBoard } from "@/components/v2/request-board/RequestBoard";
import { apiErrorMessage } from "@/lib/api-error";
import {
  approveJobP0Request,
  invalidateP0,
  rejectJobP0Request,
  useP0Jobs,
  type P0Job,
  type P0Request,
} from "@/lib/api/jobP0";
import { useRequestBoard, type BoardRequest } from "@/lib/api/requestAllocation";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import {
  isP0Active,
  isP0Overdue,
  p0OverdueLabel,
  p0Remaining,
  P0_DURATION_OPTIONS,
} from "@/lib/job-p0";

import { P0Chip } from "./P0Chip";
import { P0OverdueActions } from "./P0OverdueActions";

/** Ile P0 panel pokazuje od razu — 5 wierszy tabeli zajmuje cały ekran 1280 × 720.
 *  W pasku na pulpicie to liczba P0 w linii. */
export const P0_PANEL_VISIBLE = 3;

function people(item: P0Job): string {
  const names = item.recruiters.map((name) => shortenPersonName(name) ?? name);
  if (names.length === 0) return "bez rekrutera";
  return names.join(", ");
}

function durationLabel(duration: P0Request["duration"]): string {
  return P0_DURATION_OPTIONS.find((option) => option.value === duration)?.label ?? duration;
}

const NO_BOARD: ReadonlyMap<number, BoardRequest> = new Map();

function lineMeta(item: P0Job, request: BoardRequest | undefined): string {
  const time = isP0Overdue(item)
    ? p0OverdueLabel(item.p0_until)
    : `zostało ${p0Remaining(item.p0_until) ?? "chwilę"}`;
  return typeof request?.sent === "number" ? `${time} · wysłani ${request.sent}` : time;
}

function lineTitle(item: P0Job, request: BoardRequest | undefined): string {
  if (!request?.title) return item.title;
  return [request.client_reference, request.title].filter(Boolean).join(" ");
}

/** Pasek jednej linii (audyt 2, 08.11.2026): na ekranie 1280 × 720 pod nim zaczyna się kolejka roli. */
function P0Line({
  items,
  boardById,
  open,
  onToggle,
}: {
  items: P0Job[];
  boardById: ReadonlyMap<number, BoardRequest>;
  open: boolean;
  onToggle: () => void;
}) {
  const inLine = items.slice(0, P0_PANEL_VISIBLE);
  const rest = items.length - inLine.length;
  return (
    <div
      className="flex min-w-0 items-center gap-3 text-destructive-muted-foreground"
      data-testid="p0-now-line"
    >
      <h2 className="flex shrink-0 items-center gap-1.5 text-sm font-bold">
        <Flame className="h-4 w-4" aria-hidden="true" />
        Pilne u klientów · {items.length}
      </h2>
      {open ? null : (
        <>
          {/* Równe szerokości: krótki tytuł obok długich nie może skurczyć się do
              zera i wjechać czasem na sąsiada. Na telefonie linia mieści sam
              nagłówek — P0 są pod „Pokaż tabelę”. */}
          <ul className="hidden min-w-0 flex-1 items-center gap-4 sm:flex">
            {inLine.map((item) => {
              const request = boardById.get(item.job_id);
              const title = lineTitle(item, request);
              return (
                <li key={item.job_id} className="min-w-0 flex-1">
                  <Link
                    href={`/jobs/${item.job_id}`}
                    title={item.p0_reason ? `${title} — „${item.p0_reason}”` : title}
                    className="flex min-w-0 items-baseline gap-1 text-xs hover:underline"
                  >
                    <span className="truncate font-semibold">{title}</span>
                    <span className="shrink-0 whitespace-nowrap">({lineMeta(item, request)})</span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {rest > 0 ? <span className="hidden shrink-0 text-xs font-semibold sm:inline">+{rest}</span> : null}
        </>
      )}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        data-tour="dashboard.p0-line"
        className="ml-auto flex shrink-0 items-center gap-0.5 whitespace-nowrap text-xs font-medium underline-offset-2 hover:underline"
      >
        {open ? "Zwiń tabelę" : "Pokaż tabelę"}
        <ChevronDown className={"h-3.5 w-3.5 " + (open ? "rotate-180" : "")} aria-hidden="true" />
      </button>
    </div>
  );
}

/** Wiersz P0 spoza tablicy requestów (np. rekrutacja z championem, nie „Szukamy”). */
function FallbackRow({ item, canDecide }: { item: P0Job; canDecide: boolean }) {
  return (
    <li
      className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 rounded-lg border border-destructive/25 bg-card px-3 py-2 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
      data-testid="p0-now-row"
    >
      <P0Chip until={item.p0_until} reason={item.p0_reason} />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold" title={item.title}>
          {item.title}
          {item.client_name ? (
            <span className="font-normal text-muted-foreground"> · {item.client_name}</span>
          ) : null}
        </p>
        <p className="break-words text-xs text-muted-foreground">
          {item.p0_reason ? `„${item.p0_reason}”` : null}
          {item.p0_set_by_name
            ? ` — ${shortenPersonName(item.p0_set_by_name) ?? item.p0_set_by_name}`
            : null}
          {" · "}
          {people(item)}
          {item.delivery_lead_name
            ? ` · DL: ${shortenPersonName(item.delivery_lead_name) ?? item.delivery_lead_name}`
            : null}
        </p>
        {/* 06.11.2026: P0 po terminie trwa do decyzji Head of Recruitment. */}
        {isP0Overdue(item) ? (
          <P0OverdueActions jobId={item.job_id} canDecide={canDecide} className="mt-1" />
        ) : null}
      </div>
      <Button asChild size="sm" variant="outline" className="col-span-2 justify-self-start bg-card sm:col-span-1">
        <Link href={`/jobs/${item.job_id}`}>Otwórz tablicę</Link>
      </Button>
    </li>
  );
}

/** Prośby Delivery Leadów o P0 (28.10.2026): HoR zatwierdza, DL widzi swoją. */
function P0Requests({ requests, canDecide }: { requests: P0Request[]; canDecide: boolean }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);
  const decide = async (request: P0Request, approve: boolean) => {
    setBusy(request.job_id);
    try {
      await (approve ? approveJobP0Request(request.job_id) : rejectJobP0Request(request.job_id));
      invalidateP0(queryClient, request.job_id);
      toast.showSuccess(
        approve
          ? "P0 ustawione. Zespół rekrutacji dostał powiadomienie i mail."
          : canDecide
            ? "Prośba o P0 odrzucona."
            : "Prośba o P0 wycofana.",
      );
    } catch (err) {
      toast.showError(apiErrorMessage(err, "Nie udało się zapisać decyzji o P0."));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="grid gap-1.5" data-testid="p0-requests">
      <p className="text-xs font-semibold text-destructive-muted-foreground">
        {canDecide ? `Prośby o P0 · ${requests.length}` : "Twoja prośba o P0 czeka na Head of Recruitment"}
      </p>
      <ul className="grid gap-1.5">
        {requests.map((request) => (
          <li
            key={request.job_id}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-dashed border-destructive/40 bg-card px-3 py-2"
            data-testid="p0-request-row"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm">
                {canDecide && request.requested_by_name ? (
                  <span className="font-semibold">
                    {shortenPersonName(request.requested_by_name) ?? request.requested_by_name} prosi o P0 na{" "}
                    {durationLabel(request.duration)}:{" "}
                  </span>
                ) : null}
                <Link href={`/jobs/${request.job_id}`} className="font-semibold hover:underline">
                  {request.title}
                </Link>
                {request.client_name ? (
                  <span className="text-muted-foreground"> · {request.client_name}</span>
                ) : null}
              </p>
              <p className="break-words text-xs text-muted-foreground">„{request.reason}”</p>
            </div>
            <span className="flex shrink-0 gap-1.5">
              {canDecide ? (
                <Button
                  size="sm"
                  variant="destructive"
                  loading={busy === request.job_id}
                  disabled={busy !== null}
                  onClick={() => void decide(request, true)}
                >
                  Zatwierdź P0
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                className="bg-card"
                disabled={busy !== null}
                onClick={() => void decide(request, false)}
              >
                {canDecide ? "Odrzuć" : "Wycofaj"}
              </Button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Panel „P0 — ultrapilne teraz” (27.10.2026) — na górze pulpitu, nad
 * kafelkami i niezależnie od własnego układu, oraz na Daily. Znika, gdy nie
 * ma żadnego P0 ani prośby; błąd zapytania (np. konto bez sekcji Rekrutacje)
 * też go chowa, bo panel nie jest jedynym miejscem P0.
 *
 * Propozycje Olafa (28.10.2026): serwer oddaje tylko P0 zespołów patrzącego
 * (Head of Recruitment i admin — wszystkie), wiersze są te same co tabela
 * requestów z Daily (Zweryf., QC CV, Wysłani, rekruterzy), a nad nimi stoją
 * prośby Delivery Leadów o P0.
 *
 * `compact` (audyt 2, wariant A Artura, 08.11.2026) — pulpit: P0 dalej nad
 * wszystkim, ale jako pasek jednej linii, żeby na 1280 × 720 kolejka roli
 * stała na pierwszym ekranie. Tabela wszystkich P0 po „Pokaż tabelę”,
 * rekruterzy w niej jako licznik. Prośby o P0 zostają rozwinięte: to decyzja
 * do podjęcia, a nie informacja. Daily zostaje przy pełnej tabeli.
 */
export function P0NowPanel({ className, compact = false }: { className?: string; compact?: boolean }) {
  const query = useP0Jobs();
  const board = useRequestBoard({ enabled: query.isSuccess });
  const [expanded, setExpanded] = useState(false);
  const [tableOpen, setTableOpen] = useState(false);
  const items = (query.data?.items ?? []).filter((item) =>
    isP0Active({ is_p0: true, p0_until: item.p0_until }),
  );
  const requests = query.data?.requests ?? [];
  const boardById = useMemo(
    () => new Map((board.data?.requests ?? []).map((request) => [request.job_id, request])),
    [board.data?.requests],
  );
  if (!query.isSuccess || (items.length === 0 && requests.length === 0)) return null;
  const tableHidden = compact && !tableOpen;
  const shown = tableHidden ? [] : expanded || compact ? items : items.slice(0, P0_PANEL_VISIBLE);
  const hidden = items.length - shown.length;
  // Zanim tablica requestów przyjdzie (albo gdy jej zapytanie padnie), wiersze
  // P0 rysują się po staremu — panel nie może zniknąć przez cudzą awarię.
  const inBoard = board.isSuccess
    ? new Set(shown.filter((item) => boardById.has(item.job_id)).map((item) => item.job_id))
    : new Set<number>();
  const outside = shown.filter((item) => !inBoard.has(item.job_id));
  return (
    <section
      aria-label="P0 — ultrapilne teraz"
      className={
        "grid gap-2 rounded-xl border border-destructive/35 bg-destructive-muted " +
        (compact ? "px-3 py-2.5 " : "p-3 ") +
        (className ?? "")
      }
      data-testid="p0-now-panel"
    >
      {compact ? (
        items.length > 0 ? (
          <P0Line
            items={items}
            boardById={board.isSuccess ? boardById : NO_BOARD}
            open={tableOpen}
            onToggle={() => setTableOpen((value) => !value)}
          />
        ) : null
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-destructive-muted-foreground">
          <h2 className="flex items-center gap-1.5 text-base font-bold">
            <Flame className="h-4 w-4" aria-hidden="true" />
            Pilne u klientów · {items.length}
          </h2>
          <p className="text-xs">Termin klienta jest najbliżej.</p>
          <p className="text-xs sm:ml-auto">
            {query.data.can_set
              ? "Widzisz wszystkie P0 · zespół widzi swoje"
              : "Twoje rekrutacje"}
          </p>
        </div>
      )}
      {requests.length > 0 ? (
        <P0Requests requests={requests} canDecide={query.data.can_set} />
      ) : null}
      {inBoard.size > 0 ? <RequestBoard onlyJobIds={inBoard} recruitersAsCount={compact} /> : null}
      {outside.length > 0 ? (
        <ul className="grid gap-2">
          {outside.map((item) => (
            <FallbackRow key={item.job_id} item={item} canDecide={query.data.can_set} />
          ))}
        </ul>
      ) : null}
      {!compact && items.length > P0_PANEL_VISIBLE ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="w-fit text-xs font-medium text-destructive-muted-foreground underline-offset-2 hover:underline"
          data-testid="p0-now-toggle"
        >
          {expanded ? "Pokaż mniej" : `Pokaż wszystkie · jeszcze ${hidden}`}
        </button>
      ) : null}
    </section>
  );
}
