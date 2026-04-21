"use client";

import * as React from "react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  Download,
  Eye,
  EyeOff,
  FileText,
  Printer,
  Send,
  Sparkles,
} from "lucide-react";
import { cvGeneratorApi, jobsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
}

export function CVGeneratorV2({
  open,
  onOpenChange,
  candidateId,
  candidateName,
}: Props) {
  const [template, setTemplate] = useState<"standard" | "blind">("standard");
  const [language, setLanguage] = useState<"pl" | "en">("pl");
  const [jobId, setJobId] = useState<string>("");
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: jobs = [] } = useQuery({
    queryKey: ["jobs-mini"],
    queryFn: () => jobsApi.list({ page_size: 50 }).then((r) => r.data?.items || []),
    enabled: open,
  });

  const generateMut = useMutation({
    mutationFn: (data: {
      template: "standard" | "blind";
      language: "pl" | "en";
      job_id?: number;
    }) => cvGeneratorApi.generateCV(candidateId, data),
    onSuccess: (res) => {
      setPreviewHtml(res.data.html);
      setError(null);
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail ?? "Błąd generowania CV");
    },
  });

  const handleGenerate = () =>
    generateMut.mutate({
      template,
      language,
      job_id: jobId ? parseInt(jobId) : undefined,
    });

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

  const handleCopyHtml = () => {
    if (!previewHtml) return;
    navigator.clipboard?.writeText(previewHtml);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" className="p-0 max-h-[92vh]">
        {/* Custom header with split-panel awareness */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[hsl(var(--border-subtle))]">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-[hsl(var(--accent))]" />
            <div>
              <h2 className="font-display text-lg font-bold text-[hsl(var(--text-title))]">
                Generator CV
              </h2>
              <p className="text-xs text-[hsl(var(--text-muted))]">
                {candidateName} · {template === "blind" ? "Blind (anonimowe)" : "Standard"} ·{" "}
                {language.toUpperCase()}
              </p>
            </div>
          </div>
          {previewHtml && (
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={handlePrint}>
                <Printer className="h-3.5 w-3.5" /> Drukuj
              </Button>
              <Button size="sm" variant="outline" onClick={handleDownload}>
                <Download className="h-3.5 w-3.5" /> HTML
              </Button>
              <Button size="sm" variant="primary" onClick={handleCopyHtml}>
                <Send className="h-3.5 w-3.5" /> Kopiuj HTML
              </Button>
            </div>
          )}
        </div>

        {/* Split panel */}
        <div className="grid grid-cols-[minmax(280px,320px)_1fr] min-h-[520px] max-h-[80vh]">
          {/* Left — config */}
          <aside className="border-r border-[hsl(var(--border-subtle))] p-5 space-y-5 overflow-y-auto bg-[hsl(var(--bg-canvas))]/40">
            <div>
              <Label htmlFor="cv-template" className="block mb-2">
                Typ szablonu
              </Label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => setTemplate("standard")}
                  className={cn(
                    "flex flex-col items-start gap-1 p-3 rounded-v2-m border text-sm transition-colors text-left",
                    template === "standard"
                      ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]"
                      : "border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/40"
                  )}
                >
                  <Eye className="h-4 w-4 text-[hsl(var(--accent))]" />
                  <span className="font-medium text-[hsl(var(--text-title))]">Standard</span>
                  <span className="text-[10px] text-[hsl(var(--text-muted))]">
                    z danymi osobowymi
                  </span>
                </button>
                <button
                  onClick={() => setTemplate("blind")}
                  className={cn(
                    "flex flex-col items-start gap-1 p-3 rounded-v2-m border text-sm transition-colors text-left",
                    template === "blind"
                      ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]"
                      : "border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/40"
                  )}
                >
                  <EyeOff className="h-4 w-4 text-[hsl(var(--accent))]" />
                  <span className="font-medium text-[hsl(var(--text-title))]">Blind</span>
                  <span className="text-[10px] text-[hsl(var(--text-muted))]">
                    anonimowe dla klienta
                  </span>
                </button>
              </div>
            </div>

            <div>
              <Label htmlFor="cv-lang" className="block mb-2">
                Język
              </Label>
              <div className="grid grid-cols-2 gap-2">
                {(["pl", "en"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setLanguage(l)}
                    className={cn(
                      "px-3 py-2 rounded-v2-s text-sm font-medium transition-colors",
                      language === l
                        ? "bg-[hsl(var(--accent))] text-white"
                        : "bg-[hsl(var(--bg-surface))] text-[hsl(var(--text-body))] border border-[hsl(var(--border-subtle))]"
                    )}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <Label htmlFor="cv-job" className="block mb-2">
                Dopasuj do oferty (opcjonalnie)
              </Label>
              <Select
                value={jobId || "_none"}
                onValueChange={(v) => setJobId(v === "_none" ? "" : v)}
              >
                <SelectTrigger id="cv-job">
                  <SelectValue placeholder="Bez dopasowania" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_none">Bez dopasowania</SelectItem>
                  {jobs.map((j: any) => (
                    <SelectItem key={j.id} value={String(j.id)}>
                      {j.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[10px] text-[hsl(var(--text-muted))] mt-1">
                Dodaje sekcję „Dlaczego ten kandydat" na podstawie kryteriów oferty.
              </p>
            </div>

            <Button
              variant="primary"
              size="md"
              className="w-full"
              onClick={handleGenerate}
              loading={generateMut.isPending}
            >
              <Sparkles className="h-4 w-4" />
              {previewHtml ? "Generuj ponownie" : "Generuj CV"}
            </Button>

            {error && (
              <div
                role="alert"
                className="text-xs text-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))] p-2 rounded-v2-s flex items-start gap-1.5"
              >
                <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {previewHtml && (
              <Badge variant="success" size="sm">
                CV wygenerowane
              </Badge>
            )}
          </aside>

          {/* Right — preview */}
          <div className="overflow-hidden bg-[hsl(var(--border-subtle))]/20">
            {previewHtml ? (
              <iframe
                srcDoc={previewHtml}
                sandbox="allow-same-origin"
                className="w-full h-full min-h-[520px] bg-white"
                title="Podgląd CV"
              />
            ) : (
              <div className="h-full min-h-[520px] flex flex-col items-center justify-center text-[hsl(var(--text-muted))] p-8">
                <FileText className="h-12 w-12 opacity-40 mb-3" />
                <p className="text-sm text-center max-w-xs">
                  Skonfiguruj opcje po lewej i kliknij <strong>Generuj CV</strong>, aby
                  zobaczyć podgląd.
                </p>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
