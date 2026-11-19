"use client";
// A · Dokumenty — „Co obowiązuje + grupy”. Dziś to płaska lista plików
// z datą importu, adresem e-mail i plakietką „z SharePointa” w każdym wierszu,
// a umowę, ostatni aneks i bieżące zamówienie trzeba wyszukać wzrokiem.
// Tu: trzy karty „Obowiązuje teraz”, pod nimi grupy po rodzaju posortowane po
// dacie z nazwy pliku, import opisany raz w nagłówku grupy, akcje wiersza po
// najechaniu („Usuń” w menu zamiast czerwonego kosza), bez pustej kolumny
// „Ważny do” (termin ważności jako dopisek tylko tam, gdzie jest).
//
// Folder „Zamówienia” to w NEXUSIE widok typu `order` (reguła 0494), więc tu
// jest tą samą grupą co zamówienia rozpoznane po nazwie pliku — inaczej
// zamówienia leżałyby w dwóch miejscach. Pomocnicze funkcje są eksportowane,
// korzysta z nich wariant B (`DokumentyB.tsx`).
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  ClipboardList,
  CloudDownload,
  Download,
  FilePen,
  FileText,
  Folder,
  FolderPlus,
  MoreHorizontal,
  Plus,
  ScrollText,
  Search,
} from "lucide-react";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import api from "@/lib/api";
import type { OrderDocumentItem } from "@/lib/api/dlPortal";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import type { DocumentFoldersResponse } from "@/lib/contract-document-folders";
import { cn } from "@/lib/utils";
import { useMkContract, useMkDocuments, type MkDocument } from "../shared/data";
import { daysUntil, fmtDate, personFromEmail } from "../shared/format";
import type { TabProps } from "./types";

// ── Dane wspólne dla A i B ────────────────────────────────────────────────

export type DocGroupKey = "umowy" | "aneksy" | "zamowienia" | "inne";

export interface DocRow {
  key: string;
  name: string;
  group: DocGroupKey;
  /** „Umowa”, „Aneks”, „Zamówienie”, „Wypowiedzenie”, „NDA”, „Inne”… */
  kindLabel: string;
  /** Rodzaj wzięty z nazwy pliku — w bazie plik ma typ „Inne”. */
  kindFromName: boolean;
  /** Data z nazwy pliku (RRRR-MM-DD); `until` = „do 30.06.2025” (termin zamówienia). */
  docDate: string | null;
  docDateUntil: boolean;
  /** Dzień dodania w kalendarzu firmy i osoba (bez adresu e-mail). */
  addedDay: string;
  addedBy: string | null;
  /** import = pierwsze pobranie z SharePointa, sharepoint = późniejsza synchronizacja, orders = PDF z zakładki Zamówienia. */
  origin: "import" | "sharepoint" | "orders" | "upload";
  sizeBytes: number | null;
  expiryDate: string | null;
  folderId: number | null;
  /** Dopisek pod nazwą, np. numer zamówienia klienta przy PDF-ie z zakładki Zamówienia. */
  note: string | null;
  /** PDF bieżącego (aktywnego) zamówienia klienta. */
  active: boolean;
  /** Klucz sortowania: data z nazwy, a bez niej dzień dodania (import nie ma znaczącej daty). */
  sortDay: string | null;
}

export const GROUP_LABEL: Record<DocGroupKey, string> = {
  umowy: "Umowy",
  aneksy: "Aneksy",
  zamowienia: "Zamówienia klienta",
  inne: "Inne",
};

export const GROUP_ORDER: DocGroupKey[] = ["umowy", "aneksy", "zamowienia", "inne"];

const TYPE_KIND: Record<string, { group: DocGroupKey; label: string }> = {
  contract: { group: "umowy", label: "Umowa" },
  annex: { group: "aneksy", label: "Aneks" },
  order: { group: "zamowienia", label: "Zamówienie" },
  termination_notice: { group: "umowy", label: "Wypowiedzenie" },
  termination_agreement: { group: "umowy", label: "Porozumienie" },
  nda: { group: "inne", label: "NDA" },
  nip: { group: "inne", label: "NIP" },
  zus_certificate: { group: "inne", label: "Zaświadczenie ZUS" },
  oc_policy: { group: "inne", label: "Polisa OC" },
};

/** Rodzaj z nazwy pliku dla dokumentów zapisanych jako „Inne” (import z SharePointa). */
function kindFromFileName(name: string): { group: DocGroupKey; label: string } | null {
  if (/aneks/i.test(name)) return { group: "aneksy", label: "Aneks" };
  if (/wypowiedzeni/i.test(name)) return { group: "umowy", label: "Wypowiedzenie" };
  if (/porozumieni/i.test(name)) return { group: "umowy", label: "Porozumienie" };
  if (/zam[oó]wieni/i.test(name) || /(^|[^A-Za-z])PO\d/.test(name)) return { group: "zamowienia", label: "Zamówienie" };
  if (/umow/i.test(name)) return { group: "umowy", label: "Umowa" };
  return null;
}

const DMY = /(?<!\d)(\d{2})[._-](\d{2})[._-](\d{4})(?!\d)/;
const YMD = /(?<!\d)(\d{4})[_-](\d{2})[_-](\d{2})(?!\d)/;

/** Data z nazwy: „31.10.2025”, „2024_05_01”; „do 30.06.2025” to termin. */
export function dateFromName(name: string): { iso: string; until: boolean } | null {
  const read = (re: RegExp, ymd: boolean) => {
    const m = re.exec(name);
    if (!m) return null;
    const [y, mo, d] = ymd ? [m[1], m[2], m[3]] : [m[3], m[2], m[1]];
    const month = Number(mo);
    const day = Number(d);
    const year = Number(y);
    if (month < 1 || month > 12 || day < 1 || day > 31 || year < 1990 || year > 2100) return null;
    return { iso: `${y}-${mo}-${d}`, until: /(?:^|[\s_])do[\s_]*$/i.test(name.slice(0, m.index)) };
  };
  return read(DMY, false) ?? read(YMD, true);
}

const WARSAW_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Warsaw",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** Dzień znacznika czasu w kalendarzu firmy (RRRR-MM-DD), nie w UTC. */
export function warsawDay(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso.slice(0, 10) : WARSAW_DAY.format(t);
}

/** „4,8 MB”, „243 KB”. */
export function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

function fromContractDoc(d: MkDocument): DocRow {
  const typed = d.doc_type ? TYPE_KIND[d.doc_type] : undefined;
  const byName = typed ? null : kindFromFileName(d.filename);
  const kind = typed ?? byName ?? { group: "inne" as const, label: "Inne" };
  const date = dateFromName(d.filename);
  const origin: DocRow["origin"] =
    d.source === "sharepoint_import" ? "import" : d.source === "sharepoint" ? "sharepoint" : "upload";
  const addedDay = warsawDay(d.created_at);
  return {
    key: `doc-${d.id}`,
    name: d.filename,
    group: kind.group,
    kindLabel: kind.label,
    kindFromName: byName != null,
    docDate: date?.iso ?? null,
    docDateUntil: date?.until ?? false,
    addedDay,
    addedBy: d.uploaded_by_email ? personFromEmail(d.uploaded_by_email) : null,
    origin,
    sizeBytes: d.size_bytes,
    expiryDate: d.expiry_date,
    // Zamówienie zawsze w swojej grupie, bez względu na folder (reguła 0494).
    folderId: kind.group === "zamowienia" ? null : d.folder_id,
    note: null,
    active: false,
    sortDay: date?.iso ?? (origin === "import" ? null : addedDay),
  };
}

const ORDER_STATUS: Partial<Record<OrderDocumentItem["order_status"], string>> = {
  active: "bieżące",
  paused: "wstrzymane",
  completed: "zakończone",
  cancelled: "anulowane",
  draft: "szkic",
};

function fromOrderFile(o: OrderDocumentItem): DocRow {
  const name = o.filename ?? o.title;
  const date = dateFromName(name);
  const addedDay = warsawDay(o.uploaded_at ?? o.created_at);
  return {
    key: `order-${o.order_id}`,
    name,
    group: "zamowienia",
    kindLabel: "Zamówienie",
    kindFromName: false,
    docDate: date?.iso ?? null,
    docDateUntil: date?.until ?? false,
    addedDay,
    addedBy: o.uploaded_by_email ? personFromEmail(o.uploaded_by_email) : null,
    origin: "orders",
    sizeBytes: o.size_bytes,
    expiryDate: null,
    folderId: null,
    note: `zamówienie „${o.title}”${ORDER_STATUS[o.order_status] ? ` · ${ORDER_STATUS[o.order_status]}` : ""}`,
    active: o.order_status === "active",
    sortDay: date?.iso ?? addedDay,
  };
}

/** Najnowsze pierwsze; pliki bez daty (import bez daty w nazwie) na końcu. */
export function byDocDateDesc(a: DocRow, b: DocRow): number {
  return (b.sortDay ?? "").localeCompare(a.sortDay ?? "") || a.name.localeCompare(b.name, "pl");
}

export function buildDocRows(docs: readonly MkDocument[], orderFiles: readonly OrderDocumentItem[]): DocRow[] {
  return [...docs.map(fromContractDoc), ...orderFiles.map(fromOrderFile)].sort(byDocDateDesc);
}

/** „31.10.2025” albo „do 30.06.2025”. */
export function docDateLabel(row: DocRow): string | null {
  if (!row.docDate) return null;
  return row.docDateUntil ? `do ${fmtDate(row.docDate)}` : fmtDate(row.docDate);
}

/** Ten sam rozmiar i ten sam numer w nazwie — ten sam plik dodany drugi raz? */
export function possibleDuplicates(rows: readonly DocRow[]): Map<string, DocRow> {
  const digits = (name: string) => (name.match(/\d{6,}/g) ?? []).join("|");
  const out = new Map<string, DocRow>();
  rows.forEach((a, i) => {
    rows.slice(i + 1).forEach((b) => {
      if (!a.sizeBytes || a.sizeBytes !== b.sizeBytes) return;
      const sameName = a.name.toLocaleLowerCase("pl") === b.name.toLocaleLowerCase("pl");
      if (!sameName && (!digits(a.name) || digits(a.name) !== digits(b.name))) return;
      if (!out.has(a.key)) out.set(a.key, b);
      if (!out.has(b.key)) out.set(b.key, a);
    });
  });
  return out;
}

export interface SharePointBatch {
  key: string;
  count: number;
  total: number;
  /** „z importu z SharePointa 29.09.2026 · <osoba>”. */
  what: string;
}

const FOLD_MIN = 3;

export function batchKey(r: DocRow): string | null {
  return r.origin === "import" || r.origin === "sharepoint" ? `${r.origin}|${r.addedDay}|${r.addedBy ?? ""}` : null;
}

/**
 * Pliki z SharePointa dodane jednym przebiegiem (ta sama data i osoba) opisujemy
 * raz, nie w każdym wierszu — od trzech plików; przy mniejszej liczbie data
 * w wierszu jest czytelniejsza niż przypis.
 */
export function sharePointBatch(rows: readonly DocRow[]): SharePointBatch | null {
  const counts = new Map<string, number>();
  for (const r of rows) {
    const k = batchKey(r);
    if (k) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  if (!top || top[1] < FOLD_MIN) return null;
  const first = rows.find((r) => batchKey(r) === top[0]);
  if (!first) return null;
  const what =
    first.origin === "import"
      ? `z importu z SharePointa ${fmtDate(first.addedDay)}${first.addedBy ? ` · ${first.addedBy}` : ""}`
      : `z SharePointa (synchronizacja ${fmtDate(first.addedDay)})`;
  return { key: top[0], count: top[1], total: rows.length, what };
}

/** „Wszystkie pliki (3) z importu …” / „23 z 26 plików z importu …”. */
export function batchSentence(b: SharePointBatch): string {
  return b.count === b.total ? `Wszystkie pliki (${b.count}) ${b.what}` : `${b.count} z ${b.total} plików ${b.what}`;
}

/** Foldery użytkownika i nazwa „Zamówień” (`GET /contracts/{id}/document-folders`). */
export function useMkDocFolders(id: number) {
  return useQuery<DocumentFoldersResponse>({
    queryKey: ["mk-document-folders", id],
    queryFn: () => api.get<DocumentFoldersResponse>(`/api/contracts/${id}/document-folders`).then((r) => r.data),
    enabled: Number.isFinite(id),
  });
}

/** PDF-y z zakładki Zamówienia (403 = rola nie widzi zamówień — wtedy cicho bez nich). */
export function useMkOrderFiles(id: number) {
  return useQuery<OrderDocumentItem[]>({
    queryKey: ["mk-order-files", id],
    queryFn: () =>
      api
        .get<{ documents: OrderDocumentItem[] }>(`/api/clients/order-documents/by-contract/${id}`)
        .then((r) => r.data.documents),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

export function httpStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } } | null)?.response?.status;
}

export function DocIcon({ group, className }: { group: DocGroupKey | "folder"; className?: string }) {
  const Icon =
    group === "umowy"
      ? ScrollText
      : group === "aneksy"
        ? FilePen
        : group === "zamowienia"
          ? ClipboardList
          : group === "folder"
            ? Folder
            : FileText;
  return <Icon className={cn("size-4 shrink-0 text-muted-foreground", className)} aria-hidden />;
}

/** Pobierz + „⋯” (Przenieś, Usuń) — widoczne po najechaniu na wiersz albo z klawiatury. */
export function DocRowActions({ name, movable = true }: { name: string; movable?: boolean }) {
  return (
    <div className="flex items-center justify-end gap-0.5 transition-opacity pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:focus-within:opacity-100 pointer-fine:has-[[data-state=open]]:opacity-100">
      <Button type="button" variant="ghost" size="icon-sm" aria-label={`Pobierz ${name}`} title="Pobierz">
        <Download className="size-4" aria-hidden />
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`Więcej akcji: ${name}`} title="Więcej akcji">
            <MoreHorizontal className="size-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-48">
          <DropdownMenuItem>Otwórz podgląd</DropdownMenuItem>
          <DropdownMenuItem disabled={!movable}>
            {movable ? "Przenieś do folderu…" : "Zamówienie zostaje w swojej grupie"}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-muted-foreground focus:bg-destructive/10 focus:text-destructive">
            Usuń plik…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

// ── Wariant A ─────────────────────────────────────────────────────────────

const LONG_GROUP = 7;
const LONG_GROUP_VISIBLE = 5;

const fold = (s: string) =>
  s
    .toLocaleLowerCase("pl")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/ł/g, "l");

function nowMeta(row: DocRow): string {
  const parts: string[] = [];
  if (row.active) parts.push("bieżące zamówienie klienta");
  const past = row.docDateUntil && (daysUntil(row.docDate) ?? 0) < 0;
  if (row.docDate) parts.push(row.docDateUntil ? `${past ? "wygasło" : "ważne do"} ${fmtDate(row.docDate)}` : `z ${fmtDate(row.docDate)}`);
  else if (row.origin === "import") parts.push(`bez daty w nazwie · import ${fmtDate(row.addedDay)}`);
  else parts.push(`dodano ${fmtDate(row.addedDay)}${row.addedBy ? ` · ${row.addedBy}` : ""}`);
  return parts.join(" · ");
}

function NowCard({
  label,
  tag,
  row,
  emptyTitle,
  emptyHint,
}: {
  label: string;
  tag?: string | null;
  row: DocRow | undefined;
  emptyTitle: string;
  emptyHint: string;
}) {
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card px-4 pb-3 pt-2.5 shadow-xs">
      <div className="flex h-7 items-center justify-between gap-2">
        <h3 className={CALM_HEAD}>
          {label}
          {tag ? <span className="ml-1.5 font-normal normal-case tracking-normal">{tag}</span> : null}
        </h3>
        {row ? (
          <Button type="button" variant="ghost" size="sm" className="-mr-2 h-7 gap-1.5 px-2 text-[12px]">
            <Download className="size-3.5" aria-hidden />
            Pobierz
          </Button>
        ) : null}
      </div>
      {row ? (
        <div className="mt-1 flex min-w-0 items-start gap-2">
          <DocIcon group={row.group} className="mt-0.5" />
          <div className="min-w-0">
            <p className="line-clamp-2 break-words text-[13.5px] font-medium leading-5 text-foreground" title={row.name}>
              {row.name}
            </p>
            <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{nowMeta(row)}</p>
          </div>
        </div>
      ) : (
        <div className="mt-1">
          <p className="text-[13.5px] font-medium leading-5 text-foreground">{emptyTitle}</p>
          <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{emptyHint}</p>
        </div>
      )}
    </section>
  );
}

interface Section {
  key: string;
  label: string;
  icon: DocGroupKey | "folder";
  rows: DocRow[];
  /** Podpowiedź do nazwy grupy (np. ile zamówień rozpoznano po nazwie). */
  hint?: string;
  note?: string;
}

function AddedCell({ row }: { row: DocRow }) {
  const who =
    row.addedBy ?? (row.origin === "sharepoint" ? "z SharePointa" : row.origin === "orders" ? "z zakładki Zamówienia" : null);
  return (
    <>
      <span className="text-[13px] tabular-nums text-foreground">{fmtDate(row.addedDay)}</span>
      {who ? <span className={CALM_SUBLINE}>{who}</span> : null}
    </>
  );
}

function FileRow({
  row,
  showAdded,
  folded,
  duplicateOf,
}: {
  row: DocRow;
  showAdded: boolean;
  folded: boolean;
  duplicateOf?: DocRow;
}) {
  const date = docDateLabel(row);
  return (
    <tr className={cn(CALM_ROW, "group align-top hover:bg-muted/30")}>
      <td className="py-2.5 pl-4 pr-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <DocIcon group={row.group} className="mt-0.5" />
          <div className="min-w-0">
            <button
              type="button"
              className="block max-w-full text-left text-[13px] leading-5 text-foreground hover:text-primary hover:underline"
              title={row.name}
            >
              <span className="line-clamp-2 break-words">{row.name}</span>
            </button>
            {row.expiryDate || row.note || duplicateOf ? (
              <span className={CALM_SUBLINE}>
                {[row.expiryDate ? `ważny do ${fmtDate(row.expiryDate)}` : null, row.note].filter(Boolean).join(" · ")}
                {duplicateOf ? (
                  <span title="Ten sam rozmiar i ten sam numer w nazwie — sprawdź, czy to nie ten sam plik dodany drugi raz.">
                    {row.expiryDate || row.note ? " · " : ""}możliwy duplikat „{duplicateOf.name}”
                  </span>
                ) : null}
              </span>
            ) : null}
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap py-2.5 pr-4 text-[13px] leading-5 tabular-nums text-foreground">
        {date ?? <span className={CALM_EMPTY}>—</span>}
      </td>
      {showAdded ? (
        <td className="py-2.5 pr-4 leading-5">{folded ? null : <AddedCell row={row} />}</td>
      ) : null}
      <td className="whitespace-nowrap py-2.5 pr-4 text-right text-[13px] leading-5 tabular-nums text-muted-foreground">
        {fmtSize(row.sizeBytes)}
      </td>
      <td className="py-1.5 pr-3">
        <DocRowActions name={row.name} movable={row.group !== "zamowienia"} />
      </td>
    </tr>
  );
}

export function DokumentyA({ contractId }: TabProps) {
  const contract = useMkContract(contractId).data;
  const docsQ = useMkDocuments(contractId);
  const foldersQ = useMkDocFolders(contractId);
  const ordersQ = useMkOrderFiles(contractId);
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const [showAll, setShowAll] = useState<ReadonlySet<string>>(() => new Set());

  const ordersHidden = ordersQ.isError && httpStatus(ordersQ.error) === 403;
  const rows = useMemo(
    () => buildDocRows(docsQ.data ?? [], ordersQ.data ?? []),
    [docsQ.data, ordersQ.data],
  );
  const duplicates = useMemo(() => possibleDuplicates(rows), [rows]);
  const batch = sharePointBatch(rows);
  const isFolded = (r: DocRow) => batch != null && batchKey(r) === batch.key;
  const showAdded = rows.some((r) => !isFolded(r));
  const cols = showAdded ? 5 : 4;

  const folders = foldersQ.data?.folders ?? [];
  const folderIds = new Set(folders.map((f) => f.id));
  const live = rows.filter((r) => r.folderId == null || !folderIds.has(r.folderId));
  const pick = (group: DocGroupKey, label?: string) =>
    live.find((r) => r.group === group && (!label || r.kindLabel === label));
  const nowContract = pick("umowy", "Umowa");
  const nowAnnex = pick("aneksy");
  const nowOrder = pick("zamowienia");

  const needle = fold(query.trim());
  const matches = (r: DocRow) => !needle || fold(r.name).includes(needle);

  const sections: Section[] = [
    ...GROUP_ORDER.map((g): Section => {
      const groupRows = live.filter((r) => r.group === g);
      const named = groupRows.filter((r) => r.kindFromName).length;
      return {
        key: g,
        label: GROUP_LABEL[g],
        icon: g,
        rows: groupRows,
        hint:
          named > 0
            ? `${named} z ${groupRows.length} rozpoznano po nazwie pliku — w bazie mają typ „Inne”.`
            : undefined,
      };
    }),
    ...folders.map(
      (f): Section => ({
        key: `folder-${f.id}`,
        label: f.name,
        icon: "folder",
        rows: rows.filter((r) => r.folderId === f.id),
        note: "archiwum · pliki nie zapalają alarmu wygasania",
      }),
    ),
  ].filter((s) => s.rows.length > 0 || s.icon === "folder");

  const toggle = (set: ReadonlySet<string>, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };

  const orderPeriod =
    contract?.client_order_start_date || contract?.client_order_end_date
      ? `${fmtDate(contract.client_order_start_date)} – ${fmtDate(contract.latest_order_end_date ?? contract.client_order_end_date)}`
      : null;
  const anyMatch = sections.some((s) => s.rows.some(matches));

  return (
    <div className="space-y-4">
      <div>
        <h2 className="mb-2 text-[13.5px] font-semibold text-foreground">Obowiązuje teraz</h2>
        <div className="grid grid-cols-3 gap-3">
          <NowCard
            label="Umowa"
            tag={foldersQ.data?.current_contract_number ? `nr ${foldersQ.data.current_contract_number}` : null}
            row={nowContract}
            emptyTitle="Brak pliku umowy"
            emptyHint="Dodaj podpisaną umowę — przyda się przy aneksach i zakończeniu."
          />
          <NowCard
            label="Ostatni aneks"
            row={nowAnnex}
            emptyTitle="Brak plików aneksów"
            emptyHint="Aneksy zapisane w kontrakcie są w zakładce Aneksy."
          />
          <NowCard
            label="Najnowsze zamówienie"
            row={nowOrder}
            emptyTitle="Brak pliku zamówienia"
            emptyHint={
              orderPeriod
                ? `Zamówienie ${orderPeriod} jest w kontrakcie bez PDF-a.`
                : "Dodaj PDF zamówienia klienta."
            }
          />
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <label className="relative block w-80">
          <span className="sr-only">Szukaj w dokumentach</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Szukaj w dokumentach"
            className="h-8 w-full rounded-md border border-border bg-card pl-8 pr-3 text-[13px] text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-hidden"
          />
        </label>
        <div className="flex items-center gap-1.5">
          <Button type="button" variant="ghost" size="sm">
            <FolderPlus className="size-4" aria-hidden />
            Nowy folder
          </Button>
          <Button type="button" variant="primary" size="sm">
            <Plus className="size-4" aria-hidden />
            Dodaj plik
          </Button>
        </div>
      </div>

      {foldersQ.isError ? (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
          Nie udało się wczytać folderów — pliki z folderów widać w grupach po rodzaju.
        </p>
      ) : null}
      {ordersQ.isError && !ordersHidden ? (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
          Nie udało się wczytać PDF-ów z zakładki Zamówienia — grupa zamówień może być niepełna.
        </p>
      ) : null}

      {docsQ.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie dokumentów…</p>
      ) : docsQ.isError ? (
        <QueryStateNotice state="error" description="Nie udało się wczytać dokumentów kontraktu." onRetry={() => void docsQ.refetch()} />
      ) : docsQ.isSuccess && rows.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-5 py-6 text-[13px] text-muted-foreground shadow-xs">
          Kontrakt nie ma jeszcze dokumentów — dodaj podpisaną umowę, a pliki z SharePointa dojdą same po synchronizacji.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
          {batch ? (
            <p className="flex items-center gap-2 border-b border-border/60 px-4 py-2 text-[12px] text-muted-foreground">
              <CloudDownload className="size-3.5 shrink-0" aria-hidden />
              {batchSentence(batch)}
              {batch.count < batch.total ? " — w kolumnie „Dodano” są tylko pozostałe." : "."}
            </p>
          ) : null}
          <table className="w-full table-fixed">
            <colgroup>
              <col />
              <col className="w-[132px]" />
              {showAdded ? <col className="w-[168px]" /> : null}
              <col className="w-[84px]" />
              <col className="w-[84px]" />
            </colgroup>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className={cn(CALM_HEAD, "py-2 pl-4 pr-4")}>Nazwa</th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4")}>Data dokumentu</th>
                {showAdded ? <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4")}>Dodano</th> : null}
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4 text-right")}>Rozmiar</th>
                <th scope="col" className="py-2 pr-3">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            {sections.map((s) => {
              const visible = s.rows.filter(matches);
              if (needle && visible.length === 0) return null;
              const open = !collapsed.has(s.key) || Boolean(needle);
              const long = !needle && visible.length > LONG_GROUP && !showAll.has(s.key);
              const shown = long ? visible.slice(0, LONG_GROUP_VISIBLE) : visible;
              return (
                <tbody key={s.key}>
                  <tr className="h-10 border-b border-border/60 bg-muted/30">
                    <th scope="colgroup" colSpan={cols} className="px-4 py-1.5 text-left font-normal">
                      <div className="flex items-center justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => setCollapsed((prev) => toggle(prev, s.key))}
                          aria-expanded={open}
                          className="-ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-[13px] font-semibold text-foreground hover:bg-muted"
                          title={s.hint}
                        >
                          {open ? (
                            <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
                          ) : (
                            <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
                          )}
                          {s.icon === "folder" ? <DocIcon group="folder" /> : null}
                          {s.label}
                          <span className="rounded-full bg-muted px-1.5 text-[11px] font-medium tabular-nums text-muted-foreground">
                            {needle ? `${visible.length} z ${s.rows.length}` : s.rows.length}
                          </span>
                        </button>
                        {s.note ? <span className="truncate text-[12px] text-muted-foreground">{s.note}</span> : null}
                      </div>
                    </th>
                  </tr>
                  {open && s.rows.length === 0 ? (
                    <tr className={CALM_ROW}>
                      <td colSpan={cols} className="py-2.5 pl-11 pr-4 text-[12.5px] text-muted-foreground">
                        Pusty folder — przenieś do niego pliki z menu „⋯” przy pliku.
                      </td>
                    </tr>
                  ) : null}
                  {open
                    ? shown.map((r) => (
                        <FileRow
                          key={r.key}
                          row={r}
                          showAdded={showAdded}
                          folded={isFolded(r)}
                          duplicateOf={duplicates.get(r.key)}
                        />
                      ))
                    : null}
                  {open && long ? (
                    <tr className={cn(CALM_ROW, "h-10")}>
                      <td colSpan={cols} className="py-1.5 pl-10 pr-4">
                        <button
                          type="button"
                          onClick={() => setShowAll((prev) => toggle(prev, s.key))}
                          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[12.5px] font-medium text-primary hover:bg-primary/5"
                        >
                          <ChevronDown className="size-3.5" aria-hidden />
                          Pokaż starsze ({visible.length - LONG_GROUP_VISIBLE})
                        </button>
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              );
            })}
          </table>
          {needle && !anyMatch ? (
            <p className="px-4 py-4 text-[13px] text-muted-foreground">
              Żaden plik nie pasuje do „{query.trim()}”.
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
