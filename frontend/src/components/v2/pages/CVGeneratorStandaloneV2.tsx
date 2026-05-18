"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronsUpDown,
  Download,
  Loader2,
  Search,
  Sparkles,
  UserSearch,
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

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function CVGeneratorStandaloneV2() {
  const toast = useToast();

  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [stageId, setStageId] = useState<string>("");
  const [language, setLanguage] = useState<"pl" | "en">("pl");
  const [blindCv, setBlindCv] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  // ── Candidate typeahead search ──────────────────────────────────────────
  const candidatesQuery = useQuery({
    queryKey: ["cv-gen-candidates", candidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: candidateQuery, limit: 20 },
      });
      return res.data;
    },
    enabled: candidateOpen,
    staleTime: 30_000,
  });

  // ── Recruitments for picked candidate ───────────────────────────────────
  const recruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments", candidate?.id],
    queryFn: async () => {
      if (!candidate) return [] as RecruitmentOption[];
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidate.id}/recruitments`,
      );
      return res.data;
    },
    enabled: !!candidate,
  });

  const selectedRecruitment = useMemo(() => {
    if (!stageId) return null;
    return (
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ?? null
    );
  }, [recruitmentsQuery.data, stageId]);

  const canSubmit =
    !!candidate && !!selectedRecruitment && selectedRecruitment.ready;

  // ── Generate ─────────────────────────────────────────────────────────────
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
          timeout: 180_000, // Claude can take 30–60s; allow up to 3 min
        },
      );
      const disposition = res.headers["content-disposition"] || "";
      const filenameMatch = disposition.match(/filename="?([^";]+)"?/);
      const filename = filenameMatch ? filenameMatch[1] : `CV_${candidate.lastname}.docx`;
      let parsedWarnings: string[] = [];
      const wHeader = res.headers["x-generator-warnings"];
      if (typeof wHeader === "string") {
        try {
          parsedWarnings = JSON.parse(wHeader);
        } catch {
          parsedWarnings = [];
        }
      }
      return { blob: res.data as Blob, filename, warnings: parsedWarnings };
    },
    onSuccess: ({ blob, filename, warnings: w }) => {
      setWarnings(w);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.showSuccess("CV wygenerowane i pobrane.");
    },
    onError: (err: unknown) => {
      const detail = extractErrorDetail(err);
      toast.showError(detail || "Generowanie nie powiodło się.");
    },
  });

  return (
    <div className="container mx-auto max-w-3xl py-8">
      <div className="mb-8 flex items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-3 text-primary">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Generator CV</h1>
          <p className="text-sm text-muted-foreground">
            Wybierz konsultanta i proces rekrutacyjny — system zbierze profil
            championa oraz notatki z rozmów i wygeneruje branżowo dopasowane CV
            w szablonie B2B Network.
          </p>
        </div>
      </div>

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

      {candidate && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Krok 3 — Opcje</CardTitle>
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
                  Anonimizuje imię, nazwisko i nazwy firm w doświadczeniu —
                  używaj przy share-ach klientom przed zaakceptowaniem profilu.
                </p>
              </div>
              <Switch checked={blindCv} onCheckedChange={setBlindCv} />
            </div>
          </CardContent>
        </Card>
      )}

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
          disabled={!canSubmit || generateMut.isPending}
          onClick={() => generateMut.mutate()}
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
  );
}

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
    // Blob errors — we can't read sync; show generic message.
    return "";
  }
  if (typeof data === "string") return data;
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "";
}

