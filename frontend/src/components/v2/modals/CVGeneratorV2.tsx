"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Download,
  Loader2,
  Sparkles,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  type RecruitmentOption,
  downloadBlob,
  extractErrorDetail,
  parseDispositionFilename,
  parseWarningsHeader,
  stageLabel,
} from "@/lib/cv-generator";
import { Dialog, DialogContent } from "@/components/ui/dialog";
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
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/Toast";

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
  const toast = useToast();
  const [stageId, setStageId] = useState<string>("");
  const [language, setLanguage] = useState<"pl" | "en">("pl");
  const [blindCv, setBlindCv] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const recruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments-modal", candidateId],
    queryFn: async () => {
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidateId}/recruitments`,
      );
      return res.data;
    },
    enabled: open,
  });

  // Auto-pick first ready recruitment on open
  useEffect(() => {
    if (!open || !recruitmentsQuery.data || stageId) return;
    const ready = recruitmentsQuery.data.find((r) => r.ready);
    if (ready) setStageId(String(ready.stage_id));
  }, [open, recruitmentsQuery.data, stageId]);

  const selectedRecruitment = useMemo(() => {
    if (!stageId) return null;
    return (
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ?? null
    );
  }, [recruitmentsQuery.data, stageId]);

  const canSubmit = !!selectedRecruitment && selectedRecruitment.ready;

  const generateMut = useMutation({
    mutationFn: async () => {
      if (!selectedRecruitment) throw new Error("Wybierz rekrutację");
      const res = await api.post(
        "/api/cv-generator/generate",
        {
          candidate_id: candidateId,
          stage_id: selectedRecruitment.stage_id,
          language,
          blind_cv: blindCv,
        },
        {
          responseType: "blob",
          timeout: 180_000,
        },
      );
      return {
        blob: res.data as Blob,
        filename: parseDispositionFilename(
          res.headers["content-disposition"] || "",
          `CV_${candidateName.replace(/\s+/g, "_")}.docx`,
        ),
        warnings: parseWarningsHeader(res.headers["x-generator-warnings"]),
      };
    },
    onSuccess: ({ blob, filename, warnings: w }) => {
      setWarnings(w);
      setError(null);
      downloadBlob(blob, filename);
      toast.showSuccess("CV wygenerowane i pobrane.");
    },
    onError: async (err: unknown) => {
      const detail = await extractErrorDetail(err);
      setError(detail || "Generowanie nie powiodło się.");
      toast.showError(detail || "Generowanie nie powiodło się.");
    },
  });

  const recruitments = recruitmentsQuery.data ?? [];
  const hasAny = recruitments.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" className="p-0 max-h-[92vh]">
        <div className="flex shrink-0 items-start justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-primary/10 p-2 text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-foreground">Generator CV</h2>
              <p className="text-xs text-muted-foreground">
                {candidateName} · DOCX szablon B2B Network
                {selectedRecruitment ? (
                  <>
                    {" · "}
                    {selectedRecruitment.job_title}
                  </>
                ) : null}
              </p>
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 space-y-5 p-6 overflow-y-auto">
          <div>
            <Label className="mb-2 block">Proces rekrutacyjny</Label>
            {recruitmentsQuery.isLoading ? (
              <div className="text-xs text-muted-foreground">
                Ładowanie rekrutacji…
              </div>
            ) : !hasAny ? (
              <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
                Kandydat nie uczestniczy w żadnej rekrutacji. Jeśli chcesz
                wygenerować CV bez kontekstu klienta — otwórz{" "}
                <a href="/cv-generator" className="text-primary underline">
                  /cv-generator → Old mode
                </a>{" "}
                i wgraj plik CV ręcznie.
              </div>
            ) : (
              <>
                <Select value={stageId} onValueChange={setStageId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Wybierz rekrutację…" />
                  </SelectTrigger>
                  <SelectContent>
                    {recruitments.map((r) => (
                      <SelectItem key={r.stage_id} value={String(r.stage_id)}>
                        <span className="flex items-center gap-2">
                          <span className="truncate">{r.job_title}</span>
                          <span className="text-xs text-muted-foreground">
                            · {stageLabel(r.stage)}
                          </span>
                          {r.ready ? (
                            <CheckCircle2 className="ml-1 h-3.5 w-3.5 text-emerald-600" />
                          ) : (
                            <AlertTriangle className="ml-1 h-3.5 w-3.5 text-amber-500" />
                          )}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedRecruitment && (
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <ReadyBadge
                      label="CV w systemie"
                      ok={selectedRecruitment.has_cv}
                    />
                    <ReadyBadge
                      label="Profil Championa"
                      ok={selectedRecruitment.has_champion}
                    />
                    <ReadyBadge
                      label="Notatki z rozmów"
                      ok={selectedRecruitment.has_notes}
                    />
                  </div>
                )}
                {selectedRecruitment && !selectedRecruitment.ready && (
                  <div
                    role="alert"
                    className="mt-3 flex items-start gap-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-200"
                  >
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <div className="space-y-1">
                      {!selectedRecruitment.has_cv && (
                        <div>
                          Kandydat nie ma wgranego CV (PDF/DOCX) w systemie —
                          dodaj plik w zakładce Dokumenty na profilu.
                        </div>
                      )}
                      {!selectedRecruitment.has_champion && (
                        <div>
                          Brakuje Profilu Championa na ofercie — uzupełnij go na
                          karcie oferty.
                        </div>
                      )}
                      {!selectedRecruitment.has_notes && (
                        <div>
                          Brak notatek z rozmów — wymagana co najmniej jedna:
                          screening, transkrypt CloudTalk albo notatka procesu.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="mb-2 block">Język</Label>
              <div className="grid grid-cols-2 gap-2">
                {(["pl", "en"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setLanguage(l)}
                    className={cn(
                      "px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      language === l
                        ? "bg-primary text-white"
                        : "bg-card text-foreground border border-border",
                    )}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <Label className="mb-2 block">Blind CV</Label>
              <div className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
                <span className="text-xs text-muted-foreground">
                  Anonimizuj imię, nazwisko i nazwy firm
                </span>
                <Switch checked={blindCv} onCheckedChange={setBlindCv} />
              </div>
            </div>
          </div>

          {warnings.length > 0 && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-200"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <div>
                <div className="font-medium">Uwagi z analizy Claude</div>
                <ul className="ml-4 mt-1 list-disc">
                  {warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md bg-destructive/10 p-2 text-xs text-destructive"
            >
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-xs text-muted-foreground">
              {generateMut.isPending
                ? "Claude analizuje CV i renderuje DOCX…"
                : "Generacja zajmuje 60–90 sekund. Output: DOCX szablon B2B Network."}
            </p>
            <Button
              size="md"
              disabled={!canSubmit || generateMut.isPending}
              onClick={() => {
                setError(null);
                setWarnings([]);
                generateMut.mutate();
              }}
            >
              {generateMut.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Generuję…
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" />
                  Generuj CV (DOCX)
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ReadyBadge({ label, ok }: { label: string; ok: boolean }) {
  return (
    <Badge
      variant={ok ? "success" : "warning"}
      className={cn("flex items-center gap-1")}
    >
      {ok ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : (
        <AlertTriangle className="h-3 w-3" />
      )}
      {label}
    </Badge>
  );
}

