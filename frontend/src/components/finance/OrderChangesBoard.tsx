"use client";

import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  Eye,
  Loader2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  InvoiceLine,
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
import { CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDay, formatMoment } from "@/lib/finance-order-changes";
import { cn } from "@/lib/utils";

import { ChangeRow, labelVariant, pdfKey } from "./OrderChangeRow";
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
  /** Nordea, Wejścia: zapis ręcznej poprawki pozycji faktury (ticket 8). */
  onSaveInvoiceLine?: (
    item: BoardItem,
    line: InvoiceLine,
    text: string,
  ) => Promise<boolean>;
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
 * Układ „Zmian w zamówieniach": lista klientów → wiersze zamówień w jednej
 * karcie klienta → panel podglądu (domyślnie ukryty). Wzorowany na
 * „Zamówieniach PDF". Do 02.10.2026 każde zamówienie było osobną kartą
 * z ramką — przy kilkudziesięciu zmianach miesiąca lista była ścianą ramek.
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
  onSaveInvoiceLine,
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
    <ul className="divide-y divide-border/60">
      {list.map((card) => (
        <OrderCard
          key={card.key}
          card={card}
          selected={previewed?.key === card.key}
          canCheck={canCheck}
          pendingKeys={pendingKeys}
          onToggle={onToggle}
          onSaveInvoiceLine={onSaveInvoiceLine}
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
        "grid gap-3.5 lg:items-start",
        previewed
          ? "lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)_minmax(360px,420px)]"
          : "lg:grid-cols-[260px_minmax(0,1fr)]",
      )}
    >
      <section
        aria-label="Klienci"
        className="min-w-0 rounded-[10px] border border-border bg-card p-1.5"
      >
        <h3 className={cn("px-2.5 pb-1 pt-2", CALM_HEAD)}>
          Klienci — {data.period.label}
        </h3>
        <ul role="listbox" aria-label="Klienci" className="space-y-0.5">
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
                    "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
                    active ? "bg-primary/10" : "hover:bg-muted/60",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "block truncate text-[13px] font-semibold",
                        active ? "text-primary" : "text-foreground",
                      )}
                    >
                      {tile.name}
                    </span>
                    <span className="block text-[11.5px] leading-4 text-muted-foreground">
                      {changesLabel(tile.total)} ·{" "}
                      {allDone
                        ? "wszystko zrobione"
                        : `${tile.todo} do zrobienia`}
                    </span>
                  </span>
                  {allDone ? (
                    <span
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success-muted text-success-muted-foreground"
                      aria-label="Wszystko zrobione"
                    >
                      <Check className="h-3 w-3" aria-hidden />
                    </span>
                  ) : (
                    <span
                      className={cn(
                        "flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
                        active
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground",
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
        className="min-w-0 space-y-3"
      >
        {banner}
        <div className="rounded-[10px] border border-border bg-card">
          {activeTile ? (
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-t-[10px] border-b border-border bg-background px-3.5 py-2">
              <h3 className="text-[13px] font-semibold text-foreground">
                {activeTile.name}
              </h3>
              <p className="text-xs text-muted-foreground">
                {data.period.label} · {activeTile.todo}{" "}
                {activeTile.todo === 1 ? "zmiana" : "zmian"} do zrobienia z{" "}
                {activeTile.total}
              </p>
            </div>
          ) : null}
          {open.length === 0 ? (
            <div className="p-3">
              <Empty>
                {status === "done"
                  ? "U tego klienta nic jeszcze nie oznaczono jako zrobione."
                  : "U tego klienta wszystko jest zrobione."}
              </Empty>
            </div>
          ) : (
            cardList(open)
          )}
          {finished.length > 0 ? (
            <>
              <button
                type="button"
                onClick={() => setFinishedOpen((value) => !value)}
                aria-expanded={finishedOpen}
                className={cn(
                  "flex w-full items-center justify-between border-t border-border bg-background px-3.5 py-1.5 hover:text-foreground",
                  finishedOpen ? "border-b" : "rounded-b-[10px]",
                  CALM_HEAD,
                )}
              >
                <span>Zrobione ({finished.length})</span>
                <span className="inline-flex items-center gap-1 text-xs font-medium normal-case tracking-normal text-primary">
                  {finishedOpen ? "Zwiń" : "Rozwiń"}
                  {finishedOpen ? (
                    <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                  )}
                </span>
              </button>
              {finishedOpen ? cardList(finished) : null}
            </>
          ) : null}
        </div>
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
  onSaveInvoiceLine,
  onPreview,
  onDownload,
  downloading,
}: {
  card: BoardCard;
  selected: boolean;
  canCheck: boolean;
  pendingKeys: ReadonlySet<string>;
  onToggle: (item: BoardItem, done: boolean) => void;
  onSaveInvoiceLine?: OrderChangesBoardProps["onSaveInvoiceLine"];
  onPreview: () => void;
  onDownload: () => void;
  downloading: boolean;
}) {
  const title = cardTitle(card);
  const finished = card.todo === 0;
  const stop = (event: MouseEvent) => event.stopPropagation();
  const period = `${card.orderStart ? formatDay(card.orderStart) : "—"} – ${
    card.orderEnd ? formatDay(card.orderEnd) : "bezterminowo"
  }`;
  // Rodzaj każdej widocznej zmiany stoi przy niej (plakietka w `ChangeRow`);
  // tu zostają tylko rodzaje, których w widocznych pozycjach nie ma.
  const extraLabels = card.labels.filter(
    (label) => !card.visible.some((entry) => entry.item.label === label),
  );
  const rows = Math.max(
    1,
    card.visible.length + (card.previous.length > 0 ? 1 : 0),
  );

  return (
    <li>
      {/* Wiersz zamówienia: [Zrobione] [osoba · numer · okres] [zmiana] [akcje].
          Od `md` to jedna siatka — pola „Zrobione" kolejnych zmian stoją
          w pierwszej kolumnie, osoba i akcje obejmują wszystkie wiersze zmian. */}
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
        style={{ "--rows": rows } as CSSProperties}
        className={cn(
          "grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 border-l-2 px-3.5 py-2.5 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:grid-cols-[auto_minmax(150px,1.1fr)_minmax(240px,2.6fr)_auto]",
          selected
            ? "border-primary bg-primary/5"
            : "border-transparent hover:bg-muted/40",
        )}
      >
        <div className="col-span-2 min-w-0 md:col-span-1 md:col-start-2 md:[grid-row:1/span_var(--rows)]">
          <p className="text-[13px] font-semibold text-foreground">
            {card.consultantName}
          </p>
          <p className={CALM_SUBLINE}>
            zam. {card.orderNumber} · {period}
          </p>
          {extraLabels.length > 0 || card.changedAgain || finished ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {extraLabels.map((label) => (
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
          ) : null}
        </div>

        <ul role="list" className="contents" onClick={stop}>
          {card.visible.map((entry) => (
            <ChangeRow
              key={entry.item.key}
              entry={entry}
              canCheck={canCheck}
              pending={pendingKeys.has(entry.item.key)}
              onToggle={onToggle}
              onSaveInvoiceLine={onSaveInvoiceLine}
              layout="grid"
            />
          ))}
        </ul>
        {card.previous.length > 0 ? (
          <ul className="col-span-2 space-y-0.5 text-[11.5px] leading-4 text-muted-foreground md:col-span-1 md:col-start-3">
            {card.previous.map((previous, index) => (
              <li key={index}>
                Wcześniej: {previous.summary} — oznaczona jako zrobiona przez{" "}
                {previous.done.by_name}, {formatMoment(previous.done.at)}
              </li>
            ))}
          </ul>
        ) : null}

        <div
          className="col-span-2 flex items-start gap-1.5 md:col-span-1 md:col-start-4 md:justify-end md:[grid-row:1/span_var(--rows)]"
          onClick={stop}
        >
          {card.pdf ? (
            <>
              <button
                type="button"
                onClick={onPreview}
                aria-label={`Podgląd PDF: zamówienie ${card.orderNumber}`}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors pointer-coarse:min-h-10",
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
                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background text-foreground hover:bg-muted disabled:opacity-60 pointer-coarse:min-h-10 pointer-coarse:min-w-10"
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
              className="inline-flex max-w-[220px] items-center gap-1.5 rounded-md bg-warning-muted px-2 py-1 text-[11.5px] font-medium text-warning-muted-foreground"
            >
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Brak PDF – zmiana wprowadzona ręcznie
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
