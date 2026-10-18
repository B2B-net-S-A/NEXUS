"use client";

import { useDeferredValue, useState } from "react";
import { Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useEquipmentItems,
  type EquipmentCategory,
  type EquipmentHolderKind,
  type EquipmentItemStatus,
} from "@/lib/api/equipment";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  HOLDER_KIND_LABELS,
  ITEM_STATUS_LABELS,
  ITEM_STATUS_TONE,
  PROTOCOL_STATUS_LABELS,
  itemIdentifier,
  itemNumber,
} from "./equipment-format";
import { FilterSelect } from "./FilterSelect";

interface ItemsTabProps {
  onOpenItem: (itemId: number) => void;
}

const STATUS_OPTIONS = (Object.keys(ITEM_STATUS_LABELS) as EquipmentItemStatus[]).map(
  (value) => ({ value, label: ITEM_STATUS_LABELS[value] }),
);
const HOLDER_OPTIONS: { value: "none" | EquipmentHolderKind; label: string }[] = [
  { value: "none", label: "Bez posiadacza" },
  { value: "user", label: HOLDER_KIND_LABELS.user },
  { value: "contract", label: HOLDER_KIND_LABELS.contract },
  { value: "external", label: HOLDER_KIND_LABELS.external },
  { value: "academy", label: HOLDER_KIND_LABELS.academy },
];

/** Rejestr egzemplarzy: filtry, tabela, klik = szczegół z historią. */
export function ItemsTab({ onOpenItem }: ItemsTabProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<EquipmentCategory | "">("");
  const [status, setStatus] = useState<EquipmentItemStatus | "">("");
  const [holder, setHolder] = useState<"none" | EquipmentHolderKind | "">("");
  const deferredQuery = useDeferredValue(query);
  const items = useEquipmentItems({ category, status, holder, q: deferredQuery });
  const rows = items.data?.items ?? [];
  const state = resolveViewState({
    isLoading: items.isLoading,
    error: items.error,
    isSuccess: items.isSuccess,
    isEmpty: rows.length === 0,
  });
  const filtered = Boolean(query.trim() || category || status || holder);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj sprzętu"
            placeholder="Numer, S/N, IMEI, numer SIM albo osoba…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9 pl-8"
          />
        </div>
        <FilterSelect
          label="Kategoria"
          value={category}
          allLabel="Wszystkie kategorie"
          options={CATEGORY_ORDER.map((value) => ({ value, label: CATEGORY_LABELS[value] }))}
          onChange={setCategory}
        />
        <FilterSelect
          label="Stan"
          value={status}
          allLabel="Każdy stan"
          options={STATUS_OPTIONS}
          onChange={setStatus}
        />
        <FilterSelect
          label="Posiadacz"
          value={holder}
          allLabel="Każdy posiadacz"
          options={HOLDER_OPTIONS}
          onChange={setHolder}
        />
        {items.data ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {items.data.total} pozycji
          </span>
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie rejestru…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => items.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {filtered
            ? "Żadna pozycja nie pasuje do filtrów."
            : "Rejestr jest pusty. Dodaj pozycję albo zaimportuj pliki recepcji (zakładka „Import”)."}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[880px]">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} w-20`}>Nr</TableHead>
                <TableHead className={CALM_HEAD}>Pozycja</TableHead>
                <TableHead className={CALM_HEAD}>Numer</TableHead>
                <TableHead className={CALM_HEAD}>U kogo</TableHead>
                <TableHead className={CALM_HEAD}>Stan</TableHead>
                <TableHead className={CALM_HEAD}>Protokół</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((item) => (
                <TableRow
                  key={item.id}
                  className={`${CALM_ROW} h-[46px] cursor-pointer hover:bg-muted/50`}
                  onClick={() => onOpenItem(item.id)}
                >
                  <TableCell className="font-mono text-xs">{itemNumber(item)}</TableCell>
                  <TableCell>
                    <button
                      type="button"
                      className="text-left font-medium text-foreground hover:underline"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenItem(item.id);
                      }}
                    >
                      {CATEGORY_LABELS[item.category]} {item.model.name}
                    </button>
                    {item.ownership === "klienta" ? (
                      <span className={CALM_SUBLINE}>sprzęt klienta</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {itemIdentifier(item)}
                  </TableCell>
                  <TableCell>
                    {item.holder ? (
                      <>
                        {item.holder.name}
                        <span className={CALM_SUBLINE}>
                          {HOLDER_KIND_LABELS[item.holder.kind]}
                          {item.holder.client_name ? ` · ${item.holder.client_name}` : ""}
                        </span>
                      </>
                    ) : item.location ? (
                      <span className="text-muted-foreground">{item.location}</span>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusDot tone={ITEM_STATUS_TONE[item.status]}>
                      {ITEM_STATUS_LABELS[item.status]}
                    </StatusDot>
                  </TableCell>
                  <TableCell className="text-xs">
                    {item.issue_protocol ? (
                      <>
                        {PROTOCOL_STATUS_LABELS[item.issue_protocol.status]}
                        <span className={CALM_SUBLINE}>{item.issue_protocol.number}</span>
                      </>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
