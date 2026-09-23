"use client";

import {
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  Eye,
  Loader2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  OrderChangesResponse,
  OrderChangesTab,
  OrderPdfRef,
} from "@/lib/api/finance";
import {
  BOARD_LABEL_TEXT,
  boardItems,
  buildCards,
  cardTitle,
  clientKey,
  clientTiles,
  splitCards,
  type BoardCard,
  type BoardItem,
  type StatusFilter,
} from "@/lib/finance-order-board";
import { formatMoment } from "@/lib/finance-order-changes";
import { cn } from "@/lib/utils";

import { ChangeRow, pdfKey } from "./OrderChangeRow";
import {
  OrderChangePreviewPanel,
  type OrderChangePreviewExtras,
} from "./OrderChangePreviewPanel";

export interface OrderChangesBoardProps {
  data: OrderChangesResponse;
  tab: OrderChangesTab;
  status: StatusFilter;
  /** Klucz kafelka klienta (`clientKey`) — `null` = pierwszy na liście. */
  selectedClient: string | null;
  onSelectClient: (key: string) => void;
  onToggle: (item: BoardItem, done: boolean) => void;
  /** Pozycje, których zapis odhaczenia właśnie trwa. */
  pendingKeys: ReadonlySet<string>;
  onDownloadPdf: (pdf: OrderPdfRef) => void;
  downloadingPdf: string | null;
  /** Otwarta karta w panelu podglądu (`cardKey`) — `null` = panel ukryty. */
  previewCard: string | null;
  onPreviewCard: (cardKey: string | null) => void;
  /** Reszta panelu (historia, PDF, przejście do „Zamówień PDF") — rodzic
   *  dostarcza dane, bo harness nie może odpytywać API. */
  preview: OrderChangePreviewExtras;
  /** Treść nad listą kart (np. baner o brakach). */
  banner?: ReactNode;
  emptyText: ReactNode;
}

/**
 * Układ „Zmian w zamówieniach": kafelki klientów → karty zamówień → panel
 * podglądu (domyślnie ukryty). Wzorowany na „Zamówieniach PDF".
 *
 * Czysta prezentacja — zapytania i zapisy robi `OrderChangesTab`, a ten sam
 * komponent renderuje publiczny harness bez żadnego zapytania.
 */
export function OrderChangesBoard({
  data,
  tab,
  status,
  selectedClient,
  onSelectClient,
  onToggle,
  pendingKeys,
  onDownloadPdf,
  downloadingPdf,
  previewCard,
  onPreviewCard,
  preview,
  banner,
  emptyText,
}: OrderChangesBoardProps) {
  const items = useMemo(() => boardItems(data, tab), [data, tab]);
  const tiles = useMemo(() => clientTiles(items), [items]);
  // Bez jawnego wyboru pierwszy kafelek zostaje „przyklejony": odhaczenie
  // ostatniej zmiany klienta przesuwa jego kafelek na dół, a widok nie może
  // wtedy przeskoczyć na innego klienta pod ręką użytkownika.
  const [sticky, setSticky] = useState<string | null>(null);
  const has = (key: string | null) =>
    key !== null && tiles.some((tile) => tile.key === key);
  const activeKey = has(selectedClient)
    ? selectedClient
    : has(sticky)
      ? sticky
      : (tiles[0]?.key ?? null);
  useEffect(() => {
    if (activeKey !== sticky) setSticky(activeKey);
  }, [activeKey, sticky]);
  const activeTile = tiles.find((tile) => tile.key === activeKey) ?? null;
  const clientItems = useMemo(
    () => items.filter((item) => clientKey(item.clientId) === activeKey),
    [activeKey, items],
  );
  const cards = useMemo(
    () => buildCards(clientItems, status, data.superseded ?? [], tab),
    [clientItems, data.superseded, status, tab],
  );
  const { open, finished } = splitCards(cards, status);
  // „Do zrobienia": zrobione karty zwinięte; „Wszystkie": rozwinięte.
  const [finishedOpen, setFinishedOpen] = useState(status === "all");
  useEffect(() => setFinishedOpen(status === "all"), [status]);

  const canCheck = Boolean(data.can_check);
  // Karta w panelu może pochodzić z innego klienta niż wybrany (np. po
  // zmianie kafelka) — wtedy panel się zamyka zamiast pokazywać cudzą kartę.
  const previewed = previewCard
    ? (cards.find((card) => card.key === previewCard) ?? null)
    : null;

  useEffect(() => {
    if (!previewCard) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onPreviewCard(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onPreviewCard, previewCard]);

  if (tiles.length === 0) {
    return (
      <div className="space-y-3">
        <Empty>{emptyText}</Empty>
        {banner}
      </div>
    );
  }

  const cardList = (list: BoardCard[]) => (
    <ul className="space-y-3">
      {list.map((card) => (
        <OrderCard
          key={card.key}
          card={card}
          selected={previewed?.key === card.key}
          canCheck={canCheck}
          pendingKeys={pendingKeys}
          onToggle={onToggle}
          onPreview={() => onPreviewCard(card.key)}
          onDownload={() => card.pdf && onDownloadPdf(card.pdf)}
          downloading={Boolean(card.pdf && downloadingPdf === pdfKey(card.pdf))}
        />
      ))}
    </ul>
  );

  return (
    <div
      className={cn(
        "grid gap-4",
        previewed
          ? "lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)_minmax(380px,440px)]"
          : "lg:grid-cols-[260px_minmax(0,1fr)]",
      )}
    >
      <section
        aria-label="Klienci"
        className="h-fit min-w-0 rounded-xl border border-border bg-card p-3"
      >
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
          <Building2 className="h-4 w-4 text-muted-foreground" aria-hidden />
          Klienci — {data.period.label}
        </h3>
        <ul role="listbox" aria-label="Klienci" className="space-y-1">
          {tiles.map((tile) => {
            const active = tile.key === activeKey;
            const allDone = tile.todo === 0;
            return (
              <li key={tile.key}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => onSelectClient(tile.key)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                    active ? "bg-primary/10" : "hover:bg-muted",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "block truncate text-sm font-medium",
                        active ? "text-primary" : "text-foreground",
                      )}
                    >
                      {tile.name}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {changesLabel(tile.total)} ·{" "}
                      {allDone
                        ? "wszystko zrobione"
                        : `${tile.todo} do zrobienia`}
                    </span>
                  </span>
                  {allDone ? (
                    <span
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-success-muted text-success-muted-foreground"
                      aria-label="Wszystko zrobione"
                    >
                      <Check className="h-3.5 w-3.5" aria-hidden />
                    </span>
                  ) : (
                    <span
                      className={cn(
                        "flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full px-1.5 text-xs font-semibold",
                        active
                          ? "bg-primary text-primary-foreground"
                          : "bg-primary/10 text-primary",
                      )}
                      aria-label={`${tile.todo} do zrobienia`}
                    >
                      {tile.todo}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section
        aria-label={
          activeTile ? `Zamówienia — ${activeTile.name}` : "Zamówienia"
        }
        className="min-w-0 space-y-3 rounded-xl border border-border bg-card p-3 sm:p-4"
      >
        {activeTile ? (
          <div>
            <h3 className="text-base font-semibold text-foreground">
              {activeTile.name}
            </h3>
            <p className="text-xs text-muted-foreground">
              {data.period.label} · {activeTile.todo}{" "}
              {activeTile.todo === 1 ? "zmiana" : "zmian"} do zrobienia z{" "}
              {activeTile.total}
            </p>
          </div>
        ) : null}
        {banner}
        {open.length === 0 ? (
          <Empty>
            {status === "done"
              ? "U tego klienta nic jeszcze nie oznaczono jako zrobione."
              : "U tego klienta wszystko jest zrobione."}
          </Empty>
        ) : (
          cardList(open)
        )}
        {finished.length > 0 ? (
          <div className="space-y-3 pt-1">
            <button
              type="button"
              onClick={() => setFinishedOpen((value) => !value)}
              aria-expanded={finishedOpen}
              className="flex w-full items-center justify-between border-b border-border pb-1 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
            >
              <span>Zrobione ({finished.length})</span>
              <span className="inline-flex items-center gap-1 normal-case tracking-normal text-primary">
                {finishedOpen ? "Zwiń" : "Rozwiń"}
                {finishedOpen ? (
                  <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                )}
              </span>
            </button>
            {finishedOpen ? cardList(finished) : null}
          </div>
        ) : null}
      </section>

      {previewed ? (
        <OrderChangePreviewPanel
          {...preview}
          card={previewed}
          items={preview.itemsForCard?.(previewed.key) ?? previewed.items}
          canCheck={canCheck}
          onToggle={onToggle}
          pendingKeys={pendingKeys}
          monthLabel={data.period.label}
          onClose={() => onPreviewCard(null)}
          onDownloadPdf={onDownloadPdf}
          downloadingPdf={downloadingPdf}
        />
      ) : null}
    </div>
  );
}

function changesLabel(count: number): string {
  if (count === 1) return "1 zmiana";
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} zmiany`;
  }
  return `${count} zmian`;
}

function OrderCard({
  card,
  selected,
  canCheck,
  pendingKeys,
  onToggle,
  onPreview,
  onDownload,
  downloading,
}: {
  card: BoardCard;
  selected: boolean;
  canCheck: boolean;
  pendingKeys: ReadonlySet<string>;
  onToggle: (item: BoardItem, done: boolean) => void;
  onPreview: () => void;
  onDownload: () => void;
  downloading: boolean;
}) {
  const title = cardTitle(card);
  const finished = card.todo === 0;
  const stop = (event: MouseEvent) => event.stopPropagation();

  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        aria-label={`Podgląd: ${title}`}
        aria-pressed={selected}
        onClick={onPreview}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onPreview();
          }
        }}
        className={cn(
          "cursor-pointer rounded-xl border bg-card p-3 transition-colors sm:p-4",
          selected
            ? "border-2 border-primary shadow-sm"
            : "border-border hover:border-primary/40",
        )}
      >
        <div className="flex flex-wrap items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground">{title}</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {card.labels.map((label) => (
                <Badge key={label} size="sm" variant={labelVariant(label)}>
                  {BOARD_LABEL_TEXT[label]}
                </Badge>
              ))}
              {card.changedAgain ? (
                <Badge size="sm" variant="warning">
                  Zmieniono ponownie
                </Badge>
              ) : null}
              {finished ? (
                <Badge size="sm" variant="success">
                  Zrobione
                </Badge>
              ) : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5" onClick={stop}>
            {card.pdf ? (
              <>
                <button
                  type="button"
                  onClick={onPreview}
                  aria-label={`Podgląd PDF: zamówienie ${card.orderNumber}`}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
                    selected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-foreground hover:bg-muted",
                  )}
                >
                  <Eye className="h-3.5 w-3.5" aria-hidden />
                  Podgląd
                </button>
                <button
                  type="button"
                  onClick={onDownload}
                  disabled={downloading}
                  aria-label={`Pobierz PDF: zamówienie ${card.orderNumber}`}
                  title="Pobierz PDF"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-foreground hover:bg-muted disabled:opacity-60"
                >
                  {downloading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <Download className="h-3.5 w-3.5" aria-hidden />
                  )}
                </button>
              </>
            ) : (
              <span
                role="note"
                className="inline-flex max-w-[220px] items-center gap-1.5 rounded-md border border-warning/25 bg-warning-muted px-2 py-1 text-xs font-medium text-warning-muted-foreground"
              >
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                Brak PDF – zmiana wprowadzona ręcznie
              </span>
            )}
          </div>
        </div>

        <ul className="mt-3 space-y-2" onClick={stop}>
          {card.visible.map((entry) => (
            <ChangeRow
              key={entry.item.key}
              entry={entry}
              canCheck={canCheck}
              pending={pendingKeys.has(entry.item.key)}
              onToggle={onToggle}
            />
          ))}
        </ul>
        {card.previous.length > 0 ? (
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {card.previous.map((previous, index) => (
              <li key={index}>
                Wcześniej: {previous.summary} — oznaczona jako zrobiona przez{" "}
                {previous.done.by_name}, {formatMoment(previous.done.at)}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}

function labelVariant(
  label: string,
): "info" | "success" | "warning" | "danger" | "neutral" | "soft" {
  switch (label) {
    case "new_order":
      return "success";
    case "extension":
    case "period":
      return "info";
    case "rate_revenue":
      return "soft";
    case "rate_cost":
      return "warning";
    case "exit":
    case "gap":
      return "danger";
    default:
      return "neutral";
  }
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
