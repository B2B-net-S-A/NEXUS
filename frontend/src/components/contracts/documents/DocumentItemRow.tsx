"use client";

import { useState } from "react";
import { CloudDownload, Download, FileDiff, Folder, Loader2, MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CALM_EMPTY, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { sharePointBadge } from "@/lib/contract-docs-sharepoint";
import type { DocumentFolder } from "@/lib/contract-document-folders";
import { formatIsoDatePl } from "@/lib/date-pl";
import { isDocxName } from "@/lib/legal-redline";
import { cn } from "@/lib/utils";

import { DocIcon } from "./DocIcon";
import {
  daysFromToday,
  docDateLabel,
  fmtSize,
  fromSharePoint,
  kindNote,
  type DocItem,
} from "./document-groups";
import { useDocumentFileActions } from "./useDocumentFileActions";

/** Pozycja menu wykonana po zamknięciu menu — okno otwarte w trakcie zamykania menu gubiło fokus. */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

/** Termin ważności bliżej niż 30 dni (albo już miniony) — jak dotąd ostrzeżenie kolorem. */
const SOON_DAYS = 30;

// Przyklejona pierwsza kolumna musi mieć pełne tło (zasłania kolumny pod sobą
// przy przewijaniu w bok), więc odcień najechania i zaznaczenia kładziemy na
// `bg-card` jako gradient — ten sam wzorzec co lista klientów.
const STICKY_CELL = "bg-card group-hover:bg-[linear-gradient(hsl(var(--muted)/0.3),hsl(var(--muted)/0.3))]";
const STICKY_CELL_SELECTED = "bg-card bg-[linear-gradient(hsl(var(--primary)/0.05),hsl(var(--primary)/0.05))]";

interface Props {
  item: DocItem;
  contractId: number;
  readOnly: boolean;
  /** Kolumna „Dodano” jest w tabeli. */
  showAdded: boolean;
  /** Wiersz opisany zdaniem o imporcie nad tabelą — komórka „Dodano” zostaje pusta. */
  folded: boolean;
  /** Kolumna „Ważny do” jest w tabeli (ktoś wpisał termin ważności). */
  showExpiry: boolean;
  /** Coś jest zaznaczone — pola wyboru widać w każdym wierszu, nie tylko po najechaniu. */
  selectionMode: boolean;
  selected: boolean;
  duplicateOf?: DocItem;
  /** Foldery założone przez ludzi — cele „Przenieś do folderu”. */
  folders: readonly DocumentFolder[];
  onToggle: (documentId: number) => void;
  onMove: (documentIds: number[], folderId: number | null) => void;
  onNewFolder: (documentIds: number[]) => void;
  onDelete: (item: DocItem) => void;
  /** „Popraw dokument” (asystent prawny) — tylko dla plików DOCX. */
  onRedline?: (item: DocItem) => void;
  onError: (message: string) => void;
}

function addedWho(item: DocItem): string | null {
  if (item.addedBy) return item.addedBy;
  if (fromSharePoint(item.origin)) return "z SharePointa";
  return null;
}

/**
 * Wiersz pliku w wariancie A: nazwa (klik = podgląd) z dopiskiem tylko tam,
 * gdzie jest co dopisać, data z nazwy, „Dodano” bez adresu e-mail, termin
 * ważności (gdy kolumna jest), rozmiar. Akcje widać po najechaniu albo
 * z klawiatury: „Pobierz” i „⋯” (podgląd, przeniesienie, usunięcie). Pole
 * wyboru zastępuje ikonę po najechaniu; PDF z zakładki Zamówienia i plik
 * typu Zamówienie go nie mają — leżą w grupie zamówień z definicji.
 */
export function DocumentItemRow({
  item,
  contractId,
  readOnly,
  showAdded,
  folded,
  showExpiry,
  selectionMode,
  selected,
  duplicateOf,
  folders,
  onToggle,
  onMove,
  onNewFolder,
  onDelete,
  onRedline,
  onError,
}: Props) {
  const { busy, open, download } = useDocumentFileActions(contractId, onError);
  const [menuOpen, setMenuOpen] = useState(false);

  const doc = item.row.kind === "doc" ? item.row.doc : null;
  const selectable = !readOnly && doc != null && item.movable;
  const date = docDateLabel(item);
  const who = addedWho(item);
  const expiryDays = daysFromToday(item.expiryDate);
  const sharePoint = doc ? sharePointBadge(doc) : null;
  // „z SharePointa” opisuje kolumna „Dodano” albo zdanie nad tabelą; w wierszu
  // zostaje tylko stan kopii wysłanej przez NEXUS.
  const syncState = sharePoint && sharePoint.tone !== "neutral" ? sharePoint : null;
  const kind = kindNote(item);
  // Numer zamówienia tylko wtedy, gdy nazwa pliku go nie powtarza („ZAM-2026-1001.pdf”).
  const titleInName = item.orderTitle != null && item.name.replace(/\.[^.]+$/, "") === item.orderTitle;
  const orderBits =
    item.row.kind === "order"
      ? [
          "z zakładki Zamówienia",
          item.orderTitle && !titleInName ? `zamówienie „${item.orderTitle}”` : null,
          item.orderStatus,
        ].filter((part): part is string => Boolean(part))
      : [];
  const plainBits = [kind, ...orderBits].filter((part): part is string => Boolean(part));
  const hasSubline = plainBits.length > 0 || syncState != null || duplicateOf != null;
  const moveTargets = folders.filter((f) => f.id !== item.folderId);
  const actionsVisible = busy || menuOpen;

  return (
    <tr className={cn(CALM_ROW, "group align-top", selected ? "bg-primary/5" : "hover:bg-muted/30")}>
      <td className={cn("sticky left-0 z-10 py-2.5 pl-4 pr-4", selected ? STICKY_CELL_SELECTED : STICKY_CELL)}>
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="relative mt-0.5 grid size-4 shrink-0 place-items-center">
            <DocIcon group={item.group} />
            {selectable && (
              <span
                className={cn(
                  "absolute inset-0 grid place-items-center transition-opacity",
                  !(selectionMode || selected) &&
                    "pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100",
                )}
              >
                <Checkbox
                  checked={selected}
                  onCheckedChange={() => doc && onToggle(doc.id)}
                  aria-label={`Zaznacz ${item.name}`}
                />
              </span>
            )}
          </span>
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => void open(item)}
              disabled={busy}
              title={item.name}
              className="block max-w-full text-left text-[13px] leading-5 text-foreground hover:text-primary hover:underline disabled:opacity-60"
            >
              <span className="line-clamp-2 break-words">{item.name}</span>
            </button>
            {hasSubline && (
              <span className={CALM_SUBLINE}>
                {plainBits.join(" · ")}
                {syncState && (
                  <span
                    className={syncState.tone === "warning" ? "font-medium text-warning" : undefined}
                    title={syncState.title}
                  >
                    {plainBits.length > 0 ? " · " : ""}
                    {syncState.label}
                  </span>
                )}
                {duplicateOf && (
                  <span title="Ten sam rozmiar i ten sam numer w nazwie — sprawdź, czy to nie ten sam plik dodany drugi raz.">
                    {plainBits.length > 0 || syncState ? " · " : ""}możliwy duplikat „{duplicateOf.name}”
                  </span>
                )}
              </span>
            )}
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap py-2.5 pr-4 text-[13px] leading-5 tabular-nums text-foreground">
        {date ?? <span className={CALM_EMPTY}>—</span>}
      </td>
      {showAdded && (
        <td className="py-2.5 pr-4 leading-5">
          {folded ? null : (
            <>
              <span className="inline-flex items-center gap-1.5 text-[13px] tabular-nums text-foreground">
                {fromSharePoint(item.origin) && (
                  <span title="Plik z SharePointa" className="inline-flex">
                    <CloudDownload className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="sr-only">z SharePointa, </span>
                  </span>
                )}
                {formatIsoDatePl(item.addedDay)}
              </span>
              {who && <span className={cn(CALM_SUBLINE, "truncate")}>{who}</span>}
            </>
          )}
        </td>
      )}
      {showExpiry && (
        <td className="whitespace-nowrap py-2.5 pr-4 text-[13px] leading-5 tabular-nums">
          {item.expiryDate ? (
            <span
              className={
                expiryDays != null && expiryDays <= SOON_DAYS ? "font-medium text-warning" : "text-foreground"
              }
            >
              {formatIsoDatePl(item.expiryDate)}
            </span>
          ) : (
            <span className={CALM_EMPTY}>—</span>
          )}
        </td>
      )}
      <td className="whitespace-nowrap py-2.5 pr-4 text-right text-[13px] leading-5 tabular-nums text-muted-foreground">
        {fmtSize(item.sizeBytes)}
      </td>
      <td className="py-1.5 pr-3">
        <div
          className={cn(
            "flex items-center justify-end gap-0.5 transition-opacity",
            !actionsVisible && "pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100",
          )}
        >
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => void download(item)}
            disabled={busy}
            title="Pobierz"
            aria-label={`Pobierz ${item.name}`}
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <Download className="size-4" aria-hidden="true" />
            )}
          </Button>
          {!readOnly && doc && (
            <DropdownMenu modal={false} onOpenChange={setMenuOpen}>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  title="Więcej akcji"
                  aria-label={`Więcej akcji: ${item.name}`}
                >
                  <MoreHorizontal className="size-4" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="min-w-52">
                <DropdownMenuItem onSelect={() => void open(item)}>Otwórz podgląd</DropdownMenuItem>
                {onRedline && isDocxName(doc.filename) && (
                  <DropdownMenuItem onSelect={() => deferMenuAction(() => onRedline(item))}>
                    <FileDiff className="size-4 text-muted-foreground" aria-hidden="true" />
                    Popraw dokument…
                  </DropdownMenuItem>
                )}
                {item.movable ? (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>Przenieś do folderu</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent className="min-w-56">
                      {moveTargets.map((folder) => (
                        <DropdownMenuItem key={folder.id} onSelect={() => onMove([doc.id], folder.id)}>
                          <Folder className="size-4 text-muted-foreground" aria-hidden="true" />
                          {folder.name}
                        </DropdownMenuItem>
                      ))}
                      {item.folderId != null && (
                        <DropdownMenuItem onSelect={() => onMove([doc.id], null)}>
                          Aktualna umowa (bez folderu)
                        </DropdownMenuItem>
                      )}
                      {(moveTargets.length > 0 || item.folderId != null) && <DropdownMenuSeparator />}
                      <DropdownMenuItem onSelect={() => deferMenuAction(() => onNewFolder([doc.id]))}>
                        Nowy folder z tym plikiem…
                      </DropdownMenuItem>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                ) : (
                  <DropdownMenuItem disabled>Zamówienie zostaje w grupie zamówień</DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() => deferMenuAction(() => onDelete(item))}
                  className="text-muted-foreground focus:bg-destructive/10 focus:text-destructive"
                >
                  Usuń plik…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </td>
    </tr>
  );
}
