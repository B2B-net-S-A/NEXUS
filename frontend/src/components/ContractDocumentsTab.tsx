"use client";

import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FolderPlus, Loader2, Plus } from "lucide-react";

import { DocumentFileRow } from "@/components/contracts/documents/DocumentFileRow";
import { FolderHeaderRow } from "@/components/contracts/documents/FolderHeaderRow";
import { FolderSuggestionBanner } from "@/components/contracts/documents/FolderSuggestionBanner";
import { NewFolderDialog } from "@/components/contracts/documents/NewFolderDialog";
import { SelectionBar } from "@/components/contracts/documents/SelectionBar";
import {
  UploadDocumentDialog,
  type UploadRequest,
} from "@/components/contracts/documents/UploadDocumentDialog";
import {
  useDocumentFolderMutations,
  useDocumentFoldersQuery,
  useOrderFilesQuery,
} from "@/components/contracts/documents/useDocumentFolders";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useOptionalToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { contractsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  buildDocumentSections,
  complianceRelevantDocs,
  filesLabel,
  folderNameSuggestions,
  pluralForm,
  type ContractDocument,
  type FolderSection,
} from "@/lib/contract-document-folders";

export { DOC_TYPE_LABEL } from "@/components/contracts/documents/doc-types";
export type { ContractDocument } from "@/lib/contract-document-folders";

interface Props {
  contractId: number;
  /**
   * Bramka zapisu jest JEDNA i przychodzi z góry (`canEditContractDocuments`
   * z `lib/contract-access.ts`: edycja kontraktów + podgląd kwot klienta).
   * Do 02.10.2026 w środku siedział dodatkowo `RequireRole admin/delivery_lead`
   * — posiadacz uprawnienia spoza tych ról był wpuszczany z zewnątrz
   * i wyrzucany w środku (ten sam błąd co w `ContractInvoicesTab`).
   */
  readOnly?: boolean;
}

const COMPLIANCE_TYPES = new Set(["nip", "zus_certificate", "oc_policy"]);

/**
 * Inspect the list of documents and return the soonest compliance-related
 * expiry that's already past or less than 30 days away. Used by consumers
 * that want to render a "Compliance risk" badge. Pliki w folderach (np.
 * „Poprzednia umowa”) to archiwum i alarmu nie zapalają (0494).
 */
export function summariseComplianceRisk(docs: ContractDocument[] | undefined): {
  risk: "overdue" | "soon" | "ok";
  soonestDate: string | null;
  docType: string | null;
} {
  if (!docs || docs.length === 0) {
    return { risk: "ok", soonestDate: null, docType: null };
  }
  const now = Date.now();
  let soonest: { ts: number; date: string; type: string } | null = null;
  for (const d of complianceRelevantDocs(docs)) {
    if (!d.expiry_date) continue;
    if (!COMPLIANCE_TYPES.has(d.doc_type)) continue;
    const ts = new Date(d.expiry_date).getTime();
    if (Number.isNaN(ts)) continue;
    if (soonest === null || ts < soonest.ts) {
      soonest = { ts, date: d.expiry_date, type: d.doc_type };
    }
  }
  if (!soonest) return { risk: "ok", soonestDate: null, docType: null };
  const days = Math.floor((soonest.ts - now) / (1000 * 60 * 60 * 24));
  return {
    risk: days < 0 ? "overdue" : days <= 30 ? "soon" : "ok",
    soonestDate: soonest.date,
    docType: soonest.type,
  };
}

function dismissedKey(contractId: number) {
  return `nexus.contractDocs.dismissedSuggestions.${contractId}`;
}

function readDismissed(contractId: number): Set<string> {
  try {
    const raw = window.localStorage.getItem(dismissedKey(contractId));
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeDismissed(contractId: number, values: Set<string>) {
  try {
    window.localStorage.setItem(dismissedKey(contractId), JSON.stringify([...values]));
  } catch {
    // Prywatne okno albo zablokowany magazyn — podpowiedź wróci po odświeżeniu.
  }
}

function sectionKey(folder: FolderSection): string {
  return String(folder.id);
}

const TH = "px-4 py-2 text-left";

export function ContractDocumentsTab({ contractId, readOnly = false }: Props) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [newFolderFiles, setNewFolderFiles] = useState<number[] | null>(null);
  const [newFolderError, setNewFolderError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dismissed, setDismissed] = useState<Set<string>>(() => readDismissed(contractId));

  const docsQuery = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", contractId],
    queryFn: () => contractsApi.documents(contractId).then((r) => r.data),
  });
  const foldersQuery = useDocumentFoldersQuery(contractId);
  const orderFilesQuery = useOrderFilesQuery(contractId);
  const mutations = useDocumentFolderMutations(contractId);

  const orderFilesStatus = (
    orderFilesQuery.error as { response?: { status?: number } } | null
  )?.response?.status;

  const docs = useMemo(() => docsQuery.data ?? [], [docsQuery.data]);
  const folders = useMemo(() => foldersQuery.data?.folders ?? [], [foldersQuery.data]);
  const ordersName = foldersQuery.data?.orders_folder_name ?? "Zamówienia";
  const sections = useMemo(
    () => buildDocumentSections(docs, folders, orderFilesQuery.data ?? [], ordersName),
    [docs, folders, orderFilesQuery.data, ordersName],
  );
  const docsById = useMemo(() => new Map(docs.map((d) => [d.id, d])), [docs]);
  const suggestion = (foldersQuery.data?.suggestions ?? []).find(
    (s) => !dismissed.has(s.number),
  );
  const nameSuggestions = useMemo(
    () =>
      folderNameSuggestions(foldersQuery.data?.suggestions ?? [], [
        ...folders.map((f) => f.name),
        ordersName,
      ]),
    [foldersQuery.data, folders, ordersName],
  );

  const refreshDocs = () => {
    queryClient.invalidateQueries({ queryKey: ["contract-documents", contractId] });
    queryClient.invalidateQueries({ queryKey: ["contract-document-folders", contractId] });
    queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
  };

  const notify = (message: string) => {
    if (toast) toast.showToast(message, "success");
  };

  const uploadMutation = useMutation({
    mutationFn: (fd: FormData) => contractsApi.uploadDocument(contractId, fd),
    onSuccess: () => {
      refreshDocs();
      setUploadOpen(false);
      setUploadError("");
    },
    onError: (err: unknown) => {
      setUploadError(apiErrorMessage(err, "Nie udało się wgrać pliku."));
    },
  });

  const deleteDocument = async (documentId: number) => {
    try {
      await contractsApi.deleteDocument(contractId, documentId);
      setError("");
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(documentId);
        return next;
      });
      refreshDocs();
    } catch (err) {
      // Odmowa usunięcia nie może kończyć się ciszą (audyt 24.09, N10).
      setError(apiErrorMessage(err, "Nie udało się usunąć pliku."));
    }
  };

  const handleUpload = (request: UploadRequest) => {
    const fd = new FormData();
    fd.append("file", request.file);
    fd.append("doc_type", request.docType);
    if (request.expiryDate) fd.append("expiry_date", request.expiryDate);
    if (request.folderId != null) fd.append("folder_id", String(request.folderId));
    uploadMutation.mutate(fd);
  };

  const toggleSelected = (documentId: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(documentId)) next.delete(documentId);
      else next.add(documentId);
      return next;
    });

  const toggleExpanded = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const expand = (key: string) => setExpanded((prev) => new Set(prev).add(key));

  const moveSelected = (folderId: number | null) => {
    const ids = [...selected];
    mutations.moveDocuments.mutate(
      { document_ids: ids, folder_id: folderId },
      {
        onSuccess: (res) => {
          setSelected(new Set());
          setError("");
          if (folderId != null) expand(String(folderId));
          const target =
            folderId == null
              ? "„Aktualnej umowy”"
              : `folderu „${folders.find((f) => f.id === folderId)?.name ?? ""}”`;
          notify(`Przeniesiono ${filesLabel(res.moved)} do ${target}`);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się przenieść plików.")),
      },
    );
  };

  const createFolder = (name: string) => {
    const ids = newFolderFiles ?? [];
    mutations.createFolder.mutate(
      { name, document_ids: ids },
      {
        onSuccess: (res) => {
          setNewFolderFiles(null);
          setNewFolderError("");
          setSelected(new Set());
          expand(String(res.folder.id));
          notify(
            res.moved > 0
              ? `Utworzono folder „${res.folder.name}” i przeniesiono ${filesLabel(res.moved)}`
              : `Utworzono folder „${res.folder.name}”`,
          );
        },
        onError: (err) =>
          setNewFolderError(apiErrorMessage(err, "Nie udało się utworzyć folderu.")),
      },
    );
  };

  const renameFolder = async (folder: FolderSection, name: string): Promise<boolean> => {
    try {
      if (folder.auto) await mutations.renameOrdersFolder.mutateAsync(name);
      else await mutations.renameFolder.mutateAsync({ folderId: Number(folder.id), name });
      setError("");
      return true;
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zmienić nazwy folderu."));
      return false;
    }
  };

  const deleteFolder = async (folder: FolderSection) => {
    const docIds = folder.rows.flatMap((r) => (r.kind === "doc" ? [r.doc.id] : []));
    const ok = await askConfirm({
      title: `Usunąć folder „${folder.name}”?`,
      description:
        docIds.length > 0
          ? `Usuwasz tylko folder. ${filesLabel(docIds.length)} ${pluralForm(docIds.length, "zostaje i wraca", "zostają i wracają", "zostaje i wraca")} do sekcji „Aktualna umowa”. Niczego nie kasujemy w SharePoincie.`
          : "Folder jest pusty. Niczego nie kasujemy w SharePoincie.",
      confirmLabel: "Usuń folder",
      variant: "destructive",
    });
    if (!ok) return;
    mutations.deleteFolder.mutate(Number(folder.id), {
      onSuccess: (res) => {
        setError("");
        const message =
          res.released > 0
            ? `Folder usunięty · ${filesLabel(res.released)} ${pluralForm(res.released, "wrócił", "wróciły", "wróciło")} do „Aktualnej umowy”`
            : "Folder usunięty";
        if (toast) {
          toast.showActionToast(message, {
            actionLabel: "Cofnij",
            onAction: () =>
              mutations.createFolder.mutate(
                { name: folder.name, document_ids: docIds },
                {
                  onError: (err) =>
                    setError(apiErrorMessage(err, "Nie udało się przywrócić folderu.")),
                },
              ),
          });
        }
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się usunąć folderu.")),
    });
  };

  const applySuggestion = () => {
    if (!suggestion) return;
    const onError = (err: unknown) =>
      setError(apiErrorMessage(err, "Nie udało się przenieść plików."));
    if (suggestion.folder_id != null) {
      const folderId = suggestion.folder_id;
      mutations.moveDocuments.mutate(
        { document_ids: suggestion.document_ids, folder_id: folderId },
        {
          onSuccess: (res) => {
            expand(String(folderId));
            notify(`Przeniesiono ${filesLabel(res.moved)} do folderu „${suggestion.folder_name}”`);
          },
          onError,
        },
      );
      return;
    }
    mutations.createFolder.mutate(
      { name: suggestion.folder_name, document_ids: suggestion.document_ids },
      {
        onSuccess: (res) => {
          expand(String(res.folder.id));
          notify(`Utworzono folder „${res.folder.name}” i przeniesiono ${filesLabel(res.moved)}`);
        },
        onError,
      },
    );
  };

  const dismissSuggestion = () => {
    if (!suggestion) return;
    const next = new Set(dismissed).add(suggestion.number);
    setDismissed(next);
    writeDismissed(contractId, next);
  };

  const showSelect = !readOnly;
  const colCount = showSelect ? 7 : 6;
  const hasAnything = sections.current.length > 0 || sections.folders.length > 0;
  const selectedNames = (newFolderFiles ?? []).map((id) => docsById.get(id)?.filename ?? "");

  return (
    <div className="space-y-4">
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          <AlertCircle className="h-4 w-4" /> {error}
        </div>
      )}

      <div className="rounded-2xl bg-card shadow-xs dark:bg-muted">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <h3 className="text-sm font-semibold">Dokumenty</h3>
          {!readOnly && (
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setNewFolderError("");
                  setNewFolderFiles([]);
                }}
              >
                <FolderPlus className="h-4 w-4" /> Nowy folder
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setUploadError("");
                  setUploadOpen(true);
                }}
              >
                <Plus className="h-4 w-4" /> Dodaj plik
              </Button>
            </div>
          )}
        </div>

        {foldersQuery.isError && (
          <div className="px-4 pb-3">
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać folderów — pliki widać na jednej liście."
              onRetry={() => foldersQuery.refetch()}
            />
          </div>
        )}
        {orderFilesQuery.isError && orderFilesStatus !== 403 && (
          <div className="px-4 pb-3">
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać plików z zakładki Zamówienia."
              onRetry={() => orderFilesQuery.refetch()}
            />
          </div>
        )}

        {suggestion && (
          <FolderSuggestionBanner
            suggestion={suggestion}
            currentNumber={foldersQuery.data?.current_contract_number ?? null}
            readOnly={readOnly}
            pending={mutations.createFolder.isPending || mutations.moveDocuments.isPending}
            onApply={applySuggestion}
            onSelect={() => setSelected(new Set(suggestion.document_ids))}
            onDismiss={dismissSuggestion}
          />
        )}

        {!readOnly && selected.size > 0 && (
          <SelectionBar
            count={selected.size}
            folders={folders}
            pending={mutations.moveDocuments.isPending}
            onMove={moveSelected}
            onNewFolder={() => {
              setNewFolderError("");
              setNewFolderFiles([...selected]);
            }}
            onCancel={() => setSelected(new Set())}
          />
        )}

        <div className="relative overflow-x-auto">
          {docsQuery.isLoading || foldersQuery.isLoading ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 inline-block h-5 w-5 animate-spin" />
              Ładowanie dokumentów…
            </div>
          ) : docsQuery.isError ? (
            <div className="p-4">
              <QueryStateNotice
                state="error"
                description="Nie udało się wczytać dokumentów."
                onRetry={() => docsQuery.refetch()}
              />
            </div>
          ) : docsQuery.isSuccess && !hasAnything ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              Brak załączonych dokumentów.
            </div>
          ) : (
            <table className="w-full min-w-[44rem] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground dark:bg-muted/40">
                <tr>
                  {showSelect && (
                    <th className="w-10 pl-4 pr-0">
                      <span className="sr-only">Zaznacz</span>
                    </th>
                  )}
                  <th className={`sticky left-0 z-10 bg-muted ${TH}`}>Plik</th>
                  <th className={TH}>Typ</th>
                  <th className={TH}>Rozmiar</th>
                  <th className={TH}>Ważny do</th>
                  <th className={TH}>Dodano</th>
                  <th className="px-4 py-2 text-right">Akcje</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th
                    scope="colgroup"
                    colSpan={colCount}
                    className="px-4 pb-1.5 pt-3 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    Aktualna umowa
                    <span className="ml-2 font-normal normal-case tracking-normal">
                      pliki poza folderami
                    </span>
                  </th>
                </tr>
                {sections.current.length === 0 && (
                  <tr className="border-t border-border">
                    <td colSpan={colCount} className="px-4 py-3 text-sm text-muted-foreground">
                      Wszystkie pliki są w folderach.
                    </td>
                  </tr>
                )}
                {sections.current.map((row) => (
                  <DocumentFileRow
                    key={row.key}
                    row={row}
                    contractId={contractId}
                    indented={false}
                    readOnly={readOnly}
                    selected={row.kind === "doc" && selected.has(row.doc.id)}
                    onToggle={toggleSelected}
                    onDelete={deleteDocument}
                    onError={setError}
                  />
                ))}
              </tbody>
              {sections.folders.length > 0 && (
                <tbody>
                  <tr>
                    <th
                      scope="colgroup"
                      colSpan={colCount}
                      className="border-t border-border px-4 pb-1.5 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                    >
                      Foldery
                    </th>
                  </tr>
                  {sections.folders.map((folder) => {
                    const key = sectionKey(folder);
                    const isOpen = expanded.has(key);
                    return (
                      <Fragment key={key}>
                        <FolderHeaderRow
                          folder={folder}
                          expanded={isOpen}
                          readOnly={readOnly}
                          onToggle={() => toggleExpanded(key)}
                          onRename={(name) => renameFolder(folder, name)}
                          onDelete={() => void deleteFolder(folder)}
                        />
                        {isOpen &&
                          folder.rows.map((row) => (
                            <DocumentFileRow
                              key={row.key}
                              row={row}
                              contractId={contractId}
                              indented
                              readOnly={readOnly}
                              selected={row.kind === "doc" && selected.has(row.doc.id)}
                              onToggle={toggleSelected}
                              onDelete={deleteDocument}
                              onError={setError}
                            />
                          ))}
                        {isOpen && folder.rows.length === 0 && (
                          <tr className="border-t border-border">
                            <td
                              colSpan={colCount}
                              className="py-3 pl-16 pr-4 text-sm text-muted-foreground"
                            >
                              Pusty folder — zaznacz pliki na liście i wybierz „Przenieś do”.
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              )}
            </table>
          )}
        </div>
      </div>

      <NewFolderDialog
        open={newFolderFiles !== null}
        onOpenChange={(open) => {
          if (!open) setNewFolderFiles(null);
        }}
        fileNames={selectedNames}
        suggestions={nameSuggestions}
        pending={mutations.createFolder.isPending}
        error={newFolderError}
        onSubmit={createFolder}
      />
      <UploadDocumentDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        folders={folders}
        ordersFolderName={ordersName}
        pending={uploadMutation.isPending}
        error={uploadError}
        onSubmit={handleUpload}
      />
      {confirmDialog}
    </div>
  );
}
