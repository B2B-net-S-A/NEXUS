"use client";

// Rejestr aneksów w zakładce „Generator aneksów” (13.10.2026): każdy
// wygenerowany aneks — także do umowy spoza Nexusa — z odpowiedzią na „dla
// kogo, jaki aneks, od kiedy i czy podpisany”. Do tej pory aneksy leżały
// w zakładce „Dokumenty” między rozwiązaniami, bez NIP-u, zmiany i kontraktu.
// Jeden status zamiast pary „status aneksu” + „status podpisu”: przy aneksie
// obie osie mówią to samo. Stan i dzień wejścia w życie liczy serwer.

import { useMemo, useState } from "react";
import Link from "next/link";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, MoreHorizontal, Search } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { StatusDot } from "@/components/ds/StatusDot";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  B2B_DOCUMENTS_PAGE_SIZE,
  b2bDocumentsApi,
  b2bDocumentsKeys,
  useDocumentTypes,
  type DocumentItem,
  type DocumentStatusFilter,
} from "@/lib/api/b2bDocuments";
import {
  ANNEX_FAMILIES,
  annexChangeText,
  annexStateLabel,
  annexStateOf,
  annexTitle,
  readDocumentError,
  redownloadNeedsInput,
} from "@/lib/b2b-documents";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { contractDetailTabHref } from "@/lib/contract-detail-tab";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";

import {
  AnnexHistoryDialog,
  AttachScanDialog,
  LinkContractDialog,
} from "./AnnexRegisterDialogs";
import {
  CancelDocumentDialog,
  ConfirmSignedDialog,
  RedownloadDialog,
  invalidateAfterDocumentChange,
  saveDocx,
} from "./DocumentDialogs";

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-border bg-card px-3 text-sm text-foreground";

const STATE_OPTIONS: { value: DocumentStatusFilter | ""; label: string }[] = [
  { value: "", label: "Wszystkie statusy" },
  { value: "unsigned", label: "Czeka na podpis" },
  { value: "signed", label: "Podpisany" },
  { value: "cancelled", label: "Anulowany" },
  { value: "no_contract", label: "Bez kontraktu" },
];

type RowDialog =
  | { kind: "sign" | "redownload" | "scan" | "link" | "history"; item: DocumentItem }
  | { kind: "cancel" | "delete"; item: DocumentItem };

export function AnnexRegister({
  search,
  onSearch,
  onEdit,
}: {
  /** Fraza z adresu (`?q=`) — link z etykiety na wierszu umowy. */
  search: string;
  onSearch: (next: string) => void;
  /** „Popraw” otwiera kreator z zapisanym aneksem. */
  onEdit: (item: DocumentItem) => void;
}) {
  const types = useDocumentTypes();
  const annexTypes = useMemo(
    () => (types.data?.types ?? []).filter((t) => t.family === "annex"),
    [types.data],
  );
  const [documentType, setDocumentType] = useState("");
  const [status, setStatus] = useState<DocumentStatusFilter | "">("");
  const q = useDebouncedValue(search, 300).trim();
  const list = useInfiniteQuery({
    queryKey: b2bDocumentsKeys.list({
      documentType,
      status,
      q,
      family: ANNEX_FAMILIES,
    }),
    initialPageParam: 0,
    getNextPageParam: (lastPage: DocumentItem[], allPages: DocumentItem[][]) =>
      lastPage.length < B2B_DOCUMENTS_PAGE_SIZE
        ? undefined
        : allPages.length * B2B_DOCUMENTS_PAGE_SIZE,
    queryFn: ({ pageParam }: { pageParam: number }) =>
      b2bDocumentsApi.list({
        family: ANNEX_FAMILIES,
        documentType: documentType || undefined,
        status: status || undefined,
        q,
        offset: pageParam,
      }),
    staleTime: 10_000,
  });
  const rows = useMemo(() => list.data?.pages.flat() ?? [], [list.data]);
  const filtered = Boolean(documentType || status || q);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Rejestr aneksów</CardTitle>
        <CardDescription>
          Każdy wygenerowany aneks, także do umowy spoza Nexusa. Kontrakt
          zmienia się po oznaczeniu aneksu jako podpisany; anulowany aneks
          zostaje na liście.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_220px_200px]">
          <div className="space-y-1">
            <Label htmlFor="b2b-annex-register-search">Szukaj</Label>
            <div className="relative">
              <Search
                className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                id="b2b-annex-register-search"
                className="w-full pl-8"
                placeholder="Nazwisko, firma, NIP albo numer umowy"
                value={search}
                onChange={(e) => onSearch(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="b2b-annex-register-type">Typ aneksu</Label>
            <select
              id="b2b-annex-register-type"
              className={SELECT_CLASS}
              value={documentType}
              onChange={(e) => setDocumentType(e.target.value)}
            >
              <option value="">Wszystkie typy</option>
              {annexTypes.map((t) => (
                <option key={t.key} value={t.key}>
                  {annexTitle(t.key)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="b2b-annex-register-status">Status</Label>
            <select
              id="b2b-annex-register-status"
              className={SELECT_CLASS}
              value={status}
              onChange={(e) => setStatus(e.target.value as DocumentStatusFilter | "")}
            >
              {STATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <AnnexRegisterTable
          rows={rows}
          state={
            list.isPending
              ? "loading"
              : list.isError && !list.data
                ? "error"
                : list.isSuccess && rows.length === 0
                  ? "empty"
                  : "ready"
          }
          error={list.error}
          filtered={filtered}
          onRetry={() => void list.refetch()}
          hasMore={Boolean(list.hasNextPage)}
          loadingMore={list.isFetchingNextPage}
          moreFailed={list.isFetchNextPageError}
          onMore={() => void list.fetchNextPage()}
          onEdit={onEdit}
        />
      </CardContent>
    </Card>
  );
}

export type AnnexRegisterState = "loading" | "error" | "empty" | "ready";

/** Tabela bez zapytania o listę — harness montuje ją w każdym stanie. */
export function AnnexRegisterTable({
  rows,
  state,
  error,
  filtered,
  onRetry,
  hasMore,
  loadingMore,
  moreFailed,
  onMore,
  onEdit,
}: {
  rows: DocumentItem[];
  state: AnnexRegisterState;
  error?: unknown;
  filtered: boolean;
  onRetry: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  moreFailed: boolean;
  onMore: () => void;
  onEdit: (item: DocumentItem) => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const types = useDocumentTypes();
  const [dialog, setDialog] = useState<RowDialog | null>(null);
  const download = useMutation({
    mutationFn: async (item: DocumentItem) => {
      const res = await b2bDocumentsApi.redownload(item.id);
      saveDocx(
        res as { data: unknown; headers: Record<string, unknown> },
        `${item.type_label}.docx`,
      );
    },
    onError: async (e, item) => {
      const parsed = await readDocumentError(e, "Nie udało się pobrać aneksu.");
      // Serwer może wymagać danych wrażliwych, których lista nie przewidziała.
      if (parsed.code === "sensitive_values_required") {
        setDialog({ kind: "redownload", item });
      } else toast.showError(parsed.message);
    },
  });
  const restore = useMutation({
    mutationFn: (item: DocumentItem) => b2bDocumentsApi.restore(item.id),
    onSuccess: () => {
      toast.showSuccess("Aneks przywrócony — znów czeka na podpis.");
      invalidateAfterDocumentChange(queryClient);
    },
    onError: (e) =>
      toast.showError(apiErrorMessage(e, "Nie udało się przywrócić aneksu.")),
  });

  if (state === "loading") {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Wczytuję aneksy…
      </p>
    );
  }
  if (state === "error") {
    const httpStatus = (error as { response?: { status?: number } } | null)
      ?.response?.status;
    return (
      <Alert
        variant="error"
        title={
          httpStatus === 403
            ? "Nie masz dostępu do rejestru aneksów"
            : "Nie udało się wczytać aneksów"
        }
        description={
          httpStatus === 403
            ? "Poproś administratora o dostęp do Generatora Umów B2B."
            : apiErrorMessage(error, "Spróbuj ponownie za chwilę.")
        }
      >
        {httpStatus !== 403 ? (
          <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
            Ponów
          </Button>
        ) : null}
      </Alert>
    );
  }
  if (state === "empty") {
    return (
      <EmptyState
        title={filtered ? "Brak aneksów pasujących do filtrów" : "Nie ma jeszcze aneksów"}
        description={
          filtered
            ? "Zmień filtry albo wyczyść wyszukiwanie."
            : "Aneks przygotujesz powyżej: wybierz typ, potem osobę."
        }
      />
    );
  }

  return (
    <>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[980px] table-fixed text-sm">
          <colgroup>
            <col className="w-[18%]" />
            <col className="w-[19%]" />
            <col className="w-[19%]" />
            <col className="w-[9%]" />
            <col className="w-[17%]" />
            <col className="w-[12%]" />
            <col className="w-[6%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-left">
              <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Partner</th>
              <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Umowa i klient</th>
              <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Aneks</th>
              <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Wchodzi w życie</th>
              <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Status</th>
              <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Wygenerowano</th>
              <th scope="col" className={`py-2 text-right ${CALM_HEAD}`}>Akcje</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <AnnexRegisterRow
                key={item.id}
                item={item}
                downloading={download.isPending && download.variables?.id === item.id}
                restoring={restore.isPending && restore.variables?.id === item.id}
                onDownload={() =>
                  redownloadNeedsInput(item)
                    ? setDialog({ kind: "redownload", item })
                    : download.mutate(item)
                }
                onRestore={() => restore.mutate(item)}
                onDialog={(kind) => setDialog({ kind, item })}
                onEdit={() => onEdit(item)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Pokazano {rows.length}</span>
        <span>Kwoty w kolumnie „Aneks” widzą osoby z wglądem w stawki tej umowy.</span>
        {moreFailed ? (
          <span className="text-destructive">
            Nie udało się wczytać kolejnych aneksów.
          </span>
        ) : null}
        {hasMore ? (
          <Button
            variant="outline"
            size="sm"
            onClick={onMore}
            loading={loadingMore}
            disabled={loadingMore}
          >
            {moreFailed ? "Ponów" : "Pokaż więcej"}
          </Button>
        ) : null}
      </div>

      {dialog?.kind === "sign" ? (
        <ConfirmSignedDialog item={dialog.item} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "redownload" ? (
        <RedownloadDialog
          item={dialog.item}
          type={types.data?.types.find((t) => t.key === dialog.item.document_type)}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "cancel" || dialog?.kind === "delete" ? (
        <CancelDocumentDialog
          item={dialog.item}
          mode={dialog.kind}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "scan" ? (
        <AttachScanDialog item={dialog.item} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "link" ? (
        <LinkContractDialog item={dialog.item} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "history" ? (
        <AnnexHistoryDialog item={dialog.item} onClose={() => setDialog(null)} />
      ) : null}
    </>
  );
}

function AnnexRegisterRow({
  item,
  downloading,
  restoring,
  onDownload,
  onRestore,
  onDialog,
  onEdit,
}: {
  item: DocumentItem;
  downloading: boolean;
  restoring: boolean;
  onDownload: () => void;
  onRestore: () => void;
  onDialog: (kind: RowDialog["kind"]) => void;
  onEdit: () => void;
}) {
  const state = annexStateOf(item);
  const badge = annexStateLabel(state);
  const change = annexChangeText(item.change);
  const person = item.person_name || item.partner_name || "—";
  const company = [
    item.partner_legal_name && item.partner_legal_name !== person
      ? item.partner_legal_name
      : "",
    item.partner_nip ? `NIP ${item.partner_nip}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const agreement = item.parent_generated_contract_id
    ? `Umowa ${item.parent_contract_number ?? "bez numeru"}`
    : item.document_type === "annex_mandate"
      ? "Umowa zlecenie"
      : "Umowa spoza Nexusa";
  const signed = state === "signed_pending" || state === "in_force";
  const statusNote =
    state === "signed_pending" && item.effective_date
      ? `wejdzie w życie ${formatIsoDatePl(item.effective_date)}`
      : state === "in_force" && item.signed_at
        ? `podpisany ${formatIsoDatePl(item.signed_at)}`
        : state === "cancelled"
          ? item.cancelled_reason
          : state === "waiting" && !item.contract_id && item.external
            ? "podpis po powiązaniu z kontraktem"
            : null;

  return (
    <tr className={`${CALM_ROW} align-top`}>
      <td className="py-2.5 pr-3">
        {item.candidate_id ? (
          <Link
            href={`/candidates/${item.candidate_id}`}
            className="font-medium text-foreground hover:underline"
          >
            {person}
          </Link>
        ) : (
          <span className="font-medium text-foreground">{person}</span>
        )}
        {company ? <span className={CALM_SUBLINE}>{company}</span> : null}
      </td>
      <td className="py-2.5 pr-3">
        <span className="text-foreground">{agreement}</span>
        <span className={CALM_SUBLINE}>
          {item.client_name || "—"}
          {" · "}
          {item.contract_id ? (
            <Link
              href={contractDetailTabHref(
                `/contracts/${item.contract_id}`,
                "",
                "amendments",
              )}
              className="font-medium text-primary hover:underline"
            >
              Kontrakt #{item.contract_id}
            </Link>
          ) : (
            <span className="font-medium text-destructive">bez kontraktu</span>
          )}
        </span>
      </td>
      <td className="py-2.5 pr-3">
        <span className="font-medium text-foreground">
          {annexTitle(item.document_type)}
        </span>
        {change ? (
          <span className={`${CALM_SUBLINE} tabular-nums`}>
            {change.before ? (
              <>
                <span className="line-through">{change.before}</span>
                {" → "}
              </>
            ) : null}
            <span className="text-foreground">{change.after}</span>
          </span>
        ) : null}
      </td>
      <td className="whitespace-nowrap py-2.5 pr-3 tabular-nums">
        {item.effective_date ? (
          formatIsoDatePl(item.effective_date)
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </td>
      <td className="py-2.5 pr-3">
        <StatusDot tone={badge.tone} note={statusNote}>
          {badge.label}
        </StatusDot>
        {item.can_confirm_signed ? (
          <Button size="sm" className="mt-1.5" onClick={() => onDialog("sign")}>
            Oznacz jako podpisany
          </Button>
        ) : null}
        {item.can_link_contract ? (
          <Button
            size="sm"
            variant="outline"
            className="mt-1.5"
            onClick={() => onDialog("link")}
          >
            Powiąż z kontraktem
          </Button>
        ) : null}
      </td>
      <td className="py-2.5 pr-3">
        <span className="whitespace-nowrap text-xs tabular-nums text-foreground">
          {item.created_at ? formatDateTimePl(item.created_at) : "—"}
        </span>
        <span className={CALM_SUBLINE}>{item.created_by_name || "—"}</span>
      </td>
      <td className="py-2.5 text-right">
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={downloading}
            onClick={onDownload}
            title="Pobierz DOCX"
            aria-label={`Pobierz: ${item.label}`}
          >
            {downloading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Więcej akcji: ${item.label}`}
                title="Więcej akcji"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {item.can_edit ? (
                <DropdownMenuItem onSelect={onEdit}>Popraw aneks</DropdownMenuItem>
              ) : null}
              {signed && item.contract_id ? (
                <DropdownMenuItem onSelect={() => onDialog("scan")}>
                  {item.signed_scan_document_id ? "Podmień skan" : "Dołącz skan"}
                </DropdownMenuItem>
              ) : null}
              {item.can_restore ? (
                <DropdownMenuItem disabled={restoring} onSelect={onRestore}>
                  Przywróć
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem onSelect={() => onDialog("history")}>
                Historia
              </DropdownMenuItem>
              {item.can_edit ? (
                <DropdownMenuItem onSelect={() => onDialog("cancel")}>
                  Anuluj aneks
                </DropdownMenuItem>
              ) : null}
              {item.can_delete ? (
                <DropdownMenuItem
                  className="text-destructive"
                  onSelect={() => onDialog("delete")}
                >
                  Usuń aneks
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </td>
    </tr>
  );
}
