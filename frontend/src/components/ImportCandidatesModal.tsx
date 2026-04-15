"use client";

import { useState, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Upload,
  X,
  CheckCircle2,
  AlertCircle,
  SkipForward,
  FileSpreadsheet,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ImportResult {
  imported: number;
  skipped: number;
  errors: number;
  details: Array<{
    row: number;
    status: "imported" | "skipped" | "error";
    name?: string;
    email?: string;
    reason?: string;
  }>;
}

interface ImportCandidatesModalProps {
  onClose: () => void;
}

export function ImportCandidatesModal({ onClose }: ImportCandidatesModalProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { mutate: doImport, isPending } = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.post("/api/import/candidates", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return res.data as ImportResult;
    },
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail || "Błąd podczas importu. Sprawdź format pliku.");
    },
  });

  const handleFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith(".csv")) {
      setError("Dozwolone są tylko pliki CSV");
      return;
    }
    setFile(f);
    setError(null);
    setResult(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  const handleSubmit = () => {
    if (!file) return;
    doImport(file);
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <FileSpreadsheet className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Import kandydatów z CSV</h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">UTF-8, polskie znaki obsługiwane</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {!result ? (
            <>
              {/* Column reference */}
              <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-4 text-xs">
                <p className="font-semibold text-gray-700 dark:text-gray-300 mb-2">Wymagane kolumny CSV:</p>
                <div className="grid grid-cols-2 gap-1 font-mono text-gray-600 dark:text-gray-400">
                  {["name", "lastname", "email", "phone", "location", "source", "skills", "salary_expectation"].map((col) => (
                    <span key={col} className="bg-white dark:bg-gray-700 px-2 py-1 rounded border border-gray-200 dark:border-gray-600">
                      {col}
                    </span>
                  ))}
                </div>
                <p className="text-gray-500 mt-2">
                  Kolumna <span className="font-mono">skills</span>: wartości rozdzielone przecinkami (np. <em>Python, React, AWS</em>)
                </p>
              </div>

              {/* Drop zone */}
              <div
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                className={cn(
                  "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                  dragOver
                    ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                    : file
                    ? "border-green-400 bg-green-50 dark:bg-green-900/10"
                    : "border-gray-200 dark:border-gray-600 hover:border-blue-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                )}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFile(f);
                  }}
                />
                {file ? (
                  <div className="space-y-1">
                    <CheckCircle2 className="w-8 h-8 text-green-500 mx-auto" />
                    <p className="text-sm font-semibold text-green-700">{file.name}</p>
                    <p className="text-xs text-gray-500">
                      {(file.size / 1024).toFixed(1)} KB — kliknij aby zmienić
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Upload className="w-8 h-8 text-gray-400 mx-auto" />
                    <p className="text-sm font-medium text-gray-600 dark:text-gray-300">
                      Przeciągnij plik CSV lub kliknij
                    </p>
                    <p className="text-xs text-gray-400">Maksymalnie 10 MB</p>
                  </div>
                )}
              </div>

              {error && (
                <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={onClose}
                  className="flex-1 px-4 py-2 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Anuluj
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={!file || isPending}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Importowanie...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4" />
                      Importuj
                    </>
                  )}
                </button>
              </div>
            </>
          ) : (
            /* Results view */
            <div className="space-y-4">
              {/* Summary cards */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-green-50 dark:bg-green-900/20 rounded-xl p-4 text-center">
                  <p className="text-2xl font-bold text-green-600">{result.imported}</p>
                  <p className="text-xs text-green-700 dark:text-green-400 font-medium mt-1">Zaimportowanych</p>
                </div>
                <div className="bg-amber-50 dark:bg-amber-900/20 rounded-xl p-4 text-center">
                  <p className="text-2xl font-bold text-amber-600">{result.skipped}</p>
                  <p className="text-xs text-amber-700 dark:text-amber-400 font-medium mt-1">Pominiętych</p>
                </div>
                <div className="bg-red-50 dark:bg-red-900/20 rounded-xl p-4 text-center">
                  <p className="text-2xl font-bold text-red-600">{result.errors}</p>
                  <p className="text-xs text-red-700 dark:text-red-400 font-medium mt-1">Błędów</p>
                </div>
              </div>

              {/* Details list */}
              {result.details.length > 0 && (
                <div className="max-h-52 overflow-y-auto space-y-1 bg-gray-50 dark:bg-gray-800 rounded-xl p-3">
                  {result.details.map((d, i) => (
                    <div
                      key={i}
                      className={cn(
                        "flex items-start gap-2 text-xs px-2 py-1.5 rounded-lg",
                        d.status === "imported" ? "text-green-700 bg-green-50 dark:bg-green-900/20" :
                        d.status === "skipped" ? "text-amber-700 bg-amber-50 dark:bg-amber-900/20" :
                        "text-red-700 bg-red-50 dark:bg-red-900/20"
                      )}
                    >
                      <span className="font-semibold flex-shrink-0">R{d.row}:</span>
                      <span className="truncate">
                        {d.status === "imported" ? `✓ ${d.name || d.email || ""}` :
                         d.status === "skipped" ? `⊘ ${d.email} — ${d.reason}` :
                         `✕ ${d.reason}`}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => { setResult(null); setFile(null); }}
                  className="flex-1 px-4 py-2 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Importuj kolejny plik
                </button>
                <button
                  onClick={onClose}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  Zamknij
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
