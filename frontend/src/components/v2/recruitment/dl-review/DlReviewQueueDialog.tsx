"use client";

/**
 * Porównanie osób czekających na przegląd Delivery Leada w jednej rekrutacji
 * (D10, 08.10.2026). DL przeglądał je pojedynczo i nie widział, że trzecia
 * osoba z kolejki jest tańsza i spełnia więcej wymagań niż pierwsza. Tabela:
 * kandydat · ocena rekrutera · wymagania X/Y · koszt · start · ryzyka · czeka
 * od. Klik w osobę otwiera jej przegląd (wiersz kolejki przychodzi z serwera,
 * bez drugiego żądania).
 *
 * Wejścia: pulpit („Czeka na Twój przegląd”, 2+ osoby w rekrutacji) i nagłówek
 * kolumny „QC CV” na Tablicy („Porównaj (N)”). U Nordei przeglądu DL nie ma
 * — serwer oddaje pustą listę, a przyciski się nie pokazują.
 */

import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";
import { waitingFor, type BoardTaskRow } from "@/lib/api/boardTasks";
import { useDlReviewQueue, type DlReviewQueueItem } from "@/lib/api/dlReview";
import { formatHourly } from "@/lib/dl-review-margin";
import { rateText } from "@/lib/person-facts";

export interface DlReviewQueueDialogProps {
  jobId: number | null;
  jobTitle?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Otwórz przegląd jednej osoby (wiersz kolejki jak na pulpicie). */
  onReview: (task: BoardTaskRow) => void;
}

const FIT_VARIANT: Record<string, "success" | "danger" | "outline"> = {
  fit: "success",
  miss: "danger",
  uncertain: "outline",
};

export function costText(item: DlReviewQueueItem): string {
  const rate = item.candidate_rate;
  if (!rate) return "—";
  const text = rateText(rate.amount, rate.unit, rate.currency) ?? "—";
  return rate.unit !== "hourly" && rate.hourly_pln != null ? `${text} (${formatHourly(rate.hourly_pln)})` : text;
}

export function DlReviewQueueTable({
  items,
  onReview,
}: {
  items: DlReviewQueueItem[];
  onReview: (task: BoardTaskRow) => void;
}) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[56rem] text-left text-xs" aria-label="Porównanie kandydatów w przeglądzie">
        <thead className="bg-muted/40 text-[11px] text-muted-foreground">
          <tr>
            <th scope="col" className="sticky left-0 bg-muted/40 px-2 py-1.5 font-medium">Kandydat</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Ocena rekrutera</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Wymagania</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Koszt</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Start</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Ryzyka</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Czeka</th>
            <th scope="col" className="px-2 py-1.5 font-medium">
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((item) => (
            <tr key={item.candidate_id} data-testid="dl-review-queue-row">
              <td className="sticky left-0 bg-background px-2 py-1.5 align-top">
                <span className="font-medium text-foreground">{item.candidate_name}</span>
                <span className="mt-0.5 flex flex-wrap gap-1">
                  <QcStatusBadge row={{ qc_status: item.qc_status as never, qc_blocking_failed: 0 }} />
                  {item.fix_rounds > 0 ? (
                    <Badge size="sm" variant="warning">
                      poprawki: {item.fix_rounds}
                    </Badge>
                  ) : null}
                </span>
              </td>
              <td className="px-2 py-1.5 align-top">
                {item.overall_fit_label ? (
                  <Badge size="sm" variant={FIT_VARIANT[item.overall_fit ?? "uncertain"] ?? "outline"}>
                    {item.overall_fit_label}
                  </Badge>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-2 py-1.5 align-top tabular-nums">
                {item.requirements_total > 0 ? `${item.requirements_met}/${item.requirements_total}` : "—"}
              </td>
              <td className="px-2 py-1.5 align-top tabular-nums">{costText(item)}</td>
              <td className="max-w-[10rem] px-2 py-1.5 align-top [overflow-wrap:anywhere]">{item.start ?? "—"}</td>
              <td className="max-w-[16rem] px-2 py-1.5 align-top">
                {item.risks.length === 0 ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <ul className="space-y-0.5">
                    {item.risks.slice(0, 3).map((risk, index) => (
                      <li
                        key={`${risk.code}-${index}`}
                        className={
                          risk.severity === "high"
                            ? "text-destructive [overflow-wrap:anywhere]"
                            : "text-muted-foreground [overflow-wrap:anywhere]"
                        }
                      >
                        {risk.label}
                      </li>
                    ))}
                    {item.risks.length > 3 ? (
                      <li className="text-muted-foreground">i {item.risks.length - 3} więcej</li>
                    ) : null}
                  </ul>
                )}
              </td>
              <td className="px-2 py-1.5 align-top tabular-nums text-muted-foreground">{waitingFor(item.since)}</td>
              <td className="px-2 py-1.5 align-top">
                <Button size="sm" variant="outline" onClick={() => onReview(item.task)} aria-label={`Przejrzyj: ${item.candidate_name}`}>
                  Przejrzyj
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DlReviewQueueDialog({ jobId, jobTitle, open, onOpenChange, onReview }: DlReviewQueueDialogProps) {
  const queue = useDlReviewQueue(jobId, open);
  const items = queue.data?.items ?? [];
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title={jobTitle ? `Porównaj kandydatów — ${jobTitle}` : "Porównaj kandydatów"}
      description="Osoby czekające na Twój przegląd w tej rekrutacji, obok siebie."
    >
      {queue.isLoading ? (
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Wczytywanie kolejki…
        </p>
      ) : queue.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się wczytać kolejki.{" "}
          <button type="button" className="font-medium underline" onClick={() => void queue.refetch()}>
            Ponów
          </button>
        </p>
      ) : queue.isSuccess && items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {queue.data?.cpro_client
            ? "U tego klienta CV idzie do Cpro — przeglądu Delivery Leada nie ma."
            : "Nikt w tej rekrutacji nie czeka na Twój przegląd."}
        </p>
      ) : (
        <div className="space-y-2">
          <DlReviewQueueTable
            items={items}
            onReview={(task) => {
              onOpenChange(false);
              onReview(task);
            }}
          />
          {queue.data && queue.data.total > items.length ? (
            <p className="text-xs text-muted-foreground">
              Pokazano {items.length} z {queue.data.total} — najdłużej czekające.
            </p>
          ) : null}
        </div>
      )}
    </AppModal>
  );
}
