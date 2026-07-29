"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Sparkles,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  type CvContentMode,
  type RecruitmentOption,
  DEFAULT_CV_CONTENT_MODE,
  extractErrorDetail,
} from "@/lib/cv-generator";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/Toast";
import { ContentModeTiles } from "@/components/v2/cv-generator/ContentModeTiles";
import { RecruitmentCombobox } from "@/components/v2/cv-generator/RecruitmentCombobox";
import { LanguageTiles } from "@/components/v2/LanguageTiles";

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
  const [contentMode, setContentMode] = useState<CvContentMode>(
    DEFAULT_CV_CONTENT_MODE,
  );
  const [enqueued, setEnqueued] = useState(false);
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
      const res = await api.post<{
        id: number;
        status: string;
        candidate_name: string;
      }>(
        "/api/cv-generator/generate",
        {
          candidate_id: candidateId,
          stage_id: selectedRecruitment.stage_id,
          language,
          blind_cv: blindCv,
          content_mode: contentMode,
        },
        { timeout: 30_000 },
      );
      return res.data;
    },
    onSuccess: () => {
      setError(null);
      setEnqueued(true);
      toast.showSuccess(
        "Generacja ruszyła w tle — CV pojawi się w Generatorze CV, gdy będzie gotowe.",
      );
    },
    onError: async (err: unknown) => {
      const detail = await extractErrorDetail(err);
      setError(detail || "Nie udało się uruchomić generacji.");
      toast.showError(detail || "Nie udało się uruchomić generacji.");
    },
  });

  const recruitments = recruitmentsQuery.data ?? [];
  const hasAny = recruitments.length > 0;

  // Reset the „enqueued" success view when the dialog closes so re-opening lands
  // on the form again.
  function handleOpenChange(next: boolean) {
    if (!next) {
      setEnqueued(false);
      setError(null);
    }
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
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

        {enqueued ? (
          <div className="flex-1 min-h-0 space-y-4 p-6">
            <div className="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/50 dark:bg-emerald-950/30">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
              <div className="space-y-1 text-sm">
                <div className="font-medium text-foreground">
                  Generacja ruszyła w tle
                </div>
                <p className="text-muted-foreground">
                  CV dla <span className="font-medium">{candidateName}</span>{" "}
                  generuje się w tle (60–90 s) i pojawi się na liście
                  „Wygenerowane CV" w Generatorze CV. Możesz spokojnie zamknąć to
                  okno — wynik nie przepadnie.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2">
              <Button
                variant="outline"
                size="md"
                onClick={() => handleOpenChange(false)}
              >
                Zamknij
              </Button>
              <a href="/cv-generator">
                <Button size="md">Otwórz Generator CV</Button>
              </a>
            </div>
          </div>
        ) : (
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
                  <RecruitmentCombobox
                    recruitments={recruitments}
                    value={stageId}
                    onChange={setStageId}
                    loading={recruitmentsQuery.isLoading}
                  />
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

            <div>
              <Label className="mb-2 block">Obróbka treści</Label>
              <ContentModeTiles value={contentMode} onChange={setContentMode} />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label className="mb-2 block">Język</Label>
                <LanguageTiles
                  value={language}
                  onChange={setLanguage}
                  ariaLabel="Język"
                />
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
                  ? "Uruchamiam generację…"
                  : "Generacja leci w tle (60–90 s) — CV trafi na listę „Wygenerowane CV”. Możesz zamknąć okno."}
              </p>
              <Button
                size="md"
                disabled={!canSubmit || generateMut.isPending}
                onClick={() => {
                  setError(null);
                  generateMut.mutate();
                }}
              >
                {generateMut.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Uruchamiam…
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Generuj CV w tle
                  </>
                )}
              </Button>
            </div>
          </div>
        )}
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

