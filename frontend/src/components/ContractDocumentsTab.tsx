"use client";

import { useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ChevronDown, CloudDownload, FileDiff, FolderPlus, Loader2, Plus, Search } from "lucide-react";

import { DocumentGroupHeader } from "@/components/contracts/documents/DocumentGroupHeader";
import { DocumentItemRow } from "@/components/contracts/documents/DocumentItemRow";
import { DocumentSelectionBar } from "@/components/contracts/documents/DocumentSelectionBar";
import { DocumentsNowCards } from "@/components/contracts/documents/DocumentsNowCards";
import {
  batchKey,
  batchSentence,
  buildDocumentsView,
  DEFAULT_ORDERS_FOLDER_NAME,
  fmtSize,
  folderSectionKey,
  groupLabel,
  matchesQuery,
  type DocItem,
  type DocSection,
} from "@/components/contracts/documents/document-groups";
import { FolderSuggestionBanner } from "@/components/contracts/documents/FolderSuggestionBanner";
import { NewFolderDialog } from "@/components/contracts/documents/NewFolderDialog";
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
import { RedlineDialog } from "@/components/legal-assistant/redline/RedlineDialog";
import { useOptionalToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { contractsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import {
  complianceRelevantDocs,
  filesLabel,
  folderNameSuggestions,
  pluralForm,
  type ContractDocument,
} from "@/lib/contract-document-folders";
import { formatIsoDatePl } from "@/lib/date-pl";
import { isDocxName, type RedlineTarget } from "@/lib/legal-redline";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";

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

function toggledSet(set: ReadonlySet<string>, key: string): Set<string> {
  const next = new Set(set);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function docIdOf(item: DocItem): number | null {
  return item.row.kind === "doc" ? item.row.doc.id : null;
}

/** Długa grupa pokazuje pięć najnowszych plików i „Pokaż starsze”. */
const LONG_GROUP = 7;
const LONG_GROUP_VISIBLE = 5;

/**
 * Zakładka „Dokumenty” kontraktu w wariancie A (decyzja Artura 19.11.2026):
 * „Obowiązuje teraz” (umowa, ostatni aneks, najnowsze zamówienie), pasek
 * z wyszukiwarką, „Nowy folder” i „Dodaj plik”, a pod nim jedna tabela
 * z grupami po rodzaju (pliki poza folderami) i folderami pod spodem
 * (`components/contracts/documents/document-groups.ts`). Funkcje z 0494
 * zostają: foldery, przenoszenie (pole wyboru i pasek albo „⋯” przy pliku),
 * podpowiedź „Poprzednia umowa”, automatyczna grupa zamówień.
 */
export function ContractDocumentsTab({ contractId, readOnly = false }: Props) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const headingId = useId();
  const searchId = useId();
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  // Sekcje w stanie innym niż domyślny: grupy po rodzaju są rozwinięte,
  // foldery (archiwum) zwinięte — jak przed przebudową.
  const [toggled, setToggled] = useState<Set<string>>(() => new Set());
  const [showAll, setShowAll] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const [newFolderFiles, setNewFolderFiles] = useState<number[] | null>(null);
  const [newFolderError, setNewFolderError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dismissed, setDismissed] = useState<Set<string>>(() => readDismissed(contractId));
  // „Popraw dokument” (asystent prawny): plik z listy albo z dysku.
  const [redline, setRedline] = useState<{ target: RedlineTarget; title: string } | null>(null);
  const redlineInput = useRef<HTMLInputElement>(null);

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
  const ordersName = foldersQuery.data?.orders_folder_name ?? DEFAULT_ORDERS_FOLDER_NAME;
  const ordersLabel = groupLabel("zamowienia", ordersName);
  const currentNumber = foldersQuery.data?.current_contract_number ?? null;
  const view = useMemo(
    () => buildDocumentsView(docs, folders, orderFilesQuery.data ?? [], currentNumber),
    [docs, folders, orderFilesQuery.data, currentNumber],
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

  const unselect = (ids: readonly number[]) =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.delete(id);
      return next;
    });

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

  const deleteFile = async (item: DocItem) => {
    if (item.row.kind !== "doc") return;
    const doc = item.row.doc;
    const linkedToSharePoint =
      doc.source === "sharepoint" || doc.source === "sharepoint_import" || Boolean(doc.sharepoint_item_id);
    const ok = await askConfirm({
      title: `Usunąć plik „${doc.filename}”?`,
      description: linkedToSharePoint
        ? "Plik zniknie z kontraktu w NEXUSIE. Kopia w SharePoincie zostaje — usunięcie po jednej stronie nie kasuje drugiej."
        : "Plik zniknie z kontraktu w NEXUSIE.",
      confirmLabel: "Usuń plik",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await contractsApi.deleteDocument(contractId, doc.id);
      setError("");
      unselect([doc.id]);
      refreshDocs();
      notify(`Usunięto plik „${doc.filename}”`);
    } catch (err) {
      // Odmowa usunięcia nie może kończyć się ciszą (audyt 24.09, N10).
      setError(apiErrorMessage(err, "Nie udało się usunąć pliku."));
    }
  };

  const openRedline = (item: DocItem) => {
    if (item.row.kind !== "doc") return;
    const doc = item.row.doc;
    setRedline({
      target: { kind: "contract-document", contractId, documentId: doc.id, name: doc.filename, docType: doc.doc_type },
      title: doc.filename,
    });
  };

  const openRedlineFromDisk = (file: File | undefined) => {
    if (!file) return;
    if (!isDocxName(file.name)) {
      setError("„Popraw dokument” działa na plikach Worda (DOCX). Zapisz plik jako .docx i spróbuj ponownie.");
      return;
    }
    setError("");
    setRedline({ target: { kind: "file", file, contractId, generatedId: null }, title: file.name });
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

  const isOpen = (section: DocSection) =>
    section.kind === "folder" ? toggled.has(section.key) : !toggled.has(section.key);

  const expandFolder = (folderId: number) =>
    setToggled((prev) => new Set(prev).add(folderSectionKey(folderId)));

  /** Pliki z podpowiedzi „Zaznacz te pliki” mają być widać: rozwiń ich sekcje i starsze pliki. */
  const revealDocs = (ids: ReadonlySet<number>) => {
    const hit = view.sections.filter((s) =>
      s.items.some((i) => {
        const id = docIdOf(i);
        return id != null && ids.has(id);
      }),
    );
    setToggled((prev) => {
      const next = new Set(prev);
      for (const s of hit) {
        if (s.kind === "folder") next.add(s.key);
        else next.delete(s.key);
      }
      return next;
    });
    setShowAll((prev) => new Set([...prev, ...hit.map((s) => s.key)]));
  };

  const moveFiles = (ids: number[], folderId: number | null) => {
    mutations.moveDocuments.mutate(
      { document_ids: ids, folder_id: folderId },
      {
        onSuccess: (res) => {
          unselect(ids);
          setError("");
          if (folderId != null) expandFolder(folderId);
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

  const openNewFolder = (ids: number[]) => {
    setNewFolderError("");
    setNewFolderFiles(ids);
  };

  const createFolder = (name: string) => {
    const ids = newFolderFiles ?? [];
    mutations.createFolder.mutate(
      { name, document_ids: ids },
      {
        onSuccess: (res) => {
          setNewFolderFiles(null);
          setNewFolderError("");
          unselect(ids);
          expandFolder(res.folder.id);
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

  const renameSection = async (section: DocSection, name: string): Promise<boolean> => {
    try {
      if (section.folder) {
        await mutations.renameFolder.mutateAsync({ folderId: section.folder.id, name });
      } else {
        await mutations.renameOrdersFolder.mutateAsync(name);
      }
      setError("");
      return true;
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zmienić nazwy folderu."));
      return false;
    }
  };

  const deleteFolder = async (section: DocSection) => {
    const folder = section.folder;
    if (!folder) return;
    const docIds = section.items.flatMap((i) => {
      const id = docIdOf(i);
      return id == null ? [] : [id];
    });
    const ok = await askConfirm({
      title: `Usunąć folder „${folder.name}”?`,
      description:
        docIds.length > 0
          ? `Usuwasz tylko folder. ${filesLabel(docIds.length)} ${pluralForm(docIds.length, "zostaje i wraca", "zostają i wracają", "zostaje i wraca")} do „Aktualnej umowy” — to pliki poza folderami, w grupach po rodzaju. Niczego nie kasujemy w SharePoincie.`
          : "Folder jest pusty. Niczego nie kasujemy w SharePoincie.",
      confirmLabel: "Usuń folder",
      variant: "destructive",
    });
    if (!ok) return;
    mutations.deleteFolder.mutate(folder.id, {
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
            expandFolder(folderId);
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
          expandFolder(res.folder.id);
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

  const sectionLabel = (section: DocSection) =>
    section.folder ? section.folder.name : groupLabel(section.group ?? "inne", ordersName);

  const sectionNote = (section: DocSection): string | undefined => {
    if (section.folder) {
      return [
        "archiwum · pliki nie zapalają alarmu wygasania",
        section.totalBytes > 0 ? fmtSize(section.totalBytes) : null,
        `założony ${formatIsoDatePl(warsawDateOf(section.folder.created_at))}`,
      ]
        .filter(Boolean)
        .join(" · ");
    }
    if (section.group === "zamowienia") return "automatyczny folder · nowe zamówienia trafiają tu same";
    return undefined;
  };

  const needle = query.trim();
  const searching = needle.length > 0;
  const loading = docsQuery.isLoading || foldersQuery.isLoading;
  const hasAnything = view.items.length > 0 || folders.length > 0;
  const isFolded = (item: DocItem) => view.batch != null && batchKey(item) === view.batch.key;
  const showAdded = view.items.some((i) => !isFolded(i));
  const showExpiry = view.hasExpiry;
  const colCount = 4 + (showAdded ? 1 : 0) + (showExpiry ? 1 : 0);
  const selectionMode = !readOnly && selected.size > 0;
  const anyMatch = !searching || view.items.some((i) => matchesQuery(i, needle));
  const selectedNames = (newFolderFiles ?? []).map((id) => docsById.get(id)?.filename ?? "");

  return (
    <div className="space-y-4">
      {loading ? (
        <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground shadow-xs">
          <Loader2 className="mr-2 inline-block h-5 w-5 animate-spin" aria-hidden="true" />
          Ładowanie dokumentów…
        </div>
      ) : docsQuery.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać dokumentów."
          onRetry={() => docsQuery.refetch()}
        />
      ) : (
        <>
          {hasAnything && (
            <section aria-labelledby={headingId}>
              <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <h2 id={headingId} className="text-[13.5px] font-semibold text-foreground">
                  Obowiązuje teraz
                </h2>
                {folders.length > 0 && (
                  <span className="text-[12px] text-muted-foreground">
                    liczą się pliki poza folderami — foldery to archiwum
                  </span>
                )}
              </div>
              <DocumentsNowCards
                contractId={contractId}
                current={view.current}
                contractNumber={currentNumber}
                readOnly={readOnly}
                onError={setError}
              />
            </section>
          )}

          {(view.items.length > 0 || !readOnly) && (
            <div className="flex flex-wrap items-center gap-2">
              {view.items.length > 0 && (
                <div className="w-full sm:w-80">
                  <label htmlFor={searchId} className="sr-only">
                    Szukaj w dokumentach
                  </label>
                  <Input
                    id={searchId}
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Szukaj w dokumentach"
                    leadingIcon={<Search className="size-4" />}
                    className="h-8 text-[13px]"
                  />
                </div>
              )}
              {!readOnly && (
                <div className="ml-auto flex items-center gap-1.5">
                  <input
                    ref={redlineInput}
                    type="file"
                    accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    className="sr-only"
                    tabIndex={-1}
                    aria-hidden="true"
                    onChange={(e) => {
                      openRedlineFromDisk(e.target.files?.[0]);
                      e.target.value = "";
                    }}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => redlineInput.current?.click()}
                    title="Umowa od klienta albo nasza umowa jako DOCX ze śledzeniem zmian"
                  >
                    <FileDiff className="size-4" aria-hidden="true" />
                    Popraw plik z dysku
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => openNewFolder([])}>
                    <FolderPlus className="size-4" aria-hidden="true" />
                    Nowy folder
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => {
                      setUploadError("");
                      setUploadOpen(true);
                    }}
                  >
                    <Plus className="size-4" aria-hidden="true" />
                    Dodaj plik
                  </Button>
                </div>
              )}
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" /> {error}
            </div>
          )}

          {foldersQuery.isError && (
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać folderów — pliki z folderów widać w grupach po rodzaju."
              onRetry={() => foldersQuery.refetch()}
            />
          )}
          {orderFilesQuery.isError && orderFilesStatus !== 403 && (
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać plików z zakładki Zamówienia — grupa zamówień może być niepełna."
              onRetry={() => orderFilesQuery.refetch()}
            />
          )}

          {selectionMode && (
            <DocumentSelectionBar
              count={selected.size}
              folders={folders}
              pending={mutations.moveDocuments.isPending}
              onMove={(folderId) => moveFiles([...selected], folderId)}
              onNewFolder={() => openNewFolder([...selected])}
              onCancel={() => setSelected(new Set())}
            />
          )}

          {docsQuery.isSuccess && !hasAnything ? (
            <div className="rounded-xl border border-border bg-card px-5 py-6 text-[13px] text-muted-foreground shadow-xs">
              Brak załączonych dokumentów.
              {!readOnly && " Dodaj podpisaną umowę przyciskiem „Dodaj plik”."}
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-card shadow-xs">
              {suggestion && (
                <div className="pt-3">
                  <FolderSuggestionBanner
                    suggestion={suggestion}
                    currentNumber={currentNumber}
                    readOnly={readOnly}
                    pending={mutations.createFolder.isPending || mutations.moveDocuments.isPending}
                    onApply={applySuggestion}
                    onSelect={() => {
                      const ids = new Set(suggestion.document_ids);
                      setSelected(ids);
                      revealDocs(ids);
                    }}
                    onDismiss={dismissSuggestion}
                  />
                </div>
              )}
              {view.batch && (
                <p className="flex items-start gap-2 border-b border-border/60 px-4 py-2 text-[12px] leading-4 text-muted-foreground">
                  <CloudDownload className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                  <span>
                    {batchSentence(view.batch)}
                    {view.batch.count < view.batch.total
                      ? " — w kolumnie „Dodano” są tylko pozostałe."
                      : "."}
                  </span>
                </p>
              )}
              <div className="relative overflow-x-auto rounded-xl">
                <table aria-label="Dokumenty kontraktu" className="w-full min-w-[50rem] table-fixed">
                  <colgroup>
                    <col />
                    <col className="w-[132px]" />
                    {showAdded && <col className="w-[168px]" />}
                    {showExpiry && <col className="w-[112px]" />}
                    <col className="w-[88px]" />
                    <col className={readOnly ? "w-[56px]" : "w-[88px]"} />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-border text-left">
                      <th scope="col" className={cn(CALM_HEAD, "sticky left-0 z-10 bg-card py-2 pl-4 pr-4")}>
                        Nazwa
                      </th>
                      <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4")}>
                        Data dokumentu
                      </th>
                      {showAdded && (
                        <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4")}>
                          Dodano
                        </th>
                      )}
                      {showExpiry && (
                        <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4")}>
                          Ważny do
                        </th>
                      )}
                      <th scope="col" className={cn(CALM_HEAD, "py-2 pr-4 text-right")}>
                        Rozmiar
                      </th>
                      <th scope="col" className="py-2 pr-3">
                        <span className="sr-only">Akcje</span>
                      </th>
                    </tr>
                  </thead>
                  {view.sections.map((section) => {
                    const visible = searching
                      ? section.items.filter((i) => matchesQuery(i, needle))
                      : section.items;
                    if (searching && visible.length === 0) return null;
                    const open = searching || isOpen(section);
                    const long = !searching && visible.length > LONG_GROUP && !showAll.has(section.key);
                    const shown = long ? visible.slice(0, LONG_GROUP_VISIBLE) : visible;
                    const isFolder = section.folder != null;
                    return (
                      <tbody key={section.key}>
                        <DocumentGroupHeader
                          label={sectionLabel(section)}
                          isFolder={isFolder}
                          colSpan={colCount}
                          open={open}
                          total={section.items.length}
                          matching={searching ? visible.length : null}
                          hint={
                            section.namedCount > 0
                              ? `${section.namedCount} z ${section.items.length} rozpoznano po nazwie pliku — w bazie mają typ „Inne”.`
                              : undefined
                          }
                          note={sectionNote(section)}
                          canRename={!readOnly && (isFolder || section.group === "zamowienia")}
                          canDelete={!readOnly && isFolder}
                          onToggle={() => setToggled((prev) => toggledSet(prev, section.key))}
                          onRename={(name) => renameSection(section, name)}
                          onDelete={() => void deleteFolder(section)}
                        />
                        {open && section.items.length === 0 && (
                          <tr className={CALM_ROW}>
                            <td colSpan={colCount} className="py-2.5 pl-11 pr-4 text-[12.5px] text-muted-foreground">
                              {readOnly
                                ? "Pusty folder."
                                : "Pusty folder — zaznacz pliki na liście albo wybierz „Przenieś do folderu” w menu „⋯” przy pliku."}
                            </td>
                          </tr>
                        )}
                        {open &&
                          shown.map((item) => {
                            const id = docIdOf(item);
                            return (
                              <DocumentItemRow
                                key={item.key}
                                item={item}
                                contractId={contractId}
                                readOnly={readOnly}
                                showAdded={showAdded}
                                folded={isFolded(item)}
                                showExpiry={showExpiry}
                                selectionMode={selectionMode}
                                selected={id != null && selected.has(id)}
                                duplicateOf={view.duplicates.get(item.key)}
                                folders={folders}
                                onToggle={toggleSelected}
                                onMove={moveFiles}
                                onNewFolder={openNewFolder}
                                onDelete={(row) => void deleteFile(row)}
                                onRedline={openRedline}
                                onError={setError}
                              />
                            );
                          })}
                        {open && long && (
                          <tr className={cn(CALM_ROW, "h-10")}>
                            <td colSpan={colCount} className="py-1.5 pl-10 pr-4">
                              <button
                                type="button"
                                onClick={() => setShowAll((prev) => new Set(prev).add(section.key))}
                                className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[12.5px] font-medium text-primary hover:bg-primary/5"
                              >
                                <ChevronDown className="size-3.5" aria-hidden="true" />
                                Pokaż starsze ({visible.length - LONG_GROUP_VISIBLE})
                              </button>
                            </td>
                          </tr>
                        )}
                      </tbody>
                    );
                  })}
                </table>
                {searching && !anyMatch && (
                  <p className="px-4 py-4 text-[13px] text-muted-foreground">
                    Żaden plik nie pasuje do „{needle}”.
                  </p>
                )}
              </div>
            </div>
          )}
        </>
      )}

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
        ordersFolderName={ordersLabel}
        pending={uploadMutation.isPending}
        error={uploadError}
        onSubmit={handleUpload}
      />
      <RedlineDialog
        open={redline !== null}
        onOpenChange={(open) => {
          if (!open) setRedline(null);
        }}
        target={redline?.target ?? null}
        title={redline?.title ?? ""}
        canSave={!readOnly}
        onSaved={(filename) => {
          refreshDocs();
          notify(`Zapisano „${filename}” w Dokumentach`);
        }}
      />
      {confirmDialog}
    </div>
  );
}
