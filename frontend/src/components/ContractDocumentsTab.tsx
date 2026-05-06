"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { contractsApi } from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatDate } from "@/lib/utils";
import {
  Upload,
  Trash2,
  Download,
  FileText,
  FileCheck,
  FileSignature,
  FileWarning,
  Loader2,
  AlertCircle,
} from "lucide-react";

// Matches backend ContractDocumentType enum
const DOC_TYPES: { value: string; label: string }[] = [
  { value: "contract", label: "Umowa" },
  { value: "annex", label: "Aneks" },
  { value: "nda", label: "NDA" },
  { value: "nip", label: "NIP" },
  { value: "zus_certificate", label: "Zaświadczenie ZUS" },
  { value: "oc_policy", label: "Polisa OC" },
  { value: "other", label: "Inne" },
];

const DOC_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  DOC_TYPES.map((d) => [d.value, d.label]),
);

const TYPE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  contract: FileSignature,
  annex: FileSignature,
  nda: FileCheck,
  nip: FileText,
  zus_certificate: FileCheck,
  oc_policy: FileWarning,
  other: FileText,
};

export interface ContractDocument {
  id: number;
  contract_id: number;
  filename: string;
  doc_type: string;
  content_type: string | null;
  size_bytes: number | null;
  expiry_date: string | null;
  uploaded_by: number | null;
  uploaded_by_email: string | null;
  created_at: string;
}

function formatBytes(n: number | null | undefined): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  contractId: number;
}

const COMPLIANCE_TYPES = new Set(["nip", "zus_certificate", "oc_policy"]);

/**
 * Inspect the list of documents and return the soonest compliance-related
 * expiry that's already past or less than 30 days away. Used by consumers
 * that want to render a "Compliance risk" badge.
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
  for (const d of docs) {
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

export function ContractDocumentsTab({ contractId }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [docType, setDocType] = useState<string>("contract");
  const [expiryDate, setExpiryDate] = useState<string>("");
  const [error, setError] = useState<string>("");

  const { data, isLoading } = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", contractId],
    queryFn: () => contractsApi.documents(contractId).then((r) => r.data),
  });

  const uploadMutation = useMutation({
    mutationFn: (fd: FormData) => contractsApi.uploadDocument(contractId, fd),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-documents", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
      if (fileInputRef.current) fileInputRef.current.value = "";
      setExpiryDate("");
      setError("");
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : "Błąd podczas uploadu";
      setError(message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: number) =>
      contractsApi.deleteDocument(contractId, documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-documents", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("doc_type", docType);
    if (expiryDate) fd.append("expiry_date", expiryDate);
    uploadMutation.mutate(fd);
  };

  const handleDelete = (doc: ContractDocument) => {
    if (window.confirm(`Usunąć plik "${doc.filename}"?`)) {
      deleteMutation.mutate(doc.id);
    }
  };

  const docs = data ?? [];

  return (
    <div className="space-y-4">
      <RequireRole roles={["admin", "delivery_lead", "tac"]}>
        <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                Typ dokumentu
              </label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                Data ważności (opcjonalnie)
              </label>
              <input
                type="date"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
              />
            </div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
              className="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {uploadMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Upload className="w-4 h-4" />
              )}
              Wgraj plik
            </button>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
              onChange={handleFileChange}
            />
          </div>
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-3 py-2 flex items-center gap-2">
              <AlertCircle className="w-4 h-4" /> {error}
            </div>
          )}
          <div className="text-xs text-muted-foreground dark:text-muted-foreground">
            Maks. 20 MB. PDF / DOCX / JPG / PNG. Dla OC i NIP ustaw datę ważności —
            system powiadomi o wygaśnięciu.
          </div>
        </div>
      </RequireRole>

      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-muted-foreground dark:text-muted-foreground">
            <Loader2 className="w-5 h-5 inline-block animate-spin mr-2" />
            Ładowanie dokumentów…
          </div>
        ) : docs.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground dark:text-muted-foreground">
            Brak załączonych dokumentów.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground dark:text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2">Plik</th>
                <th className="text-left px-4 py-2">Typ</th>
                <th className="text-left px-4 py-2">Rozmiar</th>
                <th className="text-left px-4 py-2">Ważny do</th>
                <th className="text-left px-4 py-2">Dodano</th>
                <th className="text-right px-4 py-2">Akcje</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => {
                const Icon = TYPE_ICON[d.doc_type] ?? FileText;
                const isExpiringSoon =
                  d.expiry_date &&
                  new Date(d.expiry_date).getTime() - Date.now() <=
                    30 * 24 * 60 * 60 * 1000;
                return (
                  <tr
                    key={d.id}
                    className="border-t border-border dark:border-border"
                  >
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <Icon className="w-4 h-4 text-muted-foreground" />
                        <a
                          href={contractsApi.documentDownloadUrl(contractId, d.id)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary hover:underline dark:text-primary"
                        >
                          {d.filename}
                        </a>
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      {DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground dark:text-muted-foreground">
                      {formatBytes(d.size_bytes)}
                    </td>
                    <td className="px-4 py-2">
                      {d.expiry_date ? (
                        <span
                          className={
                            isExpiringSoon
                              ? "text-orange-600 font-medium"
                              : "text-muted-foreground dark:text-muted-foreground"
                          }
                        >
                          {formatDate(d.expiry_date)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground dark:text-muted-foreground">
                      {formatDate(d.created_at)}
                      {d.uploaded_by_email && (
                        <span className="block opacity-70">
                          {d.uploaded_by_email}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="inline-flex gap-1">
                        <a
                          href={contractsApi.documentDownloadUrl(contractId, d.id)}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1.5 rounded hover:bg-muted dark:hover:bg-muted text-muted-foreground dark:text-muted-foreground"
                          title="Pobierz"
                        >
                          <Download className="w-4 h-4" />
                        </a>
                        <RequireRole roles={["admin", "delivery_lead", "tac"]}>
                          <button
                            onClick={() => handleDelete(d)}
                            disabled={deleteMutation.isPending}
                            className="p-1.5 rounded hover:bg-destructive/10 dark:hover:bg-red-900/20 text-destructive disabled:opacity-50"
                            title="Usuń"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </RequireRole>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
