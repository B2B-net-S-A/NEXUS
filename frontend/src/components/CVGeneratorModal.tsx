"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  FileText,
  X,
  Printer,
  Download,
  Send,
  Eye,
  Loader2,
  AlertCircle,
  User,
  EyeOff,
} from "lucide-react";
import { cvGeneratorApi, jobsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

type CVGeneratorModalProps = {
  candidateId: number;
  candidateName: string;
  onClose: () => void;
};

export function CVGeneratorModal({
  candidateId,
  candidateName,
  onClose,
}: CVGeneratorModalProps) {
  const [template, setTemplate] = useState<"standard" | "blind">("standard");
  const [language, setLanguage] = useState<"pl" | "en">("pl");
  const [jobId, setJobId] = useState<string>("");
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: jobs = [] } = useQuery({
    queryKey: ["jobs-mini"],
    queryFn: () => jobsApi.list({ page_size: 50 }).then((r) => r.data?.items || []),
  });

  const generateMutation = useMutation({
    mutationFn: (data: { template: "standard" | "blind"; language: "pl" | "en"; job_id?: number }) =>
      cvGeneratorApi.generateCV(candidateId, data),
    onSuccess: (res) => {
      setPreviewHtml(res.data.html);
      setError(null);
    },
    onError: (e: any) => {
      setError(e.response?.data?.detail || "Błąd generowania CV");
    },
  });

  const handleGenerate = () => {
    generateMutation.mutate({
      template,
      language,
      job_id: jobId ? parseInt(jobId) : undefined,
    });
  };

  const handlePrint = () => {
    if (!previewHtml) return;
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(previewHtml);
    win.document.close();
    win.focus();
    win.print();
  };

  const handleDownload = () => {
    if (!previewHtml) return;
    const blob = new Blob([previewHtml], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `CV_${candidateName.replace(/ /g, "_")}_${template}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSendToClient = () => {
    // Placeholder — copy HTML to clipboard
    if (!previewHtml) return;
    navigator.clipboard?.writeText(previewHtml);
    alert("HTML CV skopiowany do schowka. Wyślij kandydatowi lub klientowi.");
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-5xl my-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-blue-600" />
            <div>
              <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Generator CV</h2>
              <p className="text-xs text-gray-500">{candidateName}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {previewHtml && (
              <>
                <button
                  onClick={handlePrint}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
                >
                  <Printer className="w-3.5 h-3.5" />
                  Drukuj
                </button>
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  Pobierz HTML
                </button>
                <button
                  onClick={handleSendToClient}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <Send className="w-3.5 h-3.5" />
                  Wyślij do klienta
                </button>
              </>
            )}
            <button onClick={onClose} className="ml-1 text-gray-400 hover:text-gray-600">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="flex divide-x divide-gray-200">
          {/* ── Left panel: options ── */}
          <div className="w-72 flex-shrink-0 p-6 space-y-5">
            {/* Template */}
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wide block mb-2">
                Typ szablonu
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setTemplate("standard")}
                  className={cn(
                    "flex flex-col items-center gap-1.5 p-3 border rounded-xl text-xs font-medium transition-colors",
                    template === "standard"
                      ? "bg-blue-50 border-blue-300 text-blue-700"
                      : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                  )}
                >
                  <User className="w-5 h-5" />
                  Standard
                  <span className="text-xs opacity-60 text-center">Z danymi osobowymi</span>
                </button>
                <button
                  type="button"
                  onClick={() => setTemplate("blind")}
                  className={cn(
                    "flex flex-col items-center gap-1.5 p-3 border rounded-xl text-xs font-medium transition-colors",
                    template === "blind"
                      ? "bg-purple-50 border-purple-300 text-purple-700"
                      : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                  )}
                >
                  <EyeOff className="w-5 h-5" />
                  Blind
                  <span className="text-xs opacity-60 text-center">Anonimowy profil</span>
                </button>
              </div>
              {template === "blind" && (
                <p className="text-xs text-purple-600 mt-2 bg-purple-50 border border-purple-100 rounded-lg px-2 py-1.5">
                  Ukrywa: imię, email, telefon, nazwy firm
                </p>
              )}
            </div>

            {/* Language */}
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wide block mb-2">
                Język
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setLanguage("pl")}
                  className={cn(
                    "p-2.5 border rounded-xl text-sm font-bold transition-colors",
                    language === "pl"
                      ? "bg-blue-50 border-blue-300 text-blue-700"
                      : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                  )}
                >
                  🇵🇱 PL
                </button>
                <button
                  type="button"
                  onClick={() => setLanguage("en")}
                  className={cn(
                    "p-2.5 border rounded-xl text-sm font-bold transition-colors",
                    language === "en"
                      ? "bg-blue-50 border-blue-300 text-blue-700"
                      : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                  )}
                >
                  🇬🇧 EN
                </button>
              </div>
            </div>

            {/* Job selector */}
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wide block mb-2">
                Dopasuj do oferty (opcjonalnie)
              </label>
              <select
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
                className="w-full border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Bez dopasowania —</option>
                {jobs.map((j: any) => (
                  <option key={j.id} value={j.id}>
                    {j.title}
                  </option>
                ))}
              </select>
              {jobId && (
                <p className="text-xs text-blue-600 mt-1 bg-blue-50 border border-blue-100 rounded px-2 py-1">
                  ✓ CV zostanie dopasowane do wymagań oferty
                </p>
              )}
            </div>

            {/* Generate button */}
            <button
              onClick={handleGenerate}
              disabled={generateMutation.isPending}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl disabled:opacity-50 transition-colors"
            >
              {generateMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Generuję...
                </>
              ) : (
                <>
                  <Eye className="w-4 h-4" />
                  {previewHtml ? "Regeneruj" : "Generuj CV"}
                </>
              )}
            </button>

            {/* Summary */}
            <div className="text-xs text-gray-400 space-y-1 pt-2">
              <p className="font-semibold text-gray-500">Podsumowanie:</p>
              <p>• Szablon: <span className="font-medium text-gray-700">{template === "standard" ? "Standard" : "Blind (anonimowy)"}</span></p>
              <p>• Język: <span className="font-medium text-gray-700">{language === "pl" ? "Polski" : "English"}</span></p>
              {jobId && (
                <p>• Dopasowany do oferty: <span className="font-medium text-blue-600">Tak</span></p>
              )}
            </div>
          </div>

          {/* ── Right panel: preview ── */}
          <div className="flex-1 overflow-hidden">
            {error && (
              <div className="m-4 flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                {error}
              </div>
            )}

            {!previewHtml && !generateMutation.isPending && (
              <div className="flex flex-col items-center justify-center h-96 text-gray-400">
                <FileText className="w-16 h-16 mb-4 opacity-20" />
                <p className="text-lg font-medium">Podgląd CV</p>
                <p className="text-sm mt-1">Skonfiguruj opcje i kliknij „Generuj CV"</p>
              </div>
            )}

            {generateMutation.isPending && (
              <div className="flex flex-col items-center justify-center h-96 text-gray-400">
                <Loader2 className="w-10 h-10 animate-spin text-blue-400 mb-3" />
                <p className="text-sm">Generuję profesjonalne CV...</p>
              </div>
            )}

            {previewHtml && !generateMutation.isPending && (
              <div className="h-[600px] overflow-y-auto border-l border-gray-100">
                <iframe
                  srcDoc={previewHtml}
                  className="w-full h-full"
                  title="CV Preview"
                  sandbox="allow-same-origin"
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
