"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, Lock, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { contractsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { ContractDocument } from "@/lib/contract-document-folders";
import { permissionLabel } from "@/lib/permissions";

import { DOC_TYPE_LABEL } from "./doc-types";
import { UploadDocumentDialog, type UploadRequest } from "./UploadDocumentDialog";

interface Props {
  contractId: number;
}

/**
 * Zakładka „Dokumenty” dla osoby, która edytuje kontrakt, ale nie ma
 * „Stawki i kwoty: podgląd” (zgłoszenie 22.10.2026). Pliki umów niosą stawki,
 * więc listy nie widzi — może tylko dodać nowy plik (wypowiedzenie, aneks)
 * i widzi to, co dodała w tej wizycie.
 */
export function UploadOnlyDocuments({ contractId }: Props) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [added, setAdded] = useState<ContractDocument[]>([]);

  const upload = useMutation({
    mutationFn: (fd: FormData) =>
      contractsApi.uploadDocument(contractId, fd).then((r) => r.data as ContractDocument),
    onSuccess: (doc) => {
      setAdded((prev) => [doc, ...prev]);
      setOpen(false);
      setError("");
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
    },
    onError: (err: unknown) => {
      setError(apiErrorMessage(err, "Nie udało się wgrać pliku."));
    },
  });

  const handleUpload = (request: UploadRequest) => {
    const fd = new FormData();
    fd.append("file", request.file);
    fd.append("doc_type", request.docType);
    if (request.expiryDate) fd.append("expiry_date", request.expiryDate);
    upload.mutate(fd);
  };

  return (
    <div className="rounded-2xl bg-card shadow-xs dark:bg-muted">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <h3 className="text-sm font-semibold">Dokumenty</h3>
        <Button
          size="sm"
          onClick={() => {
            setError("");
            setOpen(true);
          }}
        >
          <Plus className="h-4 w-4" /> Dodaj plik
        </Button>
      </div>
      <p className="flex items-start gap-2 px-4 pb-4 text-sm text-muted-foreground">
        <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span>
          Możesz dodać plik — np. wypowiedzenie albo aneks. Listę plików tego kontraktu
          widzą osoby z uprawnieniem „{permissionLabel("amounts_view")}”, bo w umowach są
          stawki.
        </span>
      </p>
      {added.length > 0 && (
        <ul className="space-y-1 border-t border-border px-4 py-3" aria-label="Dodane teraz">
          {added.map((doc) => (
            <li key={doc.id} className="flex items-center gap-2 text-sm">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="truncate">{doc.filename}</span>
              <span className="text-muted-foreground">
                · {DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type} · dodano
              </span>
            </li>
          ))}
        </ul>
      )}
      <UploadDocumentDialog
        open={open}
        onOpenChange={setOpen}
        folders={[]}
        ordersFolderName="Zamówienia"
        pending={upload.isPending}
        error={error}
        onSubmit={handleUpload}
      />
    </div>
  );
}
