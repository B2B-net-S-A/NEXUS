"use client";

import { useState } from "react";
import {
  ClipboardList,
  Download,
  FileCheck,
  FileSignature,
  FileText,
  FileWarning,
  Loader2,
  Trash2,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { downloadContractDocument, openContractDocument } from "@/lib/contract-documents";
import { formatBytes, type FileRow } from "@/lib/contract-document-folders";
import { sharePointBadge } from "@/lib/contract-docs-sharepoint";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { downloadOrderDocument, openOrderDocument } from "@/lib/order-documents";
import { cn } from "@/lib/utils";

import { DOC_TYPE_LABEL } from "./doc-types";

const TYPE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  contract: FileSignature,
  annex: FileSignature,
  nda: FileCheck,
  nip: FileText,
  zus_certificate: FileCheck,
  oc_policy: FileWarning,
  order: ClipboardList,
  termination_notice: FileWarning,
  termination_agreement: FileSignature,
  other: FileText,
};

const SOON_MS = 30 * 24 * 60 * 60 * 1000;

interface Props {
  row: FileRow;
  contractId: number;
  indented: boolean;
  readOnly: boolean;
  selected: boolean;
  onToggle: (documentId: number) => void;
  onDelete: (documentId: number) => Promise<void>;
  onError: (message: string) => void;
}

/**
 * Wiersz pliku — ten sam w „Aktualnej umowie” i w folderze: Typ, oznaczenie
 * SharePointa, Rozmiar, Ważny do, Dodano, Pobierz i Usuń. Plik z zakładki
 * Zamówienia nie ma checkboxa ani „Usuń” — należy do zamówienia.
 */
export function DocumentFileRow({
  row,
  contractId,
  indented,
  readOnly,
  selected,
  onToggle,
  onDelete,
  onError,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const isDoc = row.kind === "doc";
  const name = isDoc ? row.doc.filename : row.order.title;
  const docType = isDoc ? row.doc.doc_type : "order";
  const Icon = TYPE_ICON[docType] ?? FileText;
  // Zamówienia nie przenosi się ręcznie — leży w „Zamówieniach” z definicji.
  const movable = isDoc && row.doc.doc_type !== "order";
  const expiry = isDoc ? row.doc.expiry_date : null;
  const expiringSoon = expiry ? new Date(expiry).getTime() - Date.now() <= SOON_MS : false;
  const added = isDoc ? row.doc.created_at : (row.order.uploaded_at ?? row.order.created_at);
  const addedBy = isDoc ? row.doc.uploaded_by_email : row.order.uploaded_by_email;
  const spBadge = isDoc ? sharePointBadge(row.doc) : null;

  const run = async (action: () => Promise<void>, failure: string) => {
    setBusy(true);
    try {
      await action();
    } catch {
      onError(failure);
    } finally {
      setBusy(false);
    }
  };

  const open = () =>
    run(
      () => (isDoc ? openContractDocument(contractId, row.doc) : openOrderDocument(row.order)),
      `Nie udało się otworzyć pliku „${name}”.`,
    );
  const download = () =>
    run(
      () =>
        isDoc ? downloadContractDocument(contractId, row.doc) : downloadOrderDocument(row.order),
      `Nie udało się pobrać pliku „${name}”.`,
    );

  const confirmDelete = async () => {
    if (!isDoc) return;
    setDeleting(true);
    try {
      await onDelete(row.doc.id);
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  };

  return (
    <tr className={cn("border-t border-border", selected && "bg-primary/5")}>
      {!readOnly && (
        <td className="w-10 pl-4 pr-0 py-2 align-middle">
          {movable && (
            <Checkbox
              checked={selected}
              onCheckedChange={() => onToggle(row.doc.id)}
              aria-label={`Zaznacz ${name}`}
            />
          )}
        </td>
      )}
      <td className={cn("sticky left-0 z-10 bg-card px-4 py-2", selected && "bg-primary/5")}>
        <div
          className={cn(
            "flex max-w-[14rem] items-center gap-2 sm:max-w-none",
            indented && "pl-6",
          )}
        >
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <button
            type="button"
            onClick={open}
            disabled={busy}
            className="min-w-0 break-words text-left text-primary hover:underline disabled:opacity-60"
            title="Otwórz"
          >
            {name}
          </button>
        </div>
      </td>
      <td className="px-4 py-2">
        {DOC_TYPE_LABEL[docType] ?? docType}
        {spBadge && (
          <Badge variant={spBadge.tone} size="sm" className="ml-2" title={spBadge.title}>
            {spBadge.label}
          </Badge>
        )}
        {!isDoc && (
          <Badge variant="neutral" size="sm" className="ml-2">
            z zakładki Zamówienia
          </Badge>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-2 text-muted-foreground tabular-nums">
        {formatBytes(isDoc ? row.doc.size_bytes : row.order.size_bytes)}
      </td>
      <td className="px-4 py-2">
        {expiry ? (
          <span className={expiringSoon ? "font-medium text-warning" : "text-muted-foreground"}>
            {formatDate(expiry)}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="px-4 py-2 text-xs text-muted-foreground">
        {formatDate(added)}
        {addedBy && <span className="block opacity-70">{addedBy}</span>}
      </td>
      <td className="px-4 py-2 text-right">
        <div className="inline-flex gap-1">
          <button
            type="button"
            onClick={download}
            disabled={busy}
            className="rounded p-1.5 text-muted-foreground hover:bg-muted disabled:opacity-50 pointer-coarse:p-2.5"
            title="Pobierz"
            aria-label={`Pobierz ${name}`}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          </button>
          {!readOnly &&
            isDoc &&
            (confirming ? (
              <span className="inline-flex items-center gap-1 text-xs">
                <span className="text-muted-foreground">Usunąć?</span>
                <button
                  type="button"
                  onClick={confirmDelete}
                  disabled={deleting}
                  aria-label={`Potwierdź usunięcie ${name}`}
                  className="rounded px-2 py-1 font-medium text-destructive hover:bg-destructive/10 disabled:opacity-60"
                >
                  Usuń
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  aria-label="Anuluj usuwanie"
                  className="rounded p-1 hover:bg-muted"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                className="rounded p-1.5 text-destructive hover:bg-destructive/10 pointer-coarse:p-2.5"
                title="Usuń"
                aria-label={`Usuń ${name}`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            ))}
        </div>
      </td>
    </tr>
  );
}
