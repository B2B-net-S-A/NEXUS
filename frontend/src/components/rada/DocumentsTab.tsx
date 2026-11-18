"use client";

import * as React from "react";
import { CheckCircle2, Download, FileUp, Pencil, RefreshCw, Sparkles, Trash2, Plus } from "lucide-react";

import { AppModal, FileDropZone, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CATEGORY_LABELS,
  ORGAN_LABELS,
  boardDocumentFilePath,
  useAttachBoardFile,
  useBoardDocuments,
  useBoardKrs,
  useCreateBoardDocument,
  useDeleteBoardDocument,
  useReadBoardDocument,
  useRefreshBoardKrs,
  useUpdateBoardDocument,
  type BoardDocument,
  type DocumentPeriod,
  type BoardDocumentCategory,
  type BoardOrgan,
  type DocumentFields,
  type FilingKind,
} from "@/lib/api/supervisory-board";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { cn, formatDate } from "@/lib/utils";
import { resolveViewState, isBlockingViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.docx,.doc";
const MAX_BYTES = 25 * 1024 * 1024;

const FILING_LABELS: Record<FilingKind, string> = {
  financial_statement: "sprawozdanie",
  activity_report: "sprawozdanie z działalności",
  audit_opinion: "opinia biegłego",
  approval: "uchwała zatwierdzająca",
};

const MISSING_YEARS = 4;

const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS) as BoardDocumentCategory[];

export function DocumentsTab() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasRole(user, "admin");
  const [category, setCategory] = React.useState<BoardDocumentCategory | null>(null);
  const [editing, setEditing] = React.useState<BoardDocument | "new" | null>(null);
  // Uwaga Rady z 18.11.2026: filtr roku i miesiąca powstania dokumentu
  // („czerwiec 2026 — wszystkie protokoły i uchwały z tego miesiąca”).
  const [period, setPeriod] = React.useState<DocumentPeriod>({ year: null, month: null });
  const docs = useBoardDocuments(category, period);
  const counts = new Map((docs.data?.categories ?? []).map((c) => [c.key, c]));
  const total = (docs.data?.categories ?? []).reduce((s, c) => s + c.total, 0);
  const state = resolveViewState({
    isLoading: docs.isLoading,
    isError: docs.isError,
    error: docs.error,
    isSuccess: docs.isSuccess,
    isEmpty: (docs.data?.items.length ?? 0) === 0,
  });

  return (
    <div className="space-y-3">
      <KrsPanel isAdmin={isAdmin} />
      <div className="grid gap-3 lg:grid-cols-[232px_minmax(0,1fr)]">
        <nav className="h-fit rounded-lg border border-border bg-card p-2" aria-label="Rodzaje dokumentów">
          <CategoryButton
            active={category === null}
            label="Wszystkie"
            count={total}
            onClick={() => setCategory(null)}
          />
          {CATEGORY_ORDER.map((key) => (
            <CategoryButton
              key={key}
              active={category === key}
              label={CATEGORY_LABELS[key]}
              count={counts.get(key)?.total ?? 0}
              missing={counts.get(key)?.without_file ?? 0}
              onClick={() => setCategory(key)}
            />
          ))}
        </nav>

        <section className="min-w-0 rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              {category ? CATEGORY_LABELS[category] : "Wszystkie dokumenty"}
              {period.year ? (
                <span className="font-normal text-muted-foreground">
                  {" "}
                  · {period.month ? `${MONTH_NAMES[period.month - 1]} ` : ""}
                  {period.year}
                </span>
              ) : null}
            </h2>
            <PeriodFilter years={docs.data?.years ?? []} value={period} onChange={setPeriod} />
            {isAdmin ? (
              <Button size="sm" onClick={() => setEditing("new")}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                Dodaj dokument
              </Button>
            ) : null}
          </div>
          {isBlockingViewState(state) ? (
            <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => docs.refetch()} />
          ) : state === "loading" ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Wczytuję dokumenty…</p>
          ) : state === "empty" ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {period.year
                ? "Brak dokumentów z tego okresu. Dokument bez daty liczy się według daty wpisu w KRS."
                : isAdmin
                ? "Brak dokumentów tego rodzaju. Dodaj skan z segregatora — model zaproponuje numer, datę i przedmiot."
                : "Zarząd nie dodał jeszcze dokumentów tego rodzaju."}
            </p>
          ) : (
            <DocumentsTable items={docs.data?.items ?? []} isAdmin={isAdmin} onEdit={setEditing} />
          )}
        </section>
      </div>
      {editing ? (
        <DocumentDialog
          document={editing === "new" ? null : editing}
          defaultCategory={category ?? "resolution_supervisory"}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
}

const MONTH_NAMES = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
];
const ALL = "all";

function PeriodFilter({
  years,
  value,
  onChange,
}: {
  years: number[];
  value: DocumentPeriod;
  onChange: (value: DocumentPeriod) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Select
        value={value.year ? String(value.year) : ALL}
        onValueChange={(v) => onChange(v === ALL ? { year: null, month: null } : { year: Number(v), month: value.month })}
      >
        <SelectTrigger className="h-8 w-[120px]" aria-label="Rok dokumentu">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Wszystkie lata</SelectItem>
          {years.map((y) => (
            <SelectItem key={y} value={String(y)}>
              {y}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={value.month ? String(value.month) : ALL}
        disabled={!value.year}
        onValueChange={(v) => onChange({ year: value.year, month: v === ALL ? null : Number(v) })}
      >
        <SelectTrigger className="h-8 w-[140px]" aria-label="Miesiąc dokumentu">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Cały rok</SelectItem>
          {MONTH_NAMES.map((name, i) => (
            <SelectItem key={name} value={String(i + 1)}>
              {name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function CategoryButton({
  active,
  label,
  count,
  missing = 0,
  onClick,
}: {
  active: boolean;
  label: string;
  count: number;
  missing?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "true" : undefined}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13px]",
        active ? "bg-primary/10 font-medium text-primary" : "text-foreground hover:bg-muted",
      )}
    >
      <span className="truncate">{label}</span>
      <span className="flex shrink-0 items-center gap-1.5 tabular-nums">
        {missing > 0 ? (
          <span
            className="h-1.5 w-1.5 rounded-full bg-warning"
            title={`${missing} bez skanu`}
            aria-label={`${missing} bez skanu`}
          />
        ) : null}
        <span className={cn(count === 0 && "text-muted-foreground")}>{count}</span>
      </span>
    </button>
  );
}

// ── KRS ──────────────────────────────────────────────────────────────────────

function KrsPanel({ isAdmin }: { isAdmin: boolean }) {
  const krs = useBoardKrs();
  const refresh = useRefreshBoardKrs();
  const { showToast } = useToast();
  const snap = krs.data?.snapshot ?? null;

  const onRefresh = () =>
    refresh.mutate(undefined, {
      onSuccess: (r) =>
        showToast(
          r.changed
            ? `Pobrano nowy odpis: ${r.new_entries} nowych wpisów, ${r.documents_created} nowych pozycji w dokumentach.`
            : "Odpis bez zmian od ostatniego pobrania.",
        ),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się pobrać odpisu KRS."), "error"),
    });

  if (krs.isError) {
    return <QueryStateNotice state="error" onRetry={() => krs.refetch()} />;
  }
  if (!krs.isSuccess) {
    return <div className="h-[92px] animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }
  if (!snap) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card p-4 text-sm">
        <span className="text-muted-foreground">
          Odpisu KRS jeszcze nie pobrano. NEXUS pobiera go co noc o 5:40.
        </span>
        {isAdmin ? (
          <Button size="sm" variant="outline" onClick={onRefresh} disabled={refresh.isPending}>
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            Pobierz teraz
          </Button>
        ) : null}
      </div>
    );
  }
  const last = snap.recent_entries[0];
  // Braki sprzed kilku lat to historia, nie sprawa do załatwienia.
  const firstYear = new Date().getFullYear() - MISSING_YEARS;
  const missing = snap.missing_filings.filter((m) => m.year >= firstYear);
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Fact
          label={`KRS ${snap.krs}`}
          value={`${snap.entries_count} wpisów`}
          sub={
            last
              ? `ostatni nr ${last.number} z ${formatDate(last.date)} · sprawdzono ${formatDate(snap.checked_at)}`
              : `sprawdzono ${formatDate(snap.checked_at)}`
          }
          action={
            isAdmin ? (
              <button
                type="button"
                onClick={onRefresh}
                disabled={refresh.isPending}
                className="text-muted-foreground hover:text-foreground disabled:opacity-50"
                aria-label="Pobierz odpis KRS teraz"
                title="Pobierz odpis KRS teraz"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", refresh.isPending && "animate-spin")} />
              </button>
            ) : null
          }
        />
        <Fact
          label="Kapitał zakładowy"
          value={formatCapital(snap.capital)}
          sub={snap.shares ? `${formatCount(snap.shares)} akcji` : undefined}
        />
        <Fact
          label="Organy wg KRS"
          value={`Zarząd ${snap.management.count} · Rada ${snap.supervisory_count}`}
          sub={snap.management.functions.length ? uniqueFunctions(snap.management.functions) : undefined}
        />
        <Fact
          label="Statut"
          value={snap.statute.last_act_date ? formatDate(snap.statute.last_act_date) : "—"}
          sub={
            snap.statute.last_entry_no
              ? `ostatnia zmiana, wpis ${snap.statute.last_entry_no} · zmian w KRS: ${snap.statute.changes}`
              : undefined
          }
        />
      </div>
      {missing.length > 0 ? (
        <div className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-[12px] text-warning-muted-foreground">
          <b>Brakuje w KRS:</b>{" "}
          {missing
            .map((m) => `${m.year} — ${m.missing.map((k) => FILING_LABELS[k]).join(", ")}`)
            .join("; ")}
          .
        </div>
      ) : null}
    </div>
  );
}

/** „1360000,00 PLN” z KRS → „1 360 000,00 zł”. */
export function formatCapital(raw: string | null): string {
  if (!raw) return "—";
  const match = raw.match(/^([\d\s]+)(?:,(\d+))?\s*([A-Z]{3})?$/);
  if (!match) return raw;
  const whole = Number(match[1].replace(/\s/g, "")).toLocaleString("pl-PL");
  const currency = !match[3] || match[3] === "PLN" ? "zł" : match[3];
  return `${whole},${match[2] ?? "00"} ${currency}`;
}

function formatCount(raw: string | null): string | undefined {
  if (!raw) return undefined;
  const value = Number(raw.replace(/\s/g, ""));
  return Number.isFinite(value) ? value.toLocaleString("pl-PL") : raw;
}

function uniqueFunctions(functions: string[]): string {
  const counts = new Map<string, number>();
  for (const f of functions) counts.set(f, (counts.get(f) ?? 0) + 1);
  return [...counts.entries()]
    .map(([f, n]) => `${n > 1 ? `${n} × ` : ""}${f.toLowerCase()}`)
    .join(", ");
}

function Fact({
  label,
  value,
  sub,
  action,
}: {
  label: string;
  value: string;
  sub?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3.5 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[12px] font-medium text-muted-foreground">{label}</span>
        {action}
      </div>
      <div className="mt-1 truncate text-lg font-semibold tabular-nums text-foreground">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

// ── Tabela ───────────────────────────────────────────────────────────────────

function DocumentsTable({
  items,
  isAdmin,
  onEdit,
}: {
  items: BoardDocument[];
  isAdmin: boolean;
  onEdit: (doc: BoardDocument) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
            <th className="px-2 py-1.5 font-medium">Dokument</th>
            <th className="px-2 py-1.5 font-medium">Organ</th>
            <th className="px-2 py-1.5 font-medium">Data</th>
            <th className="px-2 py-1.5 font-medium">KRS</th>
            <th className="px-2 py-1.5 font-medium">Plik</th>
            {isAdmin ? <th className="px-2 py-1.5" aria-label="Akcje" /> : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((doc) => (
            <DocumentRow key={doc.id} doc={doc} isAdmin={isAdmin} onEdit={onEdit} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DocumentRow({
  doc,
  isAdmin,
  onEdit,
}: {
  doc: BoardDocument;
  isAdmin: boolean;
  onEdit: (doc: BoardDocument) => void;
}) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const attach = useAttachBoardFile();
  const read = useReadBoardDocument();
  const remove = useDeleteBoardDocument();
  const update = useUpdateBoardDocument();
  const fileInput = React.useRef<HTMLInputElement>(null);
  const proposal = doc.extraction_status === "read" ? doc.extraction : null;

  const onFile = (file: File | undefined) => {
    if (!file) return;
    attach.mutate(
      { id: doc.id, file },
      {
        onSuccess: () => showToast("Dołączono plik."),
        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się dołączyć pliku."), "error"),
      },
    );
  };
  const onRead = () =>
    read.mutate(doc.id, {
      onSuccess: (d) =>
        showToast(
          d.extraction_status === "read"
            ? "Model zaproponował pola — sprawdź i przyjmij."
            : "Model nie odczytał dokumentu. Wpisz pola ręcznie.",
          d.extraction_status === "read" ? "success" : "info",
        ),
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się odczytać dokumentu."), "error"),
    });
  const onAccept = () => {
    if (!proposal) return;
    update.mutate(
      {
        id: doc.id,
        patch: {
          ...(proposal.category ? { category: proposal.category } : {}),
          ...(proposal.organ ? { organ: proposal.organ } : {}),
          ...(proposal.number ? { number: proposal.number } : {}),
          ...(proposal.doc_date ? { doc_date: proposal.doc_date } : {}),
          ...(proposal.subject ? { subject: proposal.subject } : {}),
        },
      },
      {
        onSuccess: () => showToast("Przyjęto propozycję."),
        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zapisać."), "error"),
      },
    );
  };
  const onDelete = async () => {
    const ok = await askConfirm({
      title: "Usunąć dokument?",
      description: `„${doc.title}” zniknie z rejestru Rady razem z plikiem.`,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(doc.id, {
      onSuccess: () => showToast("Usunięto dokument."),
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się usunąć."), "error"),
    });
  };

  return (
    <tr className="align-top">
      <td className="px-2 py-2">
        <div className="font-medium text-foreground">
          {doc.number ? <span className="mr-1 tabular-nums">nr {doc.number} ·</span> : null}
          {doc.title}
        </div>
        {doc.subject ? <div className="text-[12px] text-muted-foreground">{doc.subject}</div> : null}
        {proposal && isAdmin ? (
          <div className="mt-1 flex flex-wrap items-center gap-2 rounded-md bg-info-muted px-2 py-1 text-[12px] text-info-muted-foreground">
            <Sparkles className="h-3.5 w-3.5" />
            <span>
              Propozycja z pliku:{" "}
              {[
                proposal.number ? `nr ${proposal.number}` : null,
                proposal.doc_date ? formatDate(proposal.doc_date) : null,
                proposal.organ ? ORGAN_LABELS[proposal.organ] : null,
                proposal.subject,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
            <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={onAccept} disabled={update.isPending}>
              Przyjmij
            </Button>
          </div>
        ) : null}
      </td>
      <td className="whitespace-nowrap px-2 py-2">{doc.organ ? ORGAN_LABELS[doc.organ] : "—"}</td>
      <td className="whitespace-nowrap px-2 py-2 tabular-nums">
        {doc.doc_date ? (
          formatDate(doc.doc_date)
        ) : doc.krs_entry_date ? (
          <span className="text-muted-foreground" title="Data wpisu w KRS">
            {formatDate(doc.krs_entry_date)} (KRS)
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="whitespace-nowrap px-2 py-2">
        {doc.krs_entry_no ? (
          <Badge variant="success" size="sm" title={doc.krs_entry_date ? `wpis z ${formatDate(doc.krs_entry_date)}` : undefined}>
            wpis {doc.krs_entry_no}
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="whitespace-nowrap px-2 py-2">
        {doc.has_file ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-primary hover:underline"
            onClick={() =>
              downloadAuthenticatedFile(boardDocumentFilePath(doc.id), doc.file_name ?? "dokument").catch((e) =>
                showToast(apiErrorMessage(e, "Nie udało się pobrać pliku."), "error"),
              )
            }
          >
            <Download className="h-3.5 w-3.5" />
            Pobierz
          </button>
        ) : (
          <Badge variant="warning" size="sm">
            brak skanu
          </Badge>
        )}
      </td>
      {isAdmin ? (
        <td className="whitespace-nowrap px-2 py-2 text-right">
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            className="hidden"
            aria-label={`Plik dla: ${doc.title}`}
            onChange={(e) => {
              onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <IconButton label={doc.has_file ? "Podmień plik" : "Dołącz skan"} onClick={() => fileInput.current?.click()} busy={attach.isPending}>
            <FileUp className="h-3.5 w-3.5" />
          </IconButton>
          {doc.has_file ? (
            <IconButton label="Odczytaj pola z pliku" onClick={onRead} busy={read.isPending}>
              <Sparkles className="h-3.5 w-3.5" />
            </IconButton>
          ) : null}
          <IconButton label="Popraw opis" onClick={() => onEdit(doc)}>
            <Pencil className="h-3.5 w-3.5" />
          </IconButton>
          {doc.source === "upload" ? (
            <IconButton label="Usuń" onClick={onDelete} busy={remove.isPending}>
              <Trash2 className="h-3.5 w-3.5" />
            </IconButton>
          ) : null}
          {confirmDialog}
        </td>
      ) : null}
    </tr>
  );
}

function IconButton({
  label,
  onClick,
  busy,
  children,
}: {
  label: string;
  onClick: () => void;
  busy?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      aria-label={label}
      title={label}
      className="ml-1 inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
    >
      {children}
    </button>
  );
}

// ── Okno dodania i poprawki ──────────────────────────────────────────────────

const NO_ORGAN = "none";

function DocumentDialog({
  document,
  defaultCategory,
  onClose,
}: {
  document: BoardDocument | null;
  defaultCategory: BoardDocumentCategory;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const create = useCreateBoardDocument();
  const update = useUpdateBoardDocument();
  const [fields, setFields] = React.useState<DocumentFields>({
    category: document?.category ?? defaultCategory,
    title: document?.title ?? "",
    organ: document?.organ ?? null,
    number: document?.number ?? "",
    subject: document?.subject ?? "",
    doc_date: document?.doc_date ?? "",
  });
  const [file, setFile] = React.useState<File | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);
  const busy = create.isPending || update.isPending;
  const set = <K extends keyof DocumentFields>(key: K, value: DocumentFields[K]) =>
    setFields((prev) => ({ ...prev, [key]: value }));

  const onSave = () => {
    const payload: DocumentFields = {
      ...fields,
      title: fields.title.trim(),
      number: fields.number?.trim() || null,
      subject: fields.subject?.trim() || null,
      doc_date: fields.doc_date || null,
    };
    const done = {
      onSuccess: () => {
        showToast(document ? "Zapisano zmiany." : "Dodano dokument.");
        onClose();
      },
      onError: (e: unknown) => showToast(apiErrorMessage(e, "Nie udało się zapisać dokumentu."), "error"),
    };
    if (document) update.mutate({ id: document.id, patch: payload }, done);
    else create.mutate({ fields: payload, file }, done);
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title={document ? "Popraw opis dokumentu" : "Dodaj dokument Rady"}
      description={document ? undefined : "Plik możesz dołączyć teraz albo później. Po dołączeniu model zaproponuje numer, datę i przedmiot."}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Anuluj
          </Button>
          <Button onClick={onSave} disabled={busy || !fields.title.trim()}>
            {document ? "Zapisz" : "Dodaj"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="board-doc-title">Tytuł</Label>
          <Input
            id="board-doc-title"
            value={fields.title}
            maxLength={255}
            onChange={(e) => set("title", e.target.value)}
            placeholder="np. Uchwała Rady w sprawie budżetu na 2027"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-doc-category">Rodzaj</Label>
          <Select value={fields.category} onValueChange={(v) => set("category", v as BoardDocumentCategory)}>
            <SelectTrigger id="board-doc-category">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORY_ORDER.map((key) => (
                <SelectItem key={key} value={key}>
                  {CATEGORY_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-doc-organ">Organ</Label>
          <Select
            value={fields.organ ?? NO_ORGAN}
            onValueChange={(v) => set("organ", v === NO_ORGAN ? null : (v as BoardOrgan))}
          >
            <SelectTrigger id="board-doc-organ">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_ORGAN}>—</SelectItem>
              {(Object.keys(ORGAN_LABELS) as BoardOrgan[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {ORGAN_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-doc-number">Numer</Label>
          <Input
            id="board-doc-number"
            value={fields.number ?? ""}
            maxLength={64}
            onChange={(e) => set("number", e.target.value)}
            placeholder="np. 3/2026"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-doc-date">Data</Label>
          <Input
            id="board-doc-date"
            type="date"
            value={fields.doc_date ?? ""}
            onChange={(e) => set("doc_date", e.target.value)}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="board-doc-subject">Przedmiot</Label>
          <Textarea
            id="board-doc-subject"
            rows={2}
            maxLength={4000}
            value={fields.subject ?? ""}
            onChange={(e) => set("subject", e.target.value)}
          />
        </div>
        {document ? null : (
          <div className="sm:col-span-2">
            <FileDropZone
              file={file}
              onPick={(f) => {
                setFile(f);
                setFileError(null);
              }}
              accept={ACCEPT}
              maxBytes={MAX_BYTES}
              label="Skan dokumentu (PDF, zdjęcie albo Word, do 25 MB)"
              error={fileError}
              onError={setFileError}
              inputId="board-doc-file"
            />
          </div>
        )}
      </div>
      {document?.source === "krs" ? (
        <p className="mt-3 flex items-center gap-1 text-[12px] text-muted-foreground">
          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
          Wiersz założony z wzmianki KRS (wpis {document.krs_entry_no}); wraca co noc, więc nie da się go usunąć.
        </p>
      ) : null}
    </AppModal>
  );
}
