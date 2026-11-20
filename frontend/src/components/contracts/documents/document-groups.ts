/**
 * Zakładka „Dokumenty” kontraktu w wariancie A (decyzja Artura 19.11.2026,
 * makieta `makiety-kontrakty/tabs/DokumentyA.tsx` na gałęzi
 * `claude/contract-module-redesign-f8f030`): trzy karty „Obowiązuje teraz”,
 * grupy po rodzaju (Umowy · Aneksy · Zamówienia klienta · Inne) posortowane po
 * dacie z nazwy pliku, pod nimi foldery założone przez ludzi. Czyste funkcje —
 * testy w `__tests__/document-groups.test.ts`.
 *
 * Reguły folderów zostają z 0494 (`docs/claude/kontrakty/foldery-w-dokumentach-kontraktu.md`):
 * - zamówienie (typ `order`) i PDF z zakładki Zamówienia leżą zawsze w grupie
 *   zamówień, nigdy w folderze, i nie da się ich przenieść (backend: 422);
 * - plik w folderze to archiwum — nie liczy się do „Obowiązuje teraz” ani do
 *   alarmu wygasania (`summariseComplianceRisk`);
 * - plik wskazujący folder, którego już nie ma (wyścig z usunięciem), wraca do
 *   grup po rodzaju, a nie znika.
 * Plik zapisany jako „Inne” (import z SharePointa) trafia do grupy po nazwie
 * („Zamówienie nr 4 do …” → zamówienia), ale typ w bazie się nie zmienia:
 * można go przenieść do folderu i wtedy leży w folderze.
 */

import type { OrderDocumentItem } from "@/lib/api/dlPortal";
import type { ContractDocument, DocumentFolder, FileRow } from "@/lib/contract-document-folders";
import { personFromEmail } from "@/lib/contract-history";
import { formatIsoDatePl } from "@/lib/date-pl";
import { orderStatusLabel } from "@/lib/status-labels";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";

import { DOC_TYPE_LABEL } from "./doc-types";

export type DocGroupKey = "umowy" | "aneksy" | "zamowienia" | "inne";

/** import = pierwsze pobranie z SharePointa, sharepoint = synchronizacja, orders = PDF z zakładki Zamówienia. */
export type DocOrigin = "import" | "sharepoint" | "orders" | "upload";

export interface DocItem {
  key: string;
  /** Źródło wiersza — plik kontraktu albo PDF zamówienia (pobranie, usunięcie, przeniesienie). */
  row: FileRow;
  name: string;
  group: DocGroupKey;
  /** „Umowa”, „Aneks”, „Zamówienie”, „Wypowiedzenie”, „Polisa OC”, „Inne”… */
  kindLabel: string;
  /** Rodzaj odczytany z nazwy pliku — w bazie plik ma typ „Inne”. */
  kindFromName: boolean;
  /** Data z nazwy pliku (RRRR-MM-DD); `docDateUntil` = „do 30.06.2025” (termin). */
  docDate: string | null;
  docDateUntil: boolean;
  /** Znacznik dodania z API i jego dzień w kalendarzu firmy. */
  addedAt: string | null;
  addedDay: string | null;
  /** Imię i nazwisko z adresu dodającego — bez adresu e-mail na ekranie. */
  addedBy: string | null;
  origin: DocOrigin;
  sizeBytes: number | null;
  expiryDate: string | null;
  /** Istniejący folder założony przez ludzi albo `null` (plik poza folderami). */
  folderId: number | null;
  /** Zamówienia (typ `order`, PDF z zakładki Zamówienia) nie przenosi się do folderu. */
  movable: boolean;
  /** PDF z zakładki Zamówienia: numer zamówienia i jego status. */
  orderTitle: string | null;
  orderStatus: string | null;
  /** PDF bieżącego (aktywnego) zamówienia klienta. */
  active: boolean;
  /** Klucz sortowania: data z nazwy, bez niej dzień dodania; plik z SharePointa bez daty — `null` (na koniec). */
  sortDay: string | null;
}

export const DEFAULT_ORDERS_FOLDER_NAME = "Zamówienia";

export const GROUP_ORDER: readonly DocGroupKey[] = ["umowy", "aneksy", "zamowienia", "inne"];

const GROUP_LABEL: Record<DocGroupKey, string> = {
  umowy: "Umowy",
  aneksy: "Aneksy",
  zamowienia: "Zamówienia klienta",
  inne: "Inne",
};

/** Rodzaj, który nazwa grupy już mówi — w wierszu go nie powtarzamy. */
const GROUP_DEFAULT_KIND: Record<DocGroupKey, string> = {
  umowy: "Umowa",
  aneksy: "Aneks",
  zamowienia: "Zamówienie",
  inne: "Inne",
};

/**
 * Nazwa grupy na ekranie. Grupa zamówień to dawny automatyczny folder
 * „Zamówienia”: gdy ktoś zmienił mu nazwę (`orders_folder_name`), pokazujemy ją.
 */
export function groupLabel(group: DocGroupKey, ordersFolderName: string): string {
  const custom = ordersFolderName.trim();
  if (group === "zamowienia" && custom && custom !== DEFAULT_ORDERS_FOLDER_NAME) return custom;
  return GROUP_LABEL[group];
}

/** Rodzaj wart dopisku w wierszu („Wypowiedzenie” w Umowach, „Polisa OC” w Innych). */
export function kindNote(item: DocItem): string | null {
  return item.kindLabel === GROUP_DEFAULT_KIND[item.group] ? null : item.kindLabel;
}

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

/**
 * Rodzaj z nazwy pliku zapisanego jako „Inne” (import z SharePointa). Aneks,
 * wypowiedzenie i porozumienie sprawdzamy przed „umową”, bo ich nazwy
 * zwykle ją zawierają („Porozumienie o rozwiązaniu umowy”).
 */
export function kindFromFileName(name: string): { group: DocGroupKey; label: string } | null {
  if (/aneks/i.test(name)) return { group: "aneksy", label: "Aneks" };
  if (/wypowiedzeni/i.test(name)) return { group: "umowy", label: "Wypowiedzenie" };
  if (/porozumieni/i.test(name)) return { group: "umowy", label: "Porozumienie" };
  if (/zam[oó]wieni/i.test(name) || /(^|[^A-Za-z])PO\d/.test(name)) {
    return { group: "zamowienia", label: "Zamówienie" };
  }
  if (/umow/i.test(name)) return { group: "umowy", label: "Umowa" };
  return null;
}

const DMY = /(?<!\d)(\d{2})[._-](\d{2})[._-](\d{4})(?!\d)/;
const YMD = /(?<!\d)(\d{4})[_-](\d{2})[_-](\d{2})(?!\d)/;
const UNTIL_BEFORE = /(?:^|[\s_])do[\s_]*$/i;

function realDate(year: number, month: number, day: number): boolean {
  if (year < 1990 || year > 2100) return false;
  const d = new Date(Date.UTC(year, month - 1, day));
  return d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day;
}

/** Data z nazwy pliku: „31.10.2025”, „2024_05_01”, „2024-05-01”; „do 30.06.2025” to termin. */
export function dateFromName(name: string): { iso: string; until: boolean } | null {
  const read = (re: RegExp, ymd: boolean) => {
    const m = re.exec(name);
    if (!m) return null;
    const [y, mo, d] = ymd ? [m[1], m[2], m[3]] : [m[3], m[2], m[1]];
    if (!realDate(Number(y), Number(mo), Number(d))) return null;
    return { iso: `${y}-${mo}-${d}`, until: UNTIL_BEFORE.test(name.slice(0, m.index)) };
  };
  return read(DMY, false) ?? read(YMD, true);
}

/** „31.10.2025” albo „do 30.06.2025”; bez daty w nazwie — `null`. */
export function docDateLabel(item: Pick<DocItem, "docDate" | "docDateUntil">): string | null {
  if (!item.docDate) return null;
  const date = formatIsoDatePl(item.docDate);
  return item.docDateUntil ? `do ${date}` : date;
}

/** „4,8 MB”, „243 KB”; brak — „—”. */
export function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

/** Dni od dziś (kalendarz firmy) do daty; ujemne = minęło. */
export function daysFromToday(iso: string | null | undefined, today: string = warsawToday()): number | null {
  if (!iso) return null;
  const a = Date.parse(`${today}T00:00:00Z`);
  const b = Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

function originOf(source: string | null | undefined): DocOrigin {
  if (source === "sharepoint_import") return "import";
  if (source === "sharepoint") return "sharepoint";
  return "upload";
}

/** Plik skopiowany z SharePointa: dzień dodania to dzień kopii, nie data dokumentu. */
export function fromSharePoint(origin: DocOrigin): boolean {
  return origin === "import" || origin === "sharepoint";
}

function fromDoc(doc: ContractDocument, knownFolders: ReadonlySet<number>): DocItem {
  const typed = TYPE_KIND[doc.doc_type];
  const byName = !typed && (!doc.doc_type || doc.doc_type === "other") ? kindFromFileName(doc.filename) : null;
  const kind = typed ??
    byName ?? { group: "inne" as const, label: DOC_TYPE_LABEL[doc.doc_type] ?? (doc.doc_type || "Inne") };
  const isOrder = doc.doc_type === "order";
  const date = dateFromName(doc.filename);
  const origin = originOf(doc.source);
  const addedDay = warsawDateOf(doc.created_at);
  return {
    key: `doc-${doc.id}`,
    row: { kind: "doc", key: `doc-${doc.id}`, doc },
    name: doc.filename,
    group: kind.group,
    kindLabel: kind.label,
    kindFromName: byName != null,
    docDate: date?.iso ?? null,
    docDateUntil: date?.until ?? false,
    addedAt: doc.created_at ?? null,
    addedDay,
    addedBy: personFromEmail(doc.uploaded_by_email),
    origin,
    sizeBytes: doc.size_bytes,
    expiryDate: doc.expiry_date,
    folderId:
      !isOrder && doc.folder_id != null && knownFolders.has(doc.folder_id) ? doc.folder_id : null,
    movable: !isOrder,
    orderTitle: null,
    orderStatus: null,
    active: false,
    sortDay: date?.iso ?? (fromSharePoint(origin) ? null : addedDay),
  };
}

function fromOrderFile(order: OrderDocumentItem): DocItem {
  const name = order.filename || order.title;
  const date = dateFromName(name);
  const addedAt = order.uploaded_at ?? order.created_at ?? null;
  const addedDay = warsawDateOf(addedAt);
  return {
    key: `order-${order.order_id}`,
    row: { kind: "order", key: `order-${order.order_id}`, order },
    name,
    group: "zamowienia",
    kindLabel: "Zamówienie",
    kindFromName: false,
    docDate: date?.iso ?? null,
    docDateUntil: date?.until ?? false,
    addedAt,
    addedDay,
    addedBy: personFromEmail(order.uploaded_by_email),
    origin: "orders",
    sizeBytes: order.size_bytes,
    expiryDate: null,
    folderId: null,
    movable: false,
    orderTitle: order.title,
    orderStatus: order.order_status ? orderStatusLabel(order.order_status).toLocaleLowerCase("pl") : null,
    active: order.order_status === "active",
    sortDay: date?.iso ?? addedDay,
  };
}

function timestamp(value: string | null): number {
  const t = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(t) ? 0 : t;
}

/**
 * Najnowsze pierwsze: data z nazwy, a bez niej dzień dodania. Plik
 * z SharePointa (import albo synchronizacja) bez daty w nazwie idzie na
 * koniec — dzień kopii nie jest datą dokumentu (umowa z 2019 r. nie może
 * stać nad aneksem z 2024 r.).
 */
export function byDocDateDesc(a: DocItem, b: DocItem): number {
  const byDay = (b.sortDay ?? "").localeCompare(a.sortDay ?? "");
  if (byDay !== 0) return byDay;
  if (a.sortDay != null) {
    const byTime = timestamp(b.addedAt) - timestamp(a.addedAt);
    if (byTime !== 0) return byTime;
  }
  return a.name.localeCompare(b.name, "pl");
}

export interface DocSection {
  /** „group:umowy” albo „folder:12”. */
  key: string;
  kind: "group" | "folder";
  group: DocGroupKey | null;
  folder: DocumentFolder | null;
  items: DocItem[];
  /** Ile plików grupy ma rodzaj odczytany z nazwy (w bazie „Inne”). */
  namedCount: number;
  totalBytes: number;
}

export interface CurrentDocuments {
  contract: DocItem | null;
  annex: DocItem | null;
  order: DocItem | null;
}

export interface SharePointBatch {
  key: string;
  count: number;
  total: number;
  origin: "import" | "sharepoint";
  day: string | null;
  person: string | null;
}

export interface DocumentsView {
  items: DocItem[];
  sections: DocSection[];
  current: CurrentDocuments;
  batch: SharePointBatch | null;
  duplicates: Map<string, DocItem>;
  hasExpiry: boolean;
}

export function groupSectionKey(group: DocGroupKey): string {
  return `group:${group}`;
}

export function folderSectionKey(folderId: number): string {
  return `folder:${folderId}`;
}

const FOLD_MIN = 3;

export function batchKey(item: DocItem): string | null {
  return item.origin === "import" || item.origin === "sharepoint"
    ? `${item.origin}|${item.addedDay ?? ""}|${item.addedBy ?? ""}`
    : null;
}

/**
 * Pliki z SharePointa dodane jednym przebiegiem (ten sam dzień i osoba)
 * opisujemy raz nad tabelą, nie plakietką w każdym wierszu — od trzech
 * plików; przy mniejszej liczbie data w wierszu jest czytelniejsza.
 */
export function sharePointBatch(items: readonly DocItem[]): SharePointBatch | null {
  const counts = new Map<string, number>();
  for (const item of items) {
    const k = batchKey(item);
    if (k) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  let top: [string, number] | null = null;
  for (const entry of counts) if (!top || entry[1] > top[1]) top = entry;
  if (!top || top[1] < FOLD_MIN) return null;
  const first = items.find((i) => batchKey(i) === top[0]);
  if (!first) return null;
  return {
    key: top[0],
    count: top[1],
    total: items.length,
    origin: first.origin === "import" ? "import" : "sharepoint",
    day: first.addedDay,
    person: first.addedBy,
  };
}

/** „Wszystkie pliki (3) z importu z SharePointa 29.09.2026 · Anna Przykładowa” / „23 z 26 plików …”. */
export function batchSentence(batch: SharePointBatch): string {
  const day = formatIsoDatePl(batch.day);
  const what =
    batch.origin === "import"
      ? `z importu z SharePointa ${day}${batch.person ? ` · ${batch.person}` : ""}`
      : `z SharePointa (synchronizacja ${day})`;
  return batch.count === batch.total
    ? `Wszystkie pliki (${batch.count}) ${what}`
    : `${batch.count} z ${batch.total} plików ${what}`;
}

/** Ten sam rozmiar i ten sam numer w nazwie (albo ta sama nazwa) — ten sam plik dodany drugi raz? */
export function possibleDuplicates(items: readonly DocItem[]): Map<string, DocItem> {
  const digits = (name: string) => (name.match(/\d{6,}/g) ?? []).join("|");
  const out = new Map<string, DocItem>();
  items.forEach((a, i) => {
    items.slice(i + 1).forEach((b) => {
      if (!a.sizeBytes || a.sizeBytes !== b.sizeBytes) return;
      const sameName = a.name.toLocaleLowerCase("pl") === b.name.toLocaleLowerCase("pl");
      if (!sameName && (!digits(a.name) || digits(a.name) !== digits(b.name))) return;
      if (!out.has(a.key)) out.set(a.key, b);
      if (!out.has(b.key)) out.set(b.key, a);
    });
  });
  return out;
}

const normalizeNumber = (s: string) => s.toLocaleLowerCase("pl").replace(/[\s_./\\]+/g, "-");

/** Nazwa pliku niesie numer umowy („1277-2025 B2B …”, „nr 340_2019”), a nie np. „1340-2019”. */
export function nameHasContractNumber(name: string, contractNumber: string | null | undefined): boolean {
  const number = contractNumber?.trim();
  if (!number) return false;
  const escaped = normalizeNumber(number).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![\\p{L}\\d])${escaped}(?![\\p{L}\\d])`, "u").test(normalizeNumber(name));
}

/**
 * Cały układ zakładki: grupy po rodzaju z plików poza folderami (puste
 * grupy się nie pokazują), potem foldery w kolejności założenia (także
 * puste), karty „Obowiązuje teraz” i opis importu z SharePointa. Karta
 * „Umowa” woli plik z numerem bieżącej umowy w nazwie — starsza umowa
 * dodana później (jeszcze nie w folderze) nie stanie pod „nr …”.
 *
 * PDF linii zamówienia zbiorczego i kopia PDF-u jej grupy bywają tym samym
 * plikiem (19.11.2026: 14 par w 13 kontraktach). Gdy serwer to potwierdzi
 * (`same_file_document_id`, SHA-256 pliku), zostaje jeden wiersz: PDF
 * z zakładki Zamówienia, bo niesie numer i status zamówienia, a bez „Usuń”
 * nie wraca po usunięciu kopii (`jeden-plik-raz-w-dokumentach-kontraktu.md`).
 */
export function buildDocumentsView(
  docs: readonly ContractDocument[],
  folders: readonly DocumentFolder[],
  orderFiles: readonly OrderDocumentItem[],
  currentContractNumber: string | null = null,
): DocumentsView {
  const known = new Set(folders.map((f) => f.id));
  const sameAsOrderFile = new Set(
    orderFiles
      .map((order) => order.same_file_document_id)
      .filter((id): id is number => id != null),
  );
  const shownDocs = docs.filter((d) => !(d.doc_type === "order" && sameAsOrderFile.has(d.id)));
  const items = [...shownDocs.map((d) => fromDoc(d, known)), ...orderFiles.map(fromOrderFile)].sort(
    byDocDateDesc,
  );
  const loose = items.filter((i) => i.folderId == null);
  const section = (
    key: string,
    rows: DocItem[],
    group: DocGroupKey | null,
    folder: DocumentFolder | null,
  ): DocSection => ({
    key,
    kind: folder ? "folder" : "group",
    group,
    folder,
    items: rows,
    namedCount: rows.filter((r) => r.kindFromName).length,
    totalBytes: rows.reduce((sum, r) => sum + (r.sizeBytes ?? 0), 0),
  });

  const sections: DocSection[] = [
    ...GROUP_ORDER.map((g) =>
      section(
        groupSectionKey(g),
        loose.filter((i) => i.group === g),
        g,
        null,
      ),
    ).filter((s) => s.items.length > 0),
    ...folders.map((f) =>
      section(
        folderSectionKey(f.id),
        items.filter((i) => i.folderId === f.id),
        null,
        f,
      ),
    ),
  ];

  const pick = (group: DocGroupKey, label?: string) =>
    loose.find((i) => i.group === group && (!label || i.kindLabel === label)) ?? null;
  const contract =
    loose.find(
      (i) => i.group === "umowy" && i.kindLabel === "Umowa" && nameHasContractNumber(i.name, currentContractNumber),
    ) ?? pick("umowy", "Umowa");

  return {
    items,
    sections,
    current: {
      contract,
      annex: pick("aneksy"),
      order: pick("zamowienia"),
    },
    batch: sharePointBatch(items),
    duplicates: possibleDuplicates(items),
    hasExpiry: items.some((i) => Boolean(i.expiryDate)),
  };
}

const fold = (s: string) =>
  s
    .toLocaleLowerCase("pl")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/ł/g, "l");

/** Wyszukiwarka po nazwie pliku (i numerze zamówienia), bez wielkości liter i polskich znaków. */
export function matchesQuery(item: DocItem, query: string): boolean {
  const needle = fold(query.trim());
  if (!needle) return true;
  return fold(item.name).includes(needle) || (item.orderTitle != null && fold(item.orderTitle).includes(needle));
}
