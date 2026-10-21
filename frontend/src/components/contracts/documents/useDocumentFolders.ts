"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { contractsApi } from "@/lib/api";
import { dlPortalApi, type OrderDocumentItem } from "@/lib/api/dlPortal";
import type { DocumentFoldersResponse } from "@/lib/contract-document-folders";

export function documentFoldersKey(contractId: number) {
  return ["contract-document-folders", contractId] as const;
}

/** Foldery, nazwa „Zamówień” i podpowiedzi „Poprzednia umowa” (0494). */
export function useDocumentFoldersQuery(contractId: number) {
  return useQuery<DocumentFoldersResponse>({
    queryKey: documentFoldersKey(contractId),
    queryFn: () => contractsApi.documentFolders(contractId).then((r) => r.data),
  });
}

/**
 * PDF-y z zakładki Zamówienia — ten sam klucz co dawna sekcja
 * `OrderDocumentsSection`, więc pamięć podręczna jest wspólna. 403 = ta rola
 * nie widzi zamówień klienta (PO niesie stawki) i wtedy folder po prostu ich
 * nie pokazuje; każdą inną awarię pokazujemy.
 */
export function useOrderFilesQuery(contractId: number) {
  return useQuery<OrderDocumentItem[]>({
    queryKey: ["order-documents", contractId, null],
    queryFn: () =>
      dlPortalApi.listContractOrderDocuments(contractId).then((r) => r.data.documents),
    retry: false,
  });
}

export function useDocumentFolderMutations(contractId: number) {
  const queryClient = useQueryClient();
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["contract-documents", contractId] });
    queryClient.invalidateQueries({ queryKey: documentFoldersKey(contractId) });
    queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
  };

  const createFolder = useMutation({
    mutationFn: (payload: { name: string; document_ids?: number[] }) =>
      contractsApi.createDocumentFolder(contractId, payload).then((r) => r.data),
    onSuccess: refresh,
  });
  const renameFolder = useMutation({
    mutationFn: ({ folderId, name }: { folderId: number; name: string }) =>
      contractsApi.renameDocumentFolder(contractId, folderId, name).then((r) => r.data),
    onSuccess: refresh,
  });
  const renameOrdersFolder = useMutation({
    mutationFn: (name: string) =>
      contractsApi.renameOrdersFolder(contractId, name).then((r) => r.data),
    onSuccess: refresh,
  });
  const deleteFolder = useMutation({
    mutationFn: (folderId: number) =>
      contractsApi.deleteDocumentFolder(contractId, folderId).then((r) => r.data),
    onSuccess: refresh,
  });
  const moveDocuments = useMutation({
    mutationFn: (payload: { document_ids: number[]; folder_id: number | null }) =>
      contractsApi.moveDocuments(contractId, payload).then((r) => r.data),
    onSuccess: refresh,
  });

  return { createFolder, renameFolder, renameOrdersFolder, deleteFolder, moveDocuments };
}
