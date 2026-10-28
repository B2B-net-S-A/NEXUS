"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Flame } from "lucide-react";

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
import { useRequestBoard } from "@/lib/api/requestAllocation";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import { isP0Active, P0_DURATION_OPTIONS } from "@/lib/job-p0";

import { P0Chip } from "./P0Chip";
import { useNow } from "./useNow";

/** Ile P0 panel pokazuje od razu — 5 wierszy tabeli zajmuje cały ekran 1280 × 720. */
export const P0_PANEL_VISIBLE = 3;

function people(item: P0Job): string {
  const names = item.recruiters.map((name) => shortenPersonName(name) ?? name);
  if (names.length === 0) return "bez rekrutera";
  return names.join(", ");
}

function durationLabel(duration: P0Request["duration"]): string {
  return P0_DURATION_OPTIONS.find((option) => option.value === duration)?.label ?? duration;
}

/** Wiersz P0 spoza tablicy requestów (np. rekrutacja z championem, nie „Szukamy”). */
function FallbackRow({ item }: { item: P0Job }) {
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
 */
export function P0NowPanel({ className }: { className?: string }) {
  const now = useNow();
  const query = useP0Jobs();
  const board = useRequestBoard({ enabled: query.isSuccess });
  const [expanded, setExpanded] = useState(false);
  const items = (query.data?.items ?? []).filter((item) =>
    isP0Active({ is_p0: true, p0_until: item.p0_until }, now),
  );
  const requests = query.data?.requests ?? [];
  const boardIds = useMemo(
    () => new Set((board.data?.requests ?? []).map((request) => request.job_id)),
    [board.data?.requests],
  );
  if (!query.isSuccess || (items.length === 0 && requests.length === 0)) return null;
  const shown = expanded ? items : items.slice(0, P0_PANEL_VISIBLE);
  const hidden = items.length - shown.length;
  // Zanim tablica requestów przyjdzie (albo gdy jej zapytanie padnie), wiersze
  // P0 rysują się po staremu — panel nie może zniknąć przez cudzą awarię.
  const inBoard = board.isSuccess
    ? new Set(shown.filter((item) => boardIds.has(item.job_id)).map((item) => item.job_id))
    : new Set<number>();
  const outside = shown.filter((item) => !inBoard.has(item.job_id));
  return (
    <section
      aria-label="P0 — ultrapilne teraz"
      className={
        "grid gap-2 rounded-xl border border-destructive/35 bg-destructive-muted p-3 " +
        (className ?? "")
      }
      data-testid="p0-now-panel"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-destructive-muted-foreground">
        <h2 className="flex items-center gap-1.5 text-base font-bold">
          <Flame className="h-4 w-4" aria-hidden="true" />
          P0 — ultrapilne teraz · {items.length}
        </h2>
        <p className="text-xs">Najpierw te rekrutacje, potem reszta.</p>
        <p className="text-xs sm:ml-auto">
          {query.data.can_set
            ? "Widzisz wszystkie P0 · zespół widzi swoje"
            : "P0 Twoich rekrutacji · ustawia Head of Recruitment"}
        </p>
      </div>
      {requests.length > 0 ? (
        <P0Requests requests={requests} canDecide={query.data.can_set} />
      ) : null}
      {inBoard.size > 0 ? <RequestBoard onlyJobIds={inBoard} /> : null}
      {outside.length > 0 ? (
        <ul className="grid gap-2">
          {outside.map((item) => (
            <FallbackRow key={item.job_id} item={item} />
          ))}
        </ul>
      ) : null}
      {items.length > P0_PANEL_VISIBLE ? (
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
