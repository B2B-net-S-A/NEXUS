"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeftRight,
  CalendarPlus,
  ChevronRight,
  FilePlus2,
  FileUp,
  History,
  Pencil,
  ReceiptText,
  Repeat,
  RotateCcw,
  SquareCheckBig,
  UserMinus,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import {
  orderGroupsApi,
  type OrderHistoryEntry,
} from "@/lib/api/orderGroups";
import { formatDateTimePl } from "@/lib/date-pl";
import {
  ALL_PEOPLE,
  ORDER_HISTORY_CATEGORY_OPTIONS,
  changesLabel,
  filterOrderHistory,
  mdImportHref,
  type OrderHistoryCategoryFilter,
} from "@/lib/order-history";
import { cn } from "@/lib/utils";

import { formatMd } from "./MdBudgetBar";

/** Ikona wpisu lustrzy przycisk, który ten wpis produkuje. `transfer_md`
 *  dostaje ikonę spoza zestawu: to ruch MIĘDZY zamówieniami, nie edycja. */
const EVENT_ICON: Record<string, LucideIcon> = {
  utworzenie: FilePlus2,
  dodanie_konsultanta: UserPlus,
  zamiana_kontraktora: Repeat,
  zakonczenie_konsultanta: UserMinus,
  edycja_reczna: Pencil,
  zakonczenie: SquareCheckBig,
  przywrocenie: RotateCcw,
  wyczerpanie: AlertTriangle,
  przedluzenie: CalendarPlus,
  import_md: FileUp,
  import_faktur: ReceiptText,
  transfer_md: ArrowLeftRight,
};

const selectClass =
  "rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring";

export function orderHistoryQueryKey(clientId: number, groupId: number) {
  return ["order-group-events", clientId, groupId, "history"] as const;
}

/** Wykonawca wpisu: nazwa, sam identyfikator (konto usunięte) albo system. */
function authorLabel(entry: {
  author_name: string | null;
  author_id: number | null;
}): string {
  if (entry.author_name) return entry.author_name;
  if (entry.author_id != null) return `Użytkownik #${entry.author_id}`;
  return "Automatycznie (system)";
}

/** Treść z klikalnym numerem zamówienia powiązanego (przejęcie zużycia MD).
 *  Bez `related_group_id` — sam tekst: przycisk bez celu obiecuje nawigację,
 *  której nie wykona. */
function Summary({
  entry,
  onFocusGroup,
}: {
  entry: OrderHistoryEntry;
  onFocusGroup: (groupId: number) => void;
}) {
  const groupId = entry.related_group_id;
  const number = entry.related_order_number;
  if (groupId == null || !number) return <>{entry.summary}</>;
  const link = (
    <button
      type="button"
      onClick={() => onFocusGroup(groupId)}
      aria-label={`Pokaż zamówienie nr ${number}`}
      className="font-semibold text-primary underline underline-offset-2 hover:no-underline"
    >
      {number}
    </button>
  );
  const at = entry.summary.indexOf(number);
  if (at < 0) {
    return (
      <>
        {entry.summary} {link}
      </>
    );
  }
  return (
    <>
      {entry.summary.slice(0, at)}
      {link}
      {entry.summary.slice(at + number.length)}
    </>
  );
}

function Balance({ entry }: { entry: OrderHistoryEntry }) {
  if (entry.balance_after == null) return null;
  const negative = entry.balance_after < 0;
  return (
    <span className="whitespace-nowrap text-muted-foreground">
      saldo po:{" "}
      <span
        className={cn(
          "font-semibold tabular-nums",
          negative ? "text-destructive" : "text-foreground",
        )}
      >
        {formatMd(entry.balance_after)} MD
      </span>
      {entry.balance_before != null && entry.balance_before !== entry.balance_after ? (
        <span
          className={cn(
            "ml-1 tabular-nums",
            entry.balance_before < 0 && "text-destructive",
          )}
        >
          (było {formatMd(entry.balance_before)})
        </span>
      ) : null}
    </span>
  );
}

function Changes({ entry }: { entry: OrderHistoryEntry }) {
  if (entry.changes.length === 0) return null;
  const exact = entry.changes.some((c) => c.before != null || c.after != null);
  if (!exact) {
    return (
      <span className="text-muted-foreground">
        zmieniono: {entry.changes.map((c) => c.label).join(", ")}
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
      {entry.changes.map((change) => (
        <span key={change.label}>
          {change.label}:{" "}
          <span className="text-foreground">{change.before ?? "—"}</span> →{" "}
          <span className="font-medium text-foreground">{change.after ?? "—"}</span>
        </span>
      ))}
    </span>
  );
}

function HistoryRow({
  entry,
  clientId,
  compact,
  onFocusGroup,
}: {
  entry: OrderHistoryEntry;
  clientId: number;
  compact: boolean;
  onFocusGroup: (groupId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const Icon = EVENT_ICON[entry.event_type] ?? History;
  const person =
    entry.person_name ??
    (entry.person_names.length > 0 ? entry.person_names.join(", ") : null);
  const grouped = entry.details.length > 1;
  // Wpis ze zmianami mówi „co zmieniono" w zmianach — opis powtórzyłby to
  // samo drugi raz. Seria ma szczegóły w rozwinięciu.
  const showSummary = !grouped && entry.changes.length === 0;
  return (
    <li className={cn("flex flex-col text-xs", compact ? "gap-0.5" : "gap-1")}>
      <div className={cn("flex flex-wrap items-baseline", compact ? "gap-x-2" : "gap-x-3", "gap-y-1")}>
        <span className="w-28 shrink-0 tabular-nums text-muted-foreground">
          {formatDateTimePl(entry.created_at)}
        </span>
        <span
          className="w-32 shrink-0 truncate text-muted-foreground"
          title={authorLabel(entry)}
        >
          {authorLabel(entry)}
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-medium text-foreground">
          <Icon className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
          {entry.type_label}
        </span>
        {person ? (
          <span className="font-medium text-foreground">{person}</span>
        ) : null}
        {showSummary ? (
          <span className="min-w-0 text-muted-foreground">
            <Summary entry={entry} onFocusGroup={onFocusGroup} />
          </span>
        ) : null}
        <Changes entry={entry} />
        <Balance entry={entry} />
        {entry.import_id != null ? (
          <Link
            href={mdImportHref(clientId, entry.import_id)}
            className="whitespace-nowrap font-medium text-primary hover:underline"
          >
            Otwórz import →
          </Link>
        ) : null}
        {grouped ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex items-center gap-0.5 whitespace-nowrap font-medium text-primary hover:underline"
          >
            <ChevronRight
              className={cn("h-3 w-3 transition-transform", open && "rotate-90")}
              aria-hidden="true"
            />
            {changesLabel(entry.details.length)}
          </button>
        ) : null}
      </div>
      {grouped && open ? (
        <ol className="ml-4 flex flex-col gap-0.5 border-l border-border pl-3">
          {entry.details.map((detail, index) => (
            <li key={`${entry.key}-${index}`} className="flex flex-wrap gap-x-2 text-muted-foreground">
              <span className="tabular-nums">{formatDateTimePl(detail.created_at)}</span>
              <span>{authorLabel(detail)}</span>
              <span className="text-foreground">{detail.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </li>
  );
}

interface Props {
  clientId: number;
  groupId: number;
  compact?: boolean;
  onFocusGroup: (groupId: number) => void;
}

/**
 * Historia zamówienia — wyłącznie zdarzenia biznesowe (ticket 7, 25.09.2026).
 *
 * Pojedyncze zejścia MD są w oknie „Zużycie MD" osoby, techniczne zmiany pól
 * w Timeline kontraktu, importy — w zakładce „Importy MD" (odsyłacz przy
 * wpisie importu).
 */
export function OrderHistoryPanel({ clientId, groupId, compact = false, onFocusGroup }: Props) {
  const [category, setCategory] = useState<OrderHistoryCategoryFilter>("all");
  const [person, setPerson] = useState<string>(ALL_PEOPLE);
  const history = useQuery({
    queryKey: orderHistoryQueryKey(clientId, groupId),
    queryFn: async () => (await orderGroupsApi.history(clientId, groupId)).data,
  });

  if (history.isError) {
    // Awaria pobrania NIE może wyglądać jak „brak historii".
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać historii tego zamówienia."
        onRetry={() => history.refetch()}
      />
    );
  }
  if (!history.isSuccess) {
    // `isSuccess`, nie `!isLoading`: między ponowieniami pusta lista wygrywałaby.
    return <p className="text-xs text-muted-foreground">Wczytywanie historii…</p>;
  }
  const { entries, people } = history.data;
  if (entries.length === 0) {
    return <p className="text-xs text-muted-foreground">Brak wpisów w historii.</p>;
  }
  const visible = filterOrderHistory(entries, { category, person });
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="inline-flex items-center gap-1.5 text-muted-foreground">
          Typ zdarzenia
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as OrderHistoryCategoryFilter)}
            className={selectClass}
          >
            {ORDER_HISTORY_CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {people.length > 0 ? (
          <label className="inline-flex items-center gap-1.5 text-muted-foreground">
            Osoba
            <select
              value={person}
              onChange={(e) => setPerson(e.target.value)}
              className={selectClass}
            >
              <option value={ALL_PEOPLE}>Wszyscy</option>
              {people.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Żaden wpis nie pasuje do wybranych filtrów.
        </p>
      ) : (
        <ol className={cn("flex flex-col", compact ? "gap-1.5" : "gap-2")}>
          {visible.map((entry) => (
            <HistoryRow
              key={entry.key}
              entry={entry}
              clientId={clientId}
              compact={compact}
              onFocusGroup={onFocusGroup}
            />
          ))}
        </ol>
      )}
    </div>
  );
}
