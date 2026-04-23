"use client";

import * as React from "react";
import { useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  FileUp,
  Sparkles,
  Upload,
  UserCheck,
  XCircle,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

/**
 * Response shape from POST /api/candidates/from-cv (201).
 * Kept deliberately loose (Record<string, any>) on the nested candidate so
 * we don't duplicate the full backend schema here — the modal only surfaces
 * the handful of fields the recruiter needs to verify inline.
 */
interface FromCVResponse {
  candidate: {
    id: number;
    name: string;
    lastname: string;
    email?: string | null;
    phone?: string | null;
    location?: string | null;
    linkedin?: string | null;
    years_it_experience?: number | null;
    skills?: Array<{ name: string } | string> | null;
  };
  confidence: Record<string, number>;
  source?: string | null;
}

/**
 * 409 payload: FastAPI nests our structured detail under `detail`.
 */
interface ConflictDetail {
  detail: string;
  existing_candidate_id: number;
  matches: Array<{
    candidate_id: number;
    name?: string | null;
    lastname?: string | null;
    email?: string | null;
    match_score: number;
    match_reasons: string[];
  }>;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded?: (candidateId: number) => void;
}

const LOW_CONFIDENCE = 0.7;

const FIELD_LABELS: Record<string, string> = {
  first_name: "Imię",
  last_name: "Nazwisko",
  email: "Email",
  phone: "Telefon",
  city: "Miasto",
  linkedin_url: "LinkedIn",
  years_it_experience: "Lata w IT",
};

function formatSkill(s: { name: string } | string): string {
  return typeof s === "string" ? s : s.name;
}

function isLow(confidence: Record<string, number>, key: string): boolean {
  const v = confidence?.[key];
  return typeof v === "number" && v < LOW_CONFIDENCE;
}

function ConfidenceRow({
  label,
  value,
  low,
}: {
  label: string;
  value: React.ReactNode;
  low: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-3 py-1.5 text-sm",
        low &&
          "rounded-v2-s bg-amber-50 border border-amber-200 px-2 -mx-2"
      )}
    >
      <dt className="text-[hsl(var(--text-muted))]">{label}</dt>
      <dd className="text-right text-[hsl(var(--text-title))] font-medium flex items-center gap-1.5">
        {low && (
          <AlertTriangle
            aria-label="AI ma niską pewność — zweryfikuj"
            className="h-3.5 w-3.5 text-amber-600"
          />
        )}
        <span>{value || <span className="text-[hsl(var(--text-muted))]">—</span>}</span>
      </dd>
    </div>
  );
}

export function AddCandidateFromCVModal({ open, onOpenChange, onAdded }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<FromCVResponse | null>(null);
  const [conflict, setConflict] = useState<ConflictDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFile(null);
    setResult(null);
    setConflict(null);
    setError(null);
  };

  // Reset state when the modal closes so a second open starts clean.
  React.useEffect(() => {
    if (!open) reset();
  }, [open]);

  const uploadMut = useMutation({
    mutationFn: async ({ f, force }: { f: File; force?: boolean }) => {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.post<FromCVResponse>(
        `/api/candidates/from-cv${force ? "?force=true" : ""}`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      return r.data;
    },
    onSuccess: (data) => {
      setResult(data);
      setConflict(null);
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      onAdded?.(data.candidate.id);
    },
    onError: (err: AxiosError<{ detail?: ConflictDetail | string }>) => {
      // 409 → structured duplicate alert; other errors → plain message.
      if (err.response?.status === 409) {
        const detail = err.response.data?.detail;
        if (detail && typeof detail === "object" && "matches" in detail) {
          setConflict(detail);
          setError(null);
          return;
        }
      }
      const msg =
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Nie udało się przetworzyć pliku. Sprawdź format i spróbuj ponownie.";
      setError(msg);
    },
  });

  const handleFile = (f: File) => {
    const name = f.name.toLowerCase();
    if (!name.endsWith(".pdf") && !name.endsWith(".docx") && !name.endsWith(".txt")) {
      setError("Dozwolone formaty: PDF, DOCX, TXT.");
      return;
    }
    setError(null);
    setFile(f);
  };

  const handleUpload = (force = false) => {
    if (!file) return;
    setError(null);
    setConflict(null);
    uploadMut.mutate({ f: file, force });
  };

  // ── success view: show parsed fields + confidence warnings ────────────
  if (result) {
    const c = result.candidate;
    const conf = result.confidence || {};
    const skills = Array.isArray(c.skills)
      ? c.skills.slice(0, 12).map(formatSkill)
      : [];
    const lowCount = Object.values(conf).filter(
      (v) => typeof v === "number" && v < LOW_CONFIDENCE
    ).length;

    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent size="md">
          <DialogHeader>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-[hsl(var(--accent))]" />
              <DialogTitle>Kandydat dodany</DialogTitle>
            </div>
            <DialogDescription>
              {c.name} {c.lastname} — profil utworzony z CV.
              {result.source && (
                <span className="ml-1 text-xs text-[hsl(var(--text-muted))]">
                  (źródło: {result.source})
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {lowCount > 0 && (
              <div className="mb-3 flex items-start gap-2 rounded-v2-s bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-900">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>
                  {lowCount}{" "}
                  {lowCount === 1 ? "pole wymaga weryfikacji" : "pól wymaga weryfikacji"}{" "}
                  — AI nie miało pełnej pewności. Otwórz profil żeby poprawić.
                </span>
              </div>
            )}
            <dl className="divide-y divide-[hsl(var(--border-subtle))]">
              <ConfidenceRow
                label={FIELD_LABELS.first_name}
                value={c.name}
                low={isLow(conf, "first_name")}
              />
              <ConfidenceRow
                label={FIELD_LABELS.last_name}
                value={c.lastname}
                low={isLow(conf, "last_name")}
              />
              <ConfidenceRow
                label={FIELD_LABELS.email}
                value={c.email}
                low={isLow(conf, "email")}
              />
              <ConfidenceRow
                label={FIELD_LABELS.phone}
                value={c.phone}
                low={isLow(conf, "phone")}
              />
              <ConfidenceRow
                label={FIELD_LABELS.city}
                value={c.location}
                low={isLow(conf, "city")}
              />
              <ConfidenceRow
                label={FIELD_LABELS.linkedin_url}
                value={c.linkedin}
                low={isLow(conf, "linkedin_url")}
              />
              <ConfidenceRow
                label={FIELD_LABELS.years_it_experience}
                value={c.years_it_experience ?? null}
                low={isLow(conf, "years_it_experience")}
              />
            </dl>
            {skills.length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
                  Wyciągnięte technologie ({skills.length})
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center rounded-v2-s bg-[hsl(var(--accent-soft))] px-2 py-0.5 text-xs text-[hsl(var(--accent))]"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => reset()}>
              Dodaj kolejnego
            </Button>
            <Button variant="outline" asChild>
              <Link href={`/candidates/${c.id}`}>Otwórz profil</Link>
            </Button>
            <Button variant="primary" onClick={() => onOpenChange(false)}>
              Zamknij
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  // ── conflict view: duplicate candidate found ───────────────────────────
  if (conflict) {
    const top = conflict.matches[0];
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent size="md">
          <DialogHeader>
            <div className="flex items-center gap-2">
              <UserCheck className="h-5 w-5 text-amber-600" />
              <DialogTitle>Znaleziono podobnego kandydata</DialogTitle>
            </div>
            <DialogDescription>{conflict.detail}</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div className="space-y-2">
              {conflict.matches.slice(0, 5).map((m) => (
                <Link
                  key={m.candidate_id}
                  href={`/candidates/${m.candidate_id}`}
                  className="flex items-center justify-between rounded-v2-m border border-[hsl(var(--border-subtle))] p-3 text-sm hover:bg-[hsl(var(--accent-soft))] hover:border-[hsl(var(--accent))]"
                >
                  <div>
                    <div className="font-medium text-[hsl(var(--text-title))]">
                      {m.name} {m.lastname}
                    </div>
                    {m.email && (
                      <div className="text-xs text-[hsl(var(--text-muted))]">
                        {m.email}
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-[hsl(var(--text-muted))]">
                      match: {(m.match_score * 100).toFixed(0)}%
                    </div>
                    <div className="text-[10px] text-[hsl(var(--text-muted))]">
                      {m.match_reasons.join(", ")}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConflict(null)}>
              Anuluj upload
            </Button>
            <Button
              variant="outline"
              loading={uploadMut.isPending}
              onClick={() => handleUpload(true)}
            >
              Zapisz mimo to
            </Button>
            <Button variant="primary" asChild>
              <Link href={`/candidates/${top.candidate_id}`}>
                Otwórz istniejącego
              </Link>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  // ── upload view ────────────────────────────────────────────────────────
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[hsl(var(--accent))]" />
            <DialogTitle>Dodaj kandydata z CV</DialogTitle>
          </div>
          <DialogDescription>
            Wrzuć PDF, DOCX lub TXT — AI wyciągnie imię, nazwisko, email, telefon,
            miasto i technologie.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) handleFile(f);
            }}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
            }}
            className={cn(
              "cursor-pointer rounded-v2-m border-2 border-dashed p-8 text-center transition-colors",
              dragOver
                ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]"
                : "border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/60 hover:bg-[hsl(var(--bg-canvas))]/40"
            )}
          >
            <FileUp className="h-10 w-10 mx-auto mb-3 text-[hsl(var(--text-muted))]" />
            {file ? (
              <div>
                <div className="text-sm font-medium text-[hsl(var(--text-title))]">
                  {file.name}
                </div>
                <div className="text-xs text-[hsl(var(--text-muted))]">
                  {(file.size / 1024).toFixed(1)} KB
                </div>
              </div>
            ) : (
              <div>
                <div className="text-sm font-medium text-[hsl(var(--text-title))]">
                  Przeciągnij CV lub kliknij
                </div>
                <div className="text-xs text-[hsl(var(--text-muted))] mt-1">
                  PDF · DOCX · TXT · max 10 MB
                </div>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
              }}
            />
          </div>
          {error && (
            <div
              role="alert"
              className="mt-3 inline-flex items-center gap-2 text-sm text-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))] px-3 py-2 rounded-v2-s w-full"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button
            variant="primary"
            disabled={!file}
            loading={uploadMut.isPending}
            onClick={() => handleUpload(false)}
          >
            <Upload className="h-4 w-4" /> Parsuj CV
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
