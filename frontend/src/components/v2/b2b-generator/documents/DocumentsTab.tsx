"use client";

// Zakładka „Dokumenty” Generatora Umów B2B (`?tab=documents`): lista aneksów,
// rozwiązań i umów przedwstępnych + kreator „Nowy dokument”. Wejście z adresu
// (`?new=<typ>&parent=<id>` albo `&contract=<id>` z modułu Kontrakty) otwiera
// kreator; efekt działa na WARTOŚCI parametrów, bo link z wiersza rejestru to
// miękka nawigacja na tej samej stronie.

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  FilePen,
  FilePlus2,
  Loader2,
  MoreHorizontal,
  Search,
} from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
  type DocumentTypeDef,
} from "@/lib/api/b2bDocuments";
import {
  DOCUMENTS_INTENT_KEYS,
  documentStatusLabel,
  intentOpensWizard,
  parseDocumentsIntent,
  readDocumentError,
  redownloadNeedsInput,
} from "@/lib/b2b-documents";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";

import {
  CancelDocumentDialog,
  ConfirmSignedDialog,
  RedownloadDialog,
  saveDocx,
} from "./DocumentDialogs";
import { DocumentWizard } from "./DocumentWizard";
import { BusinessDataAnnexQueue } from "./BusinessDataAnnexQueue";

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-border bg-card px-3 text-sm text-foreground";

const STATUS_OPTIONS: { value: DocumentStatusFilter | ""; label: string }[] = [
  { value: "", label: "Wszystkie" },
  { value: "unsigned", label: "Czekające na podpis" },
  { value: "signed", label: "Podpisane" },
  { value: "cancelled", label: "Anulowane" },
];

export interface WizardState {
  key: number;
  type: string | null;
  parentId: number | null;
  contractId: number | null;
  editId: number | null;
}

export function DocumentsTab({ canGenerate = true }: { canGenerate?: boolean }) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const intent = parseDocumentsIntent(searchParams);
  const [wizard, setWizard] = useState<WizardState | null>(null);

  // Parametry kreatora z adresu — otwórz i zdejmij, żeby F5 nie wracał do
  // pustego kreatora po zapisanym dokumencie.
  useEffect(() => {
    if (!intentOpensWizard(intent)) return;
    setWizard({
      key: Date.now(),
      type: intent.newType || null,
      parentId: intent.parentId,
      contractId: intent.contractId,
      editId: null,
    });
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    for (const key of DOCUMENTS_INTENT_KEYS) params.delete(key);
    const query = params.toString();
    router.replace(query ? `${pathname ?? ""}?${query}` : (pathname ?? ""), {
      scroll: false,
    });
    // Tylko wartości parametrów — `searchParams` zmienia tożsamość przy
    // każdej nawigacji, a zdjęcie parametrów nie może otworzyć kreatora znowu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent.newType, intent.parentId, intent.contractId]);

  return (
    <DocumentsTabContent
      canGenerate={canGenerate}
      wizard={wizard}
      onOpenWizard={(next) => setWizard({ key: Date.now(), ...next })}
      onCloseWizard={() => setWizard(null)}
    />
  );
}

/** Treść zakładki bez routera — harness montuje ją z zasianym cache'em. */
export function DocumentsTabContent({
  canGenerate = true,
  wizard,
  onOpenWizard,
  onCloseWizard,
}: {
  /** Generowanie wymaga uprawnienia „Generowanie” — bez niego sama lista. */
  canGenerate?: boolean;
  wizard: WizardState | null;
  onOpenWizard: (next: Omit<WizardState, "key">) => void;
  onCloseWizard: () => void;
}) {
  const types = useDocumentTypes();
  const [documentType, setDocumentType] = useState("");
  const [status, setStatus] = useState<DocumentStatusFilter | "">("");
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search, 300).trim();
  const list = useInfiniteQuery({
    queryKey: b2bDocumentsKeys.list({ documentType, status, q }),
    initialPageParam: 0,
    getNextPageParam: (lastPage: DocumentItem[], allPages: DocumentItem[][]) =>
      lastPage.length < B2B_DOCUMENTS_PAGE_SIZE
        ? undefined
        : allPages.length * B2B_DOCUMENTS_PAGE_SIZE,
    queryFn: ({ pageParam }: { pageParam: number }) =>
      b2bDocumentsApi.list({
        documentType: documentType || undefined,
        status: status || undefined,
        q,
        offset: pageParam,
      }),
    staleTime: 10_000,
  });
  const rows = useMemo(() => list.data?.pages.flat() ?? [], [list.data]);
  const typesByKey = useMemo(
    () => new Map((types.data?.types ?? []).map((t) => [t.key, t])),
    [types.data],
  );

  return (
    <div className="space-y-4">
      {wizard && !canGenerate ? (
        <Alert
          variant="info"
          title="Generowanie dokumentów wymaga uprawnienia „Generowanie”"
          description="Możesz przeglądać i pobierać dokumenty z listy."
        />
      ) : wizard && types.data ? (
        <DocumentWizard
          key={wizard.key}
          typesData={types.data}
          initialType={wizard.type}
          initialParentId={wizard.parentId}
          initialContractId={wizard.contractId}
          editDocumentId={wizard.editId}
          onClose={onCloseWizard}
        />
      ) : wizard && types.isError ? (
        <Alert
          variant="error"
          title="Nie udało się wczytać rodzajów dokumentów"
          description={apiErrorMessage(types.error, "Spróbuj ponownie za chwilę.")}
        >
          <Button variant="outline" size="sm" className="mt-2" onClick={() => void types.refetch()}>
            Ponów
          </Button>
        </Alert>
      ) : wizard ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Wczytuję rodzaje dokumentów…
        </p>
      ) : null}

      <BusinessDataAnnexQueue
        enabled={canGenerate && !wizard}
        onStart={(row) =>
          onOpenWizard({
            type: "annex_party_data",
            parentId: row.id,
            contractId: null,
            editId: null,
          })
        }
      />

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">Dokumenty do umów</CardTitle>
            <CardDescription>
              Aneksy, porozumienia i wypowiedzenia do umów z rejestru oraz
              umowy przedwstępne. Po podpisie oznacz dokument jako podpisany —
              NEXUS zastosuje jego skutki w kontrakcie i rejestrze.
            </CardDescription>
          </div>
          {canGenerate ? (
            <Button
              onClick={() =>
                onOpenWizard({ type: null, parentId: null, contractId: null, editId: null })
              }
            >
              <FilePlus2 className="mr-1 h-4 w-4" aria-hidden="true" />
              Nowy dokument
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_220px_200px]">
            <div className="space-y-1">
              <Label htmlFor="b2b-docs-search">Szukaj</Label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <Input
                  id="b2b-docs-search"
                  className="pl-8"
                  placeholder="Partner albo numer umowy"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="b2b-docs-type">Rodzaj</Label>
              <select
                id="b2b-docs-type"
                className={SELECT_CLASS}
                value={documentType}
                onChange={(e) => setDocumentType(e.target.value)}
              >
                <option value="">Wszystkie</option>
                {(types.data?.types ?? []).map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="b2b-docs-status">Status</Label>
              <select
                id="b2b-docs-status"
                className={SELECT_CLASS}
                value={status}
                onChange={(e) => setStatus(e.target.value as DocumentStatusFilter | "")}
              >
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <DocumentsListView
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
            filtered={Boolean(documentType || status || q)}
            onRetry={() => void list.refetch()}
            hasMore={list.hasNextPage}
            loadingMore={list.isFetchingNextPage}
            moreFailed={list.isFetchNextPageError}
            onMore={() => void list.fetchNextPage()}
            typesByKey={typesByKey}
            onEdit={(item) =>
              onOpenWizard({ type: item.document_type, parentId: null, contractId: null, editId: item.id })
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}

// ── Lista ───────────────────────────────────────────────────────────────────

export type DocumentsListState = "loading" | "error" | "empty" | "ready";

export function DocumentsListView({
  rows,
  state,
  error,
  filtered,
  onRetry,
  hasMore,
  loadingMore,
  moreFailed,
  onMore,
  typesByKey,
  onEdit,
}: {
  rows: DocumentItem[];
  state: DocumentsListState;
  error?: unknown;
  filtered: boolean;
  onRetry: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  moreFailed: boolean;
  onMore: () => void;
  typesByKey: Map<string, DocumentTypeDef>;
  onEdit: (item: DocumentItem) => void;
}) {
  const toast = useToast();
  const [signRow, setSignRow] = useState<DocumentItem | null>(null);
  const [redownloadRow, setRedownloadRow] = useState<DocumentItem | null>(null);
  const [cancelRow, setCancelRow] = useState<{ item: DocumentItem; mode: "cancel" | "delete" } | null>(null);
  const download = useMutation({
    mutationFn: async (item: DocumentItem) => {
      const res = await b2bDocumentsApi.redownload(item.id);
      saveDocx(res as { data: unknown; headers: Record<string, unknown> }, `${item.type_label}.docx`);
    },
    onError: async (e, item) => {
      const parsed = await readDocumentError(e, "Nie udało się pobrać dokumentu.");
      // Serwer może wymagać danych wrażliwych, których lista nie przewidziała.
      if (parsed.code === "sensitive_values_required") setRedownloadRow(item);
      else toast.showError(parsed.message);
    },
  });

  if (state === "loading") {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Wczytuję dokumenty…
      </p>
    );
  }
  if (state === "error") {
    const status = (error as { response?: { status?: number } } | null)?.response?.status;
    return (
      <Alert
        variant="error"
        title={
          status === 403
            ? "Nie masz dostępu do dokumentów generatora umów"
            : "Nie udało się wczytać dokumentów"
        }
        description={
          status === 403
            ? "Poproś administratora o dostęp do Generatora Umów B2B."
            : apiErrorMessage(error, "Spróbuj ponownie za chwilę.")
        }
      >
        {status !== 403 ? (
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
        title={filtered ? "Brak dokumentów pasujących do filtrów" : "Nie ma jeszcze dokumentów"}
        description={
          filtered
            ? "Zmień filtry albo wyczyść wyszukiwanie."
            : "Aneks, porozumienie albo wypowiedzenie wygenerujesz przyciskiem „Nowy dokument” albo z wiersza umowy w rejestrze."
        }
      />
    );
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="py-2 pr-4 font-medium">Dokument</th>
              <th className="py-2 pr-4 font-medium">Partner</th>
              <th className="py-2 pr-4 font-medium">Klient</th>
              <th className="py-2 pr-4 font-medium">Data</th>
              <th className="py-2 pr-4 font-medium">Status podpisu</th>
              <th className="py-2 pl-2 text-right font-medium">Akcje</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => {
              const badge = documentStatusLabel(item);
              const downloading = download.isPending && download.variables?.id === item.id;
              return (
                <tr key={item.id} className="border-b border-border align-top">
                  <td className="py-2 pr-4">
                    <div className="font-medium text-foreground">{item.label}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.created_by_name || "—"} · {formatDateTimePl(item.created_at)}
                    </div>
                    {item.cancelled_reason ? (
                      <div className="text-xs text-muted-foreground">
                        Anulowano: {item.cancelled_reason}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 pr-4">{item.partner_name || "—"}</td>
                  <td className="py-2 pr-4">{item.client_name || "—"}</td>
                  <td className="whitespace-nowrap py-2 pr-4">
                    {formatIsoDatePl(item.document_date)}
                  </td>
                  <td className="py-2 pr-4">
                    <Badge variant={badge.tone}>{badge.label}</Badge>
                    {item.signed_at ? (
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {formatDateTimePl(item.signed_at)}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 pl-2 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={downloading}
                        onClick={() =>
                          redownloadNeedsInput(item) ? setRedownloadRow(item) : download.mutate(item)
                        }
                        title="Pobierz DOCX"
                        aria-label={`Pobierz: ${item.label}`}
                      >
                        {downloading ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="h-4 w-4" />
                        )}
                      </Button>
                      {item.can_edit ? (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => onEdit(item)}
                          title="Popraw dokument"
                          aria-label={`Popraw: ${item.label}`}
                        >
                          <FilePen className="h-4 w-4" />
                        </Button>
                      ) : null}
                      {item.can_confirm_signed ? (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setSignRow(item)}
                          title="Oznacz jako podpisany"
                          aria-label={`Oznacz jako podpisany: ${item.label}`}
                        >
                          <CheckCircle2 className="h-4 w-4" />
                        </Button>
                      ) : null}
                      {item.can_edit || item.can_delete ? (
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
                              <DropdownMenuItem onSelect={() => setCancelRow({ item, mode: "cancel" })}>
                                Anuluj dokument
                              </DropdownMenuItem>
                            ) : null}
                            {item.can_delete ? (
                              <DropdownMenuItem
                                className="text-destructive"
                                onSelect={() => setCancelRow({ item, mode: "delete" })}
                              >
                                Usuń dokument
                              </DropdownMenuItem>
                            ) : null}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Pokazano {rows.length}</span>
        {moreFailed ? (
          <span className="text-destructive">Nie udało się wczytać kolejnych dokumentów.</span>
        ) : null}
        {hasMore ? (
          <Button variant="outline" size="sm" onClick={onMore} loading={loadingMore} disabled={loadingMore}>
            {moreFailed ? "Ponów" : "Pokaż więcej"}
          </Button>
        ) : null}
      </div>
      {signRow ? <ConfirmSignedDialog item={signRow} onClose={() => setSignRow(null)} /> : null}
      {redownloadRow ? (
        <RedownloadDialog
          item={redownloadRow}
          type={typesByKey.get(redownloadRow.document_type)}
          onClose={() => setRedownloadRow(null)}
        />
      ) : null}
      {cancelRow ? (
        <CancelDocumentDialog
          item={cancelRow.item}
          mode={cancelRow.mode}
          onClose={() => setCancelRow(null)}
        />
      ) : null}
    </>
  );
}
