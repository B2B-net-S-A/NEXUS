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

interface ContractDocument {
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
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Typ dokumentu
              </label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Data ważności (opcjonalnie)
              </label>
              <input
                type="date"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
              />
            </div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
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
            <div className="text-sm text-red-700 bg-red-50 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-3 py-2 flex items-center gap-2">
              <AlertCircle className="w-4 h-4" /> {error}
            </div>
          )}
          <div className="text-xs text-gray-500 dark:text-gray-400">
            Maks. 20 MB. PDF / DOCX / JPG / PNG. Dla OC i NIP ustaw datę ważności —
            system powiadomi o wygaśnięciu.
          </div>
        </div>
      </RequireRole>

      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            <Loader2 className="w-5 h-5 inline-block animate-spin mr-2" />
            Ładowanie dokumentów…
          </div>
        ) : docs.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            Brak załączonych dokumentów.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-700/40 text-xs uppercase text-gray-500 dark:text-gray-400">
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
                    className="border-t border-gray-100 dark:border-gray-700"
                  >
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <Icon className="w-4 h-4 text-gray-400" />
                        <a
                          href={contractsApi.documentDownloadUrl(contractId, d.id)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-600 hover:underline dark:text-blue-400"
                        >
                          {d.filename}
                        </a>
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      {DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type}
                    </td>
                    <td className="px-4 py-2 text-gray-500 dark:text-gray-400">
                      {formatBytes(d.size_bytes)}
                    </td>
                    <td className="px-4 py-2">
                      {d.expiry_date ? (
                        <span
                          className={
                            isExpiringSoon
                              ? "text-orange-600 font-medium"
                              : "text-gray-500 dark:text-gray-400"
                          }
                        >
                          {formatDate(d.expiry_date)}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 dark:text-gray-400">
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
                          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                          title="Pobierz"
                        >
                          <Download className="w-4 h-4" />
                        </a>
                        <RequireRole roles={["admin", "delivery_lead", "tac"]}>
                          <button
                            onClick={() => handleDelete(d)}
                            disabled={deleteMutation.isPending}
                            className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500 disabled:opacity-50"
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
