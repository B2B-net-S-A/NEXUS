"use client";

import { useDeferredValue, useState, type ReactNode } from "react";
import { MoreHorizontal, Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEquipmentItems,
  useUpdateItem,
  type EquipmentCategory,
  type EquipmentHolder,
  type EquipmentHolderKind,
  type EquipmentItem,
  type EquipmentItemStatus,
  type EquipmentSummary,
  type ItemFilters,
} from "@/lib/api/equipment";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  HOLDER_KIND_LABELS,
  ITEM_STATUS_LABELS,
  canIssue,
  groupByModel,
  itemIdentifier,
  itemNumber,
  itemTitle,
  type ModelGroup,
} from "./equipment-format";
import { CategoryIcon, HolderAvatar, ProtocolPill } from "./equipment-visuals";
import { FilterSelect } from "./FilterSelect";
import { useProtocolQuickActions } from "./useProtocolQuickActions";

/** Ile pozycji ekran czyta naraz (cały rejestr recepcji mieści się w jednym zapytaniu). */
export const ITEMS_PAGE = 500;

export type StockChip = "all" | "wydany" | "na_stanie" | "serwis" | "unsigned" | "wycofany" | "zgubiony";
export type ItemsView = "sztuki" | "modele";

interface ItemsTabProps {
  summary: EquipmentSummary | undefined;
  category: EquipmentCategory | "";
  onCategoryChange: (category: EquipmentCategory | "") => void;
  onOpenItem: (itemId: number) => void;
  onOpenProtocol: (protocolId: number) => void;
  /** „Wydaj” z wiersza — kreator z tą sztuką (osobę wybiera recepcja). */
  onIssue: (items: EquipmentItem[]) => void;
  onReturn: (holder: EquipmentHolder) => void;
  /** „Przepisz na konto” — sprzęt osoby spoza NEXUSA na jej nowe konto. */
  onMoveToAccount: (person: EquipmentHolder) => void;
  /** Widok na wejściu (`?view=modele` w adresie). */
  initialView?: ItemsView;
}

const HOLDER_OPTIONS: { value: "none" | EquipmentHolderKind; label: string }[] = [
  { value: "none", label: "Bez posiadacza" },
  { value: "user", label: HOLDER_KIND_LABELS.user },
  { value: "contract", label: HOLDER_KIND_LABELS.contract },
  { value: "external", label: HOLDER_KIND_LABELS.external },
  { value: "academy", label: HOLDER_KIND_LABELS.academy },
];

const CHIP_LABELS: Record<StockChip, string> = {
  all: "Wszystko",
  wydany: "Wydane",
  na_stanie: "Na stanie",
  serwis: "W serwisie",
  unsigned: "Bez podpisu",
  wycofany: "Wycofane",
  zgubiony: "Zgubione",
};

/** Liczniki chipów stanu z `GET /summary` (zgodne z całym rejestrem, nie z filtrem). */
export function chipCounts(summary: EquipmentSummary | undefined): Partial<Record<StockChip, number>> {
  if (!summary) return {};
  const s = summary.by_status;
  return {
    all: s.na_stanie + s.wydany + s.serwis + s.wycofany + s.zgubiony,
    wydany: s.wydany,
    na_stanie: s.na_stanie,
    serwis: s.serwis,
    unsigned: summary.unsigned_items,
    wycofany: s.wycofany,
    zgubiony: s.zgubiony,
  };
}

/** Filtry zapytania z chipa stanu (klucz cache bez pustych pól, jak w harnessie). */
export function itemFilters(
  chip: StockChip,
  category: EquipmentCategory | "",
  holder: "none" | EquipmentHolderKind | "",
  q: string,
): ItemFilters {
  const status: EquipmentItemStatus | "" =
    chip === "all" || chip === "unsigned" ? "" : chip;
  return {
    category,
    status,
    holder,
    q,
    ...(chip === "unsigned" ? { unsigned: true } : {}),
    limit: ITEMS_PAGE,
  };
}

function holderOf(item: EquipmentItem): EquipmentHolder | null {
  if (!item.holder) return null;
  return {
    kind: item.holder.kind,
    id: item.holder.id,
    name: item.holder.name,
    email: null,
    detail: HOLDER_KIND_LABELS[item.holder.kind],
  };
}

/** Ewidencja: chipy stanu, przełącznik Sztuki | Modele, akcje wiersza. */
export function ItemsTab({
  summary,
  category,
  onCategoryChange,
  onOpenItem,
  onOpenProtocol,
  onIssue,
  onReturn,
  onMoveToAccount,
  initialView = "sztuki",
}: ItemsTabProps) {
  const [query, setQuery] = useState("");
  const [chip, setChip] = useState<StockChip>("all");
  const [holder, setHolder] = useState<"none" | EquipmentHolderKind | "">("");
  const [view, setView] = useState<ItemsView>(initialView);
  const deferredQuery = useDeferredValue(query);
  const items = useEquipmentItems(itemFilters(chip, category, holder, deferredQuery));
  const quick = useProtocolQuickActions();
  const rows = items.data?.items ?? [];
  const state = resolveViewState({
    isLoading: items.isLoading,
    error: items.error,
    isSuccess: items.isSuccess,
    isEmpty: rows.length === 0,
  });
  const filtered = Boolean(query.trim() || category || chip !== "all" || holder);
  const counts = chipCounts(summary);
  const chips = (Object.keys(CHIP_LABELS) as StockChip[]).filter(
    (key) => !(key === "wycofany" || key === "zgubiony") || (counts[key] ?? 0) > 0 || chip === key,
  );

  const actions: RowActions = {
    onOpenItem,
    onOpenProtocol,
    onIssue: (item) => onIssue([item]),
    onReturn,
    onMoveToAccount,
    sendLink: quick.sendLink,
    confirmSigned: quick.confirmSigned,
    busy: quick.busy,
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {/* Jak w makiecie: pole rośnie do chipów, placeholder widać w całości (prod 20.10). */}
        <div className="relative w-full sm:w-auto sm:flex-[1_1_280px]">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj sprzętu"
            placeholder="Numer, S/N, IMEI, SIM albo osoba…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9 pl-8"
          />
        </div>
        <div role="group" aria-label="Stan sprzętu" className="flex flex-wrap gap-1.5">
          {chips.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={chip === key}
              onClick={() => setChip(key)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors",
                chip === key
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-foreground hover:bg-muted",
              )}
            >
              {CHIP_LABELS[key]}{" "}
              {counts[key] != null ? (
                <span className="tabular-nums opacity-70">{counts[key]}</span>
              ) : null}
            </button>
          ))}
        </div>
        <FilterSelect
          label="Kategoria"
          value={category}
          allLabel="Kategoria"
          options={CATEGORY_ORDER.map((value) => ({ value, label: CATEGORY_LABELS[value] }))}
          onChange={onCategoryChange}
          className="h-8 w-auto gap-2 whitespace-nowrap"
        />
        <FilterSelect
          label="Posiadacz"
          value={holder}
          allLabel="Posiadacz"
          options={HOLDER_OPTIONS}
          onChange={setHolder}
          className="h-8 w-auto gap-2 whitespace-nowrap"
        />
        <SegmentedRadio
          label="Widok ewidencji"
          size="sm"
          value={view}
          onChange={setView}
          options={[
            { value: "sztuki", label: "Sztuki" },
            { value: "modele", label: "Modele" },
          ]}
          className="ml-auto"
        />
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
      ) : view === "modele" ? (
        <ModelsView rows={rows} actions={actions} />
      ) : (
        <ItemTable rows={rows} actions={actions} />
      )}
      {items.data && items.data.total > rows.length ? (
        <p className="text-xs text-muted-foreground">
          Pokazano {rows.length} z {items.data.total} — zawęź filtrem albo wyszukaj numer.
        </p>
      ) : null}
      {quick.dialogs}
    </div>
  );
}

// ── Wiersze ───────────────────────────────────────────────────────────────────

interface RowActions {
  onOpenItem: (itemId: number) => void;
  onOpenProtocol: (protocolId: number) => void;
  onIssue: (item: EquipmentItem) => void;
  onReturn: (holder: EquipmentHolder) => void;
  onMoveToAccount: (person: EquipmentHolder) => void;
  sendLink: (protocol: { id: number; number: string }) => Promise<void>;
  confirmSigned: (protocol: { id: number; number: string }) => Promise<void>;
  busy: boolean;
}

function SectionCard({
  title,
  count,
  hint,
  children,
}: {
  title: string;
  count: ReactNode;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="rounded-lg border border-border bg-card">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2.5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          {title}
          <Badge size="sm" variant="neutral" className="tabular-nums">
            {count}
          </Badge>
        </h3>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </header>
      {children}
    </section>
  );
}

function ItemName({ item, onOpen }: { item: EquipmentItem; onOpen: () => void }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <CategoryIcon category={item.category} modelName={item.model.name} />
      <div className="min-w-0">
        <button
          type="button"
          className="text-left font-medium text-foreground hover:underline"
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
        >
          {itemTitle(item)}
        </button>
        {item.ownership === "klienta" ? (
          <Badge size="sm" variant="neutral" className="ml-1.5 align-middle">
            sprzęt klienta
          </Badge>
        ) : null}
        <span className={`${CALM_SUBLINE} font-mono`}>
          {[itemNumber(item), itemIdentifier(item)].filter((part) => part && part !== "—").join(" · ")}
        </span>
      </div>
    </div>
  );
}

function HolderCell({ item }: { item: EquipmentItem }) {
  if (item.holder) {
    return (
      <div className="flex min-w-0 items-center gap-2">
        <HolderAvatar name={item.holder.name} kind={item.holder.kind} size="sm" />
        <div className="min-w-0">
          <span className="block truncate">{item.holder.name}</span>
          <span className={CALM_SUBLINE}>
            {HOLDER_KIND_LABELS[item.holder.kind]}
            {item.holder.client_name ? ` · ${item.holder.client_name}` : ""}
          </span>
        </div>
      </div>
    );
  }
  if (item.location) return <span className="text-muted-foreground">{item.location}</span>;
  return <span className={CALM_EMPTY}>—</span>;
}

function ReturnedFromService({ item }: { item: EquipmentItem }) {
  const { showToast } = useToast();
  const update = useUpdateItem(item.id);
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={update.isPending}
      onClick={() =>
        update.mutate(
          { status: "na_stanie" },
          {
            onSuccess: () => showToast(`${itemNumber(item)} wróciło na stan`, "success"),
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
          },
        )
      }
    >
      Wróciło
    </Button>
  );
}

/** Główna akcja wiersza i menu ⋯ — zależne od stanu pozycji i protokołu. */
function ItemActions({ item, actions }: { item: EquipmentItem; actions: RowActions }) {
  const protocol = item.issue_protocol;
  const holder = holderOf(item);
  let primary: ReactNode = null;
  if (protocol?.status === "oczekuje") {
    primary = (
      <Button size="sm" variant="outline" disabled={actions.busy} onClick={() => actions.sendLink(protocol)}>
        Wyślij link
      </Button>
    );
  } else if (protocol?.status === "podpisany") {
    primary = (
      <Button size="sm" disabled={actions.busy} onClick={() => actions.confirmSigned(protocol)}>
        Potwierdź
      </Button>
    );
  } else if (item.status === "wydany" && holder) {
    primary = (
      <Button size="sm" variant="outline" onClick={() => actions.onReturn(holder)}>
        Zwrot
      </Button>
    );
  } else if (canIssue(item)) {
    primary = (
      <Button size="sm" variant="outline" onClick={() => actions.onIssue(item)}>
        Wydaj
      </Button>
    );
  } else if (item.status === "serwis") {
    primary = <ReturnedFromService item={item} />;
  }
  const label = `${itemTitle(item)} ${itemNumber(item)}`;
  return (
    <div className="flex items-center justify-end gap-1.5" onClick={(event) => event.stopPropagation()}>
      {primary}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label={`Więcej akcji: ${label}`}>
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => actions.onOpenItem(item.id)}>
            Szczegóły i historia
          </DropdownMenuItem>
          {protocol ? (
            <DropdownMenuItem onSelect={() => actions.onOpenProtocol(protocol.id)}>
              Protokół {protocol.number}
            </DropdownMenuItem>
          ) : null}
          {item.status === "wydany" &&
          holder &&
          (protocol?.status === "oczekuje" || protocol?.status === "podpisany") ? (
            <DropdownMenuItem onSelect={() => actions.onReturn(holder)}>Przyjmij zwrot</DropdownMenuItem>
          ) : null}
          {item.status === "wydany" && holder?.kind === "external" ? (
            <DropdownMenuItem onSelect={() => actions.onMoveToAccount(holder)}>
              Przepisz na konto…
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function ItemTable({
  rows,
  actions,
  showIssued = true,
  bare = false,
}: {
  rows: EquipmentItem[];
  actions: RowActions;
  showIssued?: boolean;
  /** W karcie sekcji — bez własnej ramki. */
  bare?: boolean;
}) {
  return (
    <div className={cn("relative overflow-x-auto", !bare && "rounded-lg border border-border bg-card")}>
      <Table density="compact" className="min-w-[920px]">
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} sticky left-0 bg-background`}>Pozycja</TableHead>
            <TableHead className={CALM_HEAD}>U kogo</TableHead>
            {showIssued ? <TableHead className={`${CALM_HEAD} w-28`}>Od</TableHead> : null}
            <TableHead className={CALM_HEAD}>Stan i protokół</TableHead>
            <TableHead className={`${CALM_HEAD} w-44 text-right`}>
              <span className="sr-only">Akcje</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((item) => (
            <TableRow
              key={item.id}
              className={`${CALM_ROW} h-[52px] cursor-pointer hover:bg-muted/50`}
              onClick={() => actions.onOpenItem(item.id)}
            >
              <TableCell className="sticky left-0 bg-card">
                <ItemName item={item} onOpen={() => actions.onOpenItem(item.id)} />
              </TableCell>
              <TableCell>
                <HolderCell item={item} />
              </TableCell>
              {showIssued ? (
                <TableCell className="text-xs text-muted-foreground">
                  {item.holder?.issued_at ? formatIsoDatePl(item.holder.issued_at) : "—"}
                </TableCell>
              ) : null}
              <TableCell className="text-xs">
                {item.issue_protocol ? (
                  <>
                    <ProtocolPill status={item.issue_protocol.status} />
                    <span className={`${CALM_SUBLINE} font-mono`}>{item.issue_protocol.number}</span>
                  </>
                ) : item.status === "wydany" ? (
                  <span className="text-muted-foreground">bez protokołu</span>
                ) : (
                  <Badge variant={item.status === "na_stanie" ? "success" : item.status === "serwis" ? "warning" : "neutral"}>
                    {ITEM_STATUS_LABELS[item.status]}
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                <ItemActions item={item} actions={actions} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const NUMBERS_SHOWN = 5;

function ModelTable({ groups, actions }: { groups: ModelGroup[]; actions: RowActions }) {
  return (
    <div className="relative overflow-x-auto">
      <Table density="compact" className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} sticky left-0 bg-background`}>Model</TableHead>
            <TableHead className={`${CALM_HEAD} w-24`}>Sztuk</TableHead>
            <TableHead className={CALM_HEAD}>Numery</TableHead>
            <TableHead className={`${CALM_HEAD} w-28 text-right`}>
              <span className="sr-only">Akcje</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((group) => {
            const first = group.items[0];
            const rest = group.items.length - NUMBERS_SHOWN;
            return (
              <TableRow key={group.key} className={`${CALM_ROW} h-[52px]`}>
                <TableCell className="sticky left-0 bg-card">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <CategoryIcon category={group.category} modelName={group.model.name} />
                    <div className="min-w-0">
                      <span className="block font-medium">{itemTitle(group)}</span>
                      {group.locations.length ? (
                        <span className={CALM_SUBLINE}>{group.locations.join(", ")}</span>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <span className="text-lg font-semibold tabular-nums">{group.items.length}</span>{" "}
                  <span className="text-xs text-muted-foreground">szt.</span>
                </TableCell>
                <TableCell>
                  <span className="flex flex-wrap gap-1">
                    {group.items.slice(0, NUMBERS_SHOWN).map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => actions.onOpenItem(item.id)}
                        className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11.5px] text-foreground hover:bg-muted/70"
                      >
                        {itemNumber(item) === "SIM" ? itemIdentifier(item) : itemNumber(item)}
                      </button>
                    ))}
                    {rest > 0 ? <span className="text-xs text-muted-foreground">+{rest}</span> : null}
                  </span>
                </TableCell>
                <TableCell className="text-right">
                  {canIssue(first) ? (
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Wydaj: ${group.model.name} (pierwsza wolna ${itemNumber(first)})`}
                      onClick={() => actions.onIssue(first)}
                    >
                      Wydaj
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** Ile wierszy sekcji widać, zanim recepcja kliknie „Pokaż wszystkie”. */
const SECTION_PREVIEW = 5;

function ShowAll({ hidden, label, onClick }: { hidden: number; label: string; onClick: () => void }) {
  if (hidden <= 0) return null;
  return (
    <div className="border-t border-border px-4 py-2">
      <button type="button" onClick={onClick} className="text-sm font-medium text-primary hover:underline">
        {label} ({hidden})
      </button>
    </div>
  );
}

/** „Modele”: wydane sztukami, na stanie zwinięte po modelu, serwis i reszta sztukami. */
function ModelsView({ rows, actions }: { rows: EquipmentItem[]; actions: RowActions }) {
  const [allIssued, setAllIssued] = useState(false);
  const [allModels, setAllModels] = useState(false);
  const [allOther, setAllOther] = useState(false);
  const issued = rows.filter((item) => item.status === "wydany");
  const free = rows.filter((item) => item.status === "na_stanie");
  const service = rows.filter((item) => item.status === "serwis");
  const other = rows.filter((item) => item.status === "wycofany" || item.status === "zgubiony");
  const groups = groupByModel(free);
  return (
    <div className="space-y-3">
      {issued.length ? (
        <SectionCard title="Wydane" count={issued.length}>
          <ItemTable
            bare
            rows={allIssued ? issued : issued.slice(0, SECTION_PREVIEW)}
            actions={actions}
          />
          {allIssued ? null : (
            <ShowAll
              hidden={issued.length - SECTION_PREVIEW}
              label="Pokaż wszystkie wydane"
              onClick={() => setAllIssued(true)}
            />
          )}
        </SectionCard>
      ) : null}
      {free.length ? (
        <SectionCard
          title="Na stanie"
          count={`${free.length} szt. · ${groups.length} ${groups.length === 1 ? "model" : "modeli"}`}
          hint="„Wydaj” bierze pierwszą wolną sztukę — numer zmienisz w oknie wydania"
        >
          <ModelTable groups={allModels ? groups : groups.slice(0, SECTION_PREVIEW)} actions={actions} />
          {allModels ? null : (
            <ShowAll
              hidden={groups.length - SECTION_PREVIEW}
              label="Pokaż pozostałe modele"
              onClick={() => setAllModels(true)}
            />
          )}
        </SectionCard>
      ) : null}
      {service.length ? (
        <SectionCard title="W serwisie" count={service.length}>
          <ItemTable bare rows={service} actions={actions} showIssued={false} />
        </SectionCard>
      ) : null}
      {other.length ? (
        <SectionCard title="Wycofane i zgubione" count={other.length}>
          <ItemTable
            bare
            rows={allOther ? other : other.slice(0, SECTION_PREVIEW)}
            actions={actions}
            showIssued={false}
          />
          {allOther ? null : (
            <ShowAll
              hidden={other.length - SECTION_PREVIEW}
              label="Pokaż wszystkie wycofane i zgubione"
              onClick={() => setAllOther(true)}
            />
          )}
        </SectionCard>
      ) : null}
    </div>
  );
}
