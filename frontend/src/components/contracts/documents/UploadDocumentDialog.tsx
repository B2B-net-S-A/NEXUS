"use client";

import { useEffect, useRef, useState } from "react";
import { Lock, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatBytes, type DocumentFolder } from "@/lib/contract-document-folders";

import { DOC_TYPES } from "./doc-types";

export interface UploadRequest {
  file: File;
  docType: string;
  expiryDate: string;
  folderId: number | null;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: DocumentFolder[];
  ordersFolderName: string;
  pending: boolean;
  error: string;
  onSubmit: (request: UploadRequest) => void;
}

const FIELD =
  "h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

/**
 * „Dodaj plik”: plik, typ, data ważności i folder. Zamówienie zawsze trafia
 * do folderu „Zamówienia”, więc przy tym typie wybór folderu jest zablokowany.
 */
export function UploadDocumentDialog({
  open,
  onOpenChange,
  folders,
  ordersFolderName,
  pending,
  error,
  onSubmit,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("contract");
  const [expiryDate, setExpiryDate] = useState("");
  const [folderId, setFolderId] = useState("");

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setDocType("contract");
    setExpiryDate("");
    setFolderId("");
  }, [open]);

  const isOrder = docType === "order";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Dodaj plik</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!file) return;
            onSubmit({
              file,
              docType,
              expiryDate,
              folderId: isOrder || !folderId ? null : Number(folderId),
            });
          }}
        >
          <DialogBody className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 p-4">
              <Upload className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
              <div className="min-w-0 flex-1 text-sm">
                {file ? (
                  <>
                    <p className="truncate font-medium">{file.name}</p>
                    <p className="text-muted-foreground">{formatBytes(file.size)}</p>
                  </>
                ) : (
                  <p className="text-muted-foreground">
                    Maks. 20 MB. PDF / DOCX / JPG / PNG.
                  </p>
                )}
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
                {file ? "Zmień plik" : "Wybierz plik"}
              </Button>
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
                aria-label="Plik do dodania"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="upload-doc-type" className="mb-1.5 block text-sm font-medium">
                  Typ dokumentu
                </label>
                <select
                  id="upload-doc-type"
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className={FIELD}
                >
                  {DOC_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="upload-expiry" className="mb-1.5 block text-sm font-medium">
                  Ważny do (opcjonalnie)
                </label>
                <input
                  id="upload-expiry"
                  type="date"
                  value={expiryDate}
                  onChange={(e) => setExpiryDate(e.target.value)}
                  className={FIELD}
                />
              </div>
            </div>
            <div>
              <label
                htmlFor={isOrder ? undefined : "upload-folder"}
                className="mb-1.5 block text-sm font-medium"
              >
                Folder
              </label>
              {isOrder ? (
                <div
                  className="flex h-10 items-center gap-2 rounded-md border border-info/20 bg-info-muted px-3 text-sm font-medium text-info-muted-foreground"
                >
                  <Lock className="h-4 w-4" aria-hidden="true" />
                  {ordersFolderName} (automatycznie)
                </div>
              ) : (
                <select
                  id="upload-folder"
                  value={folderId}
                  onChange={(e) => setFolderId(e.target.value)}
                  className={FIELD}
                >
                  <option value="">Aktualna umowa (bez folderu)</option>
                  {folders.map((f) => (
                    <option key={f.id} value={String(f.id)}>
                      {f.name}
                    </option>
                  ))}
                </select>
              )}
              <p className="mt-1.5 text-xs text-muted-foreground">
                {isOrder
                  ? "Zamówienie zawsze ląduje w folderze „Zamówienia”."
                  : "Dla OC i NIP ustaw datę ważności — system powiadomi o wygaśnięciu."}
              </p>
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Anuluj
            </Button>
            <Button type="submit" loading={pending} disabled={!file}>
              Dodaj plik
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
