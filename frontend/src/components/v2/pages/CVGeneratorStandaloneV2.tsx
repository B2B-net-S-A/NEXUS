"use client";

import { useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronsUpDown,
  Download,
  FileText,
  Loader2,
  Search,
  Sparkles,
  Upload,
  UserSearch,
  X,
} from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

type CandidateOption = {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  position?: string | null;
  email?: string | null;
};

type RecruitmentOption = {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage: string;
  has_champion: boolean;
  has_notes: boolean;
  ready: boolean;
};

type Mode = "new" | "old";

const STAGE_LABELS: Record<string, string> = {
  new: "Nowy",
  contacted: "Kontakt",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview",
  client_review: "U klienta",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  active: "Aktywny",
  rejected: "Odrzucony",
  withdrawn: "Rezygnacja",
  on_hold: "Wstrzymany",
};

const CV_ACCEPT = ".pdf,.docx,.doc";
const CHAMPION_ACCEPT = ".docx,.doc";
const MAX_UPLOAD_MB = 50;

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

function parseDispositionFilename(disposition: string, fallback: string): string {
  const match = disposition.match(/filename="?([^";]+)"?/);
  return match ? match[1] : fallback;
}

function parseWarningsHeader(header: unknown): string[] {
  if (typeof header !== "string") return [];
  try {
    const parsed = JSON.parse(header);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function CVGeneratorStandaloneV2() {
  const toast = useToast();

  // ── Mode (New vs Old) ───────────────────────────────────────────────────
  const [mode, setMode] = useState<Mode>("new");

  // ── New mode state ──────────────────────────────────────────────────────
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [stageId, setStageId] = useState<string>("");

  // ── Old mode state ──────────────────────────────────────────────────────
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [championFile, setChampionFile] = useState<File | null>(null);
  const [screeningNotes, setScreeningNotes] = useState("");

  // ── Shared options ──────────────────────────────────────────────────────
  const [language, setLanguage] = useState<"pl" | "en">("pl");
  const [blindCv, setBlindCv] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  // ── New mode queries ────────────────────────────────────────────────────
  const candidatesQuery = useQuery({
    queryKey: ["cv-gen-candidates", candidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: candidateQuery, limit: 20 },
      });
      return res.data;
    },
    enabled: candidateOpen && mode === "new",
    staleTime: 30_000,
  });

  const recruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments", candidate?.id],
    queryFn: async () => {
      if (!candidate) return [] as RecruitmentOption[];
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidate.id}/recruitments`,
      );
      return res.data;
    },
    enabled: !!candidate && mode === "new",
  });

  const selectedRecruitment = useMemo(() => {
    if (!stageId) return null;
    return (
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ?? null
    );
  }, [recruitmentsQuery.data, stageId]);

  const canSubmitNew =
    !!candidate && !!selectedRecruitment && selectedRecruitment.ready;
  const canSubmitOld = !!cvFile;
  const canSubmit = mode === "new" ? canSubmitNew : canSubmitOld;

  // ── New mode mutation ───────────────────────────────────────────────────
  const generateMut = useMutation({
    mutationFn: async () => {
      if (!candidate || !selectedRecruitment) {
        throw new Error("Missing inputs");
      }
      const res = await api.post(
        "/api/cv-generator/generate",
        {
          candidate_id: candidate.id,
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
          `CV_${candidate.lastname}.docx`,
        ),
        warnings: parseWarningsHeader(res.headers["x-generator-warnings"]),
      };
    },
    onSuccess: ({ blob, filename, warnings: w }) => {
      setWarnings(w);
      downloadBlob(blob, filename);
      toast.showSuccess("CV wygenerowane i pobrane.");
    },
    onError: (err: unknown) => {
      const detail = extractErrorDetail(err);
      toast.showError(detail || "Generowanie nie powiodło się.");
    },
  });

  // ── Old mode mutation ───────────────────────────────────────────────────
  const uploadMut = useMutation({
    mutationFn: async () => {
      if (!cvFile) throw new Error("CV file required");
      const fd = new FormData();
      fd.append("cv_file", cvFile);
      fd.append("language", language);
      fd.append("blind_cv", String(blindCv));
      if (screeningNotes.trim()) fd.append("screening_notes", screeningNotes);
      if (championFile) fd.append("champion_file", championFile);
      const res = await api.post("/api/cv-generator/generate-upload", fd, {
        responseType: "blob",
        timeout: 180_000,
      });
      return {
        blob: res.data as Blob,
        filename: parseDispositionFilename(
          res.headers["content-disposition"] || "",
          "CV_B2B.docx",
        ),
        warnings: parseWarningsHeader(res.headers["x-generator-warnings"]),
      };
    },
    onSuccess: ({ blob, filename, warnings: w }) => {
      setWarnings(w);
      downloadBlob(blob, filename);
      toast.showSuccess("CV wygenerowane i pobrane.");
    },
    onError: (err: unknown) => {
      const detail = extractErrorDetail(err);
      toast.showError(detail || "Generowanie nie powiodło się.");
    },
  });

  const activeMut = mode === "new" ? generateMut : uploadMut;

  function handleSubmit() {
    setWarnings([]);
    activeMut.mutate();
  }

  function handleModeChange(next: string) {
    const nextMode = next === "old" ? "old" : "new";
    setMode(nextMode);
    setWarnings([]);
  }

  return (
    <div className="container mx-auto max-w-3xl py-8">
      <div className="mb-6 flex items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-3 text-primary">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Generator CV</h1>
          <p className="text-sm text-muted-foreground">
            Wygeneruj branżowo dopasowane CV w szablonie B2B Network. Dwa tryby:
            zaciąganie danych z NEXUSa lub manualny upload plików (1:1 jak
            zewnętrzny CV-Generator).
          </p>
        </div>
      </div>

      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">Tryb</CardTitle>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={mode}
            onValueChange={handleModeChange}
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <label
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                mode === "new"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/30",
              )}
            >
              <RadioGroupItem value="new" className="mt-1" />
              <div>
                <div className="text-sm font-medium">New (z procesu)</div>
                <div className="text-xs text-muted-foreground">
                  Wybierz konsultanta i rekrutację — system zaciąga CV, profil
                  championa i notatki z NEXUSa.
                </div>
              </div>
            </label>
            <label
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                mode === "old"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/30",
              )}
            >
              <RadioGroupItem value="old" className="mt-1" />
              <div>
                <div className="text-sm font-medium">Old (upload plików)</div>
                <div className="text-xs text-muted-foreground">
                  Wgraj CV (PDF / DOCX), opcjonalnie Profil Championa i
                  notatki — 1:1 jak external CV-Generator.
                </div>
              </div>
            </label>
          </RadioGroup>
        </CardContent>
      </Card>

      {mode === "new" ? (
        <NewModeForm
          candidate={candidate}
          candidateOpen={candidateOpen}
          candidateQuery={candidateQuery}
          candidatesQuery={candidatesQuery}
          recruitmentsQuery={recruitmentsQuery}
          selectedRecruitment={selectedRecruitment}
          stageId={stageId}
          setCandidate={setCandidate}
          setCandidateOpen={setCandidateOpen}
          setCandidateQuery={setCandidateQuery}
          setStageId={setStageId}
          setWarnings={setWarnings}
        />
      ) : (
        <OldModeForm
          cvFile={cvFile}
          championFile={championFile}
          screeningNotes={screeningNotes}
          setCvFile={setCvFile}
          setChampionFile={setChampionFile}
          setScreeningNotes={setScreeningNotes}
        />
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Opcje</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div>
            <Label className="mb-2 block">Język CV</Label>
            <RadioGroup
              value={language}
              onValueChange={(v) => setLanguage(v as "pl" | "en")}
              className="flex gap-6"
            >
              <label className="flex items-center gap-2 text-sm">
                <RadioGroupItem value="pl" />
                Polski
              </label>
              <label className="flex items-center gap-2 text-sm">
                <RadioGroupItem value="en" />
                English
              </label>
            </RadioGroup>
          </div>

          <div className="flex items-center justify-between gap-4">
            <div>
              <Label className="block">Blind CV</Label>
              <p className="text-xs text-muted-foreground">
                Anonimizuje imię, nazwisko i nazwy firm w doświadczeniu — używaj
                przy share-ach klientom przed zaakceptowaniem profilu.
              </p>
            </div>
            <Switch checked={blindCv} onCheckedChange={setBlindCv} />
          </div>
        </CardContent>
      </Card>

      {warnings.length > 0 && (
        <div className="mt-4">
          <Alert
            variant="warning"
            title="Uwagi z analizy Claude"
            description={
              <ul className="ml-4 list-disc">
                {warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            }
          />
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Generacja zajmuje 30–60 sekund (Claude Sonnet 4 + DOCX render).
        </p>
        <Button
          size="lg"
          disabled={!canSubmit || activeMut.isPending}
          onClick={handleSubmit}
        >
          {activeMut.isPending ? (
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
  );
}

// ── New mode form ──────────────────────────────────────────────────────────

type NewModeFormProps = {
  candidate: CandidateOption | null;
  candidateOpen: boolean;
  candidateQuery: string;
  candidatesQuery: {
    data?: CandidateOption[];
    isLoading: boolean;
  };
  recruitmentsQuery: {
    data?: RecruitmentOption[];
    isLoading: boolean;
  };
  selectedRecruitment: RecruitmentOption | null;
  stageId: string;
  setCandidate: (c: CandidateOption | null) => void;
  setCandidateOpen: (v: boolean) => void;
  setCandidateQuery: (v: string) => void;
  setStageId: (v: string) => void;
  setWarnings: (w: string[]) => void;
};

function NewModeForm({
  candidate,
  candidateOpen,
  candidateQuery,
  candidatesQuery,
  recruitmentsQuery,
  selectedRecruitment,
  stageId,
  setCandidate,
  setCandidateOpen,
  setCandidateQuery,
  setStageId,
  setWarnings,
}: NewModeFormProps) {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Krok 1 — Konsultant</CardTitle>
          <CardDescription>
            Zacznij wpisywać imię, nazwisko lub e-mail.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={candidateOpen}
                className="w-full justify-between"
              >
                <span className="flex items-center gap-2 truncate">
                  <UserSearch className="h-4 w-4 text-muted-foreground" />
                  {candidate ? (
                    <span className="truncate">
                      {candidate.full_name}
                      {candidate.position ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {candidate.position}
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">
                      Wybierz konsultanta…
                    </span>
                  )}
                </span>
                <ChevronsUpDown className="h-4 w-4 text-muted-foreground" />
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="start"
              className="w-[--radix-popover-trigger-width] p-0"
            >
              <Command shouldFilter={false}>
                <div className="flex items-center border-b border-border px-3">
                  <Search className="mr-2 h-4 w-4 text-muted-foreground" />
                  <CommandInput
                    placeholder="Szukaj kandydata…"
                    value={candidateQuery}
                    onValueChange={setCandidateQuery}
                    className="h-10 border-0"
                  />
                </div>
                <CommandList>
                  {candidatesQuery.isLoading && (
                    <div className="p-4 text-center text-xs text-muted-foreground">
                      Ładowanie…
                    </div>
                  )}
                  <CommandEmpty>Brak wyników.</CommandEmpty>
                  <CommandGroup>
                    {(candidatesQuery.data ?? []).map((c) => (
                      <CommandItem
                        key={c.id}
                        value={String(c.id)}
                        onSelect={() => {
                          setCandidate(c);
                          setStageId("");
                          setWarnings([]);
                          setCandidateOpen(false);
                        }}
                      >
                        <div className="flex flex-col">
                          <span className="font-medium">{c.full_name}</span>
                          <span className="text-xs text-muted-foreground">
                            {[c.position, c.email].filter(Boolean).join(" · ")}
                          </span>
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </CardContent>
      </Card>

      {candidate && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Krok 2 — Proces rekrutacyjny</CardTitle>
            <CardDescription>
              Wymagany Profil Championa oraz co najmniej jedna notatka z rozmowy
              dla wybranego procesu.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select value={stageId} onValueChange={setStageId}>
              <SelectTrigger>
                <SelectValue placeholder="Wybierz rekrutację…" />
              </SelectTrigger>
              <SelectContent>
                {(recruitmentsQuery.data ?? []).map((r) => (
                  <SelectItem key={r.stage_id} value={String(r.stage_id)}>
                    <span className="flex items-center gap-2">
                      <span className="truncate">{r.job_title}</span>
                      <span className="text-xs text-muted-foreground">
                        · {stageLabel(r.stage)}
                      </span>
                      <ReadinessChip ready={r.ready} />
                    </span>
                  </SelectItem>
                ))}
                {(recruitmentsQuery.data ?? []).length === 0 &&
                  !recruitmentsQuery.isLoading && (
                    <div className="p-3 text-xs text-muted-foreground">
                      Brak procesów rekrutacyjnych dla tego konsultanta.
                    </div>
                  )}
              </SelectContent>
            </Select>

            {selectedRecruitment && (
              <div className="flex flex-wrap gap-2 text-xs">
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
              <Alert
                variant="warning"
                title="Nie można wygenerować CV"
                description={
                  <div className="space-y-1">
                    {!selectedRecruitment.has_champion && (
                      <div>
                        Brakuje Profilu Championa (must-have, nice-to-have,
                        kontekst projektu). Uzupełnij go na karcie oferty zanim
                        wygenerujesz CV.
                      </div>
                    )}
                    {!selectedRecruitment.has_notes && (
                      <div>
                        Brak notatek z rozmów — wymagana co najmniej jedna:
                        screening, transkrypt rozmowy CloudTalk albo notatka
                        procesu.
                      </div>
                    )}
                  </div>
                }
              />
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}

// ── Old mode form ──────────────────────────────────────────────────────────

type OldModeFormProps = {
  cvFile: File | null;
  championFile: File | null;
  screeningNotes: string;
  setCvFile: (f: File | null) => void;
  setChampionFile: (f: File | null) => void;
  setScreeningNotes: (v: string) => void;
};

function OldModeForm({
  cvFile,
  championFile,
  screeningNotes,
  setCvFile,
  setChampionFile,
  setScreeningNotes,
}: OldModeFormProps) {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Krok 1 — Plik CV</CardTitle>
          <CardDescription>
            Wgraj surowe CV kandydata (PDF lub DOCX, max {MAX_UPLOAD_MB} MB) —
            Claude przeanalizuje treść i wyciągnie strukturę.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FileDropZone
            file={cvFile}
            onFile={setCvFile}
            accept={CV_ACCEPT}
            label="Upuść CV tutaj lub kliknij, by wybrać plik"
            description="PDF / DOCX / DOC"
          />
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Krok 2 — Profil Championa (opcjonalnie)</CardTitle>
          <CardDescription>
            Wgraj DOCX z sekcjami MUST-HAVE / NICE-TO-HAVE / Kontekst /
            Pytania — system wytłuści kluczowe technologie w wygenerowanym CV
            i zwróci listę brakujących wymagań.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FileDropZone
            file={championFile}
            onFile={setChampionFile}
            accept={CHAMPION_ACCEPT}
            label="Upuść DOCX championa tutaj lub kliknij, by wybrać"
            description="DOCX / DOC"
          />
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Krok 3 — Notatki ze screeningu (opcjonalnie)</CardTitle>
          <CardDescription>
            Wklej notatki z rozmowy rekrutera — Claude wzbogaci CV o
            technologie i kompetencje wspomniane na screeningu.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Textarea
            rows={6}
            value={screeningNotes}
            onChange={(e) => setScreeningNotes(e.target.value)}
            placeholder="Np. „Kandydat ma 3 lata doświadczenia z Kubernetes, prowadził migrację Jenkinsa do GitHub Actions w poprzedniej firmie…”"
          />
        </CardContent>
      </Card>
    </>
  );
}

// ── File drop zone ─────────────────────────────────────────────────────────

type FileDropZoneProps = {
  file: File | null;
  onFile: (f: File | null) => void;
  accept: string;
  label: string;
  description: string;
};

function FileDropZone({
  file,
  onFile,
  accept,
  label,
  description,
}: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragOver, setDragOver] = useState(false);

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const next = e.target.files?.[0] ?? null;
    onFile(next);
  }

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const next = e.dataTransfer.files?.[0] ?? null;
    if (next) onFile(next);
  }

  function handleDragOver(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (!dragOver) setDragOver(true);
  }

  function handleDragLeave(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }

  if (file) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
        <div className="flex min-w-0 items-center gap-3">
          <FileText className="h-5 w-5 flex-shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{file.name}</div>
            <div className="text-xs text-muted-foreground">
              {(file.size / 1024).toFixed(0)} KB
            </div>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onFile(null)}
          aria-label="Usuń plik"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <label
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors",
        dragOver
          ? "border-primary bg-primary/5"
          : "border-border hover:bg-muted/30",
      )}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleChange}
        className="sr-only"
      />
      <Upload className="h-6 w-6 text-muted-foreground" />
      <div className="text-sm font-medium">{label}</div>
      <div className="text-xs text-muted-foreground">{description}</div>
    </label>
  );
}

// ── Inline UI helpers ──────────────────────────────────────────────────────

function ReadinessChip({ ready }: { ready: boolean }) {
  return ready ? (
    <CheckCircle2 className="ml-1 h-3.5 w-3.5 text-emerald-600" />
  ) : (
    <AlertTriangle className="ml-1 h-3.5 w-3.5 text-amber-500" />
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

function extractErrorDetail(err: unknown): string {
  if (typeof err !== "object" || err === null) return "";
  const anyErr = err as { response?: { data?: unknown } };
  const data = anyErr.response?.data;
  if (data instanceof Blob) {
    return "";
  }
  if (typeof data === "string") return data;
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "";
}
