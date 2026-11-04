"use client";

/**
 * Wiersze dziennika ruchów (`GET /api/pipeline/job/{id}/moves`) — wspólne dla
 * okna „Historia i czat” (cała rekrutacja) i panelu osoby (jedna para,
 * `?candidate_id=`), żeby ruch wyglądał tak samo w obu miejscach.
 */

import Link from "next/link";

import { formatDate } from "@/lib/utils";

export interface JobMoveLogItem {
  id: number;
  candidate_id: number;
  /** `null` = rola bez odczytu kandydatów (nazwiska zredagowane). */
  candidate_name: string | null;
  from_stage_name: string | null;
  to_stage_name: string | null;
  moved_by_name: string | null;
  moved_at: string | null;
  source: "traffit" | "nexus" | (string & {});
}

export interface JobMoveLogPage {
  items: JobMoveLogItem[];
  total: number;
  next_offset?: number | null;
}

export const jobMovesQueryKey = (jobId: number) => ["job-pipeline-moves", jobId] as const;

/**
 * Ruchy jednej osoby w rekrutacji. Dziennika nikt nie unieważnia po ruchu, więc
 * wołający dokłada do klucza id wiersza etapu karty — po ruchu to nowy klucz.
 */
export const pairMovesQueryKey = (jobId: number, candidateId: number) =>
  [...jobMovesQueryKey(jobId), candidateId] as const;

/** „12.10.2026 10:42” — data i godzina ruchu w strefie przeglądarki. */
export function moveWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const time = date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  return `${formatDate(iso)} ${time}`;
}

export function MoveLogList({
  items,
  hideCandidate = false,
}: {
  items: readonly JobMoveLogItem[];
  /** Panel jednej osoby: nazwisko stoi w głowie panelu, wiersz mówi sam ruch. */
  hideCandidate?: boolean;
}) {
  return (
    <ul className="space-y-2.5" aria-label="Ruchy w rekrutacji">
      {items.map((move) => (
        <li key={move.id} className="flex gap-3 text-[13px]">
          <span className="w-[92px] shrink-0 text-xs text-muted-foreground">{moveWhen(move.moved_at)}</span>
          <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
          <span className="min-w-0">
            {hideCandidate ? (
              <span className="text-foreground">
                {move.from_stage_name
                  ? `${move.from_stage_name} → ${move.to_stage_name ?? "—"}`
                  : `Dodany do rekrutacji · ${move.to_stage_name ?? "—"}`}
              </span>
            ) : (
              <>
                <Link
                  href={`/candidates/${move.candidate_id}`}
                  className="font-medium text-foreground hover:text-primary hover:underline"
                >
                  {move.candidate_name ?? `Kandydat #${move.candidate_id}`}
                </Link>
                <span className="text-foreground">
                  {move.from_stage_name ? ` ${move.from_stage_name}` : ""} → {move.to_stage_name ?? "—"}
                </span>
              </>
            )}
            <span className="block text-xs text-muted-foreground">
              {move.moved_by_name ?? (move.source === "traffit" ? "import z Traffita" : "autor nieznany")}
              {move.source === "traffit" && move.moved_by_name ? " · Traffit" : ""}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}
