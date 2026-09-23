"use client";

import {
  AlertTriangle,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  X,
} from "lucide-react";

import type { OrderHistoryEntry, OrderPdfRef } from "@/lib/api/finance";
import type { BoardCard, BoardItem } from "@/lib/finance-order-board";
import { formatDay, formatMoment } from "@/lib/finance-order-changes";

import { ChangeRow, pdfKey } from "./OrderChangeRow";
import { OrderPdfViewer, type OrderPdfLoader } from "./OrderPdfViewer";

const TAB_SHORT: Record<string, string> = {
  changes: "Zmiany",
  entries: "Wejścia",
  exits: "Zejścia",
  ending: "Kończące się",
  gaps: "Braki",
};

/** Dane panelu, które dostarcza rodzic (zapytania albo harness). */
export interface OrderChangePreviewExtras {
  /** Pozycje zamówienia ze WSZYSTKICH podzakładek miesiąca. */
  itemsForCard?: (cardKey: string) => BoardItem[];
  history: {
    items: OrderHistoryEntry[] | null;
    loading: boolean;
    failed: boolean;
  };
  loadPdf: OrderPdfLoader;
  onOpenInPdfs: (pdf: OrderPdfRef) => void;
}

export interface OrderChangePreviewProps extends OrderChangePreviewExtras {
  card: BoardCard;
  items: BoardItem[];
  canCheck: boolean;
  onToggle: (item: BoardItem, done: boolean) => void;
  pendingKeys: ReadonlySet<string>;
  monthLabel: string;
  onClose: () => void;
  onDownloadPdf: (pdf: OrderPdfRef) => void;
  downloadingPdf: string | null;
}

function historyText(entry: OrderHistoryEntry): string {
  if (entry.kind === "checked")
    return `oznaczono jako zrobione: ${entry.summary}`;
  if (entry.kind === "unchecked")
    return `cofnięto „Zrobione”: ${entry.summary}`;
  return entry.summary;
}

/**
 * Panel podglądu zamówienia: PDF, pozycje miesiąca z checkboxami, pobranie,
 * przejście do „Zamówień PDF" i historia (audyt). Poniżej `xl` wysuwa się
 * z prawej nad treścią; od `xl` stoi jako trzecia kolumna.
 */
export function OrderChangePreviewPanel({
  card,
  items,
  canCheck,
  onToggle,
  pendingKeys,
  monthLabel,
  onClose,
  onDownloadPdf,
  downloadingPdf,
  history,
  loadPdf,
  onOpenInPdfs,
}: OrderChangePreviewProps) {
  const period = `${card.orderStart ? formatDay(card.orderStart) : "—"} – ${
    card.orderEnd ? formatDay(card.orderEnd) : "bezterminowo"
  }`;
  const downloading = card.pdf ? downloadingPdf === pdfKey(card.pdf) : false;

  return (
    <aside
      aria-label="Podgląd zamówienia"
      className="fixed inset-y-0 right-0 z-40 w-full max-w-md space-y-4 overflow-y-auto border-l border-border bg-card p-4 shadow-xl xl:static xl:z-auto xl:h-fit xl:max-w-none xl:rounded-xl xl:border xl:shadow-none"
    >
      <div className="flex items-start gap-2">
        <FileText
          className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
          aria-hidden
        />
        <h3 className="flex-1 text-sm font-semibold text-foreground">
          Podgląd zamówienia
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Zamknij podgląd (Esc)"
          title="Zamknij (Esc)"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-muted text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div>
        <p className="text-base font-semibold text-foreground">
          Zam. {card.orderNumber} · {card.consultantName}
        </p>
        <p className="text-xs text-muted-foreground">
          {card.clientName} · {period}
        </p>
      </div>

      <div className="h-[420px]">
        {card.pdf ? (
          <OrderPdfViewer file={card.pdf} loadPdf={loadPdf} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-warning/40 bg-warning-muted/40 p-4 text-center text-sm text-warning-muted-foreground">
            <AlertTriangle className="h-5 w-5" aria-hidden />
            Brak PDF – zmiana wprowadzona ręcznie
          </div>
        )}
      </div>

      <section aria-label="Zmiany w tym zamówieniu" className="space-y-2">
        <h4 className="text-sm font-semibold text-foreground">
          Zmiany w tym zamówieniu ({monthLabel.toLowerCase()})
        </h4>
        <ul className="space-y-2">
          {items.map((item) => (
            <ChangeRow
              key={item.key}
              entry={{ item, earlier: [] }}
              canCheck={canCheck}
              pending={pendingKeys.has(item.key)}
              onToggle={onToggle}
              compact
              tabLabel={
                item.tab !== card.items[0]?.tab
                  ? TAB_SHORT[item.tab]
                  : undefined
              }
            />
          ))}
        </ul>
      </section>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={!card.pdf || downloading}
          onClick={() => card.pdf && onDownloadPdf(card.pdf)}
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {downloading ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Download className="h-4 w-4" aria-hidden />
          )}
          Pobierz PDF
        </button>
        <button
          type="button"
          disabled={!card.pdf}
          onClick={() => card.pdf && onOpenInPdfs(card.pdf)}
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
        >
          <ExternalLink className="h-4 w-4" aria-hidden />
          Otwórz w Zamówienia PDF
        </button>
      </div>

      <section
        aria-label="Historia (audyt)"
        className="space-y-1.5 border-t border-border pt-3"
      >
        <h4 className="text-sm font-semibold text-foreground">
          Historia (audyt)
        </h4>
        {history.loading ? (
          <p className="text-xs text-muted-foreground">Wczytywanie historii…</p>
        ) : history.failed ? (
          <p className="text-xs text-destructive">
            Nie udało się wczytać historii.
          </p>
        ) : !history.items || history.items.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Brak wpisów w historii.
          </p>
        ) : (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {history.items.map((entry, index) => (
              <li key={`${entry.at}-${index}`}>
                {formatMoment(entry.at)} ·{" "}
                {entry.by_name ?? (entry.automatic ? "automatycznie" : "—")} ·{" "}
                {historyText(entry)}
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}
