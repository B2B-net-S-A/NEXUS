"use client";

import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";
import * as React from"react";
import { useRef, useState } from"react";
import Link from"next/link";
import { useMutation, useQueryClient } from"@tanstack/react-query";
import type { AxiosError } from"axios";
import {
 AlertCircle,
 AlertTriangle,
 Check,
 CheckCircle2,
 FileUp,
 Loader2,
 Sparkles,
 Upload,
 UserCheck,
 XCircle,
} from"lucide-react";
import api, { candidateStageCvApi, phase3Api, type CandidatePipelineRow } from"@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from"@/lib/utils";
import { celebrate } from"@/lib/celebrate";
import { assignErrorMessage } from "@/lib/assign-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { ClosedCardRestore } from "@/components/v2/recruitment/ClosedCardRestore";
import type { ClosedRow } from "@/components/v2/recruitment/AddToRecruitmentDialog";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { invalidateCandidateMutation } from"@/components/v2/pages/candidate-cache";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";
import { attachCvFormData, isPhoneAndNameMatch, isSameFileMatch } from"@/lib/add-candidate-cv";

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
 /** Rekrutacja, do której okno dodaje osobę (do „Nowych”). */
 job: { id: number; title: string };
 /** Coś zmieniło się na Tablicy (dodanie, przywrócenie, nowe CV). */
 onChanged?: () => void;
 /** „Otwórz w panelu” — panel osoby na Tablicy tej rekrutacji. */
 onOpenPerson?: (candidateId: number) => void;
}

/** Wynik dodania do rekrutacji (13.10.2026: okno samo dodaje do „Nowych”). */
type JobAdd =
 | { kind: "added" }
 | { kind: "already"; label: string | null }
 | { kind: "closed"; row: ClosedRow }
 | { kind: "skipped"; text: string };

/**
 * Osoba z bazy po akcji w oknie — widok końcowy. `client_cv`: plik „B2B_…”
 * został CV do klienta tej rekrutacji, `client_cv_kept`: klient ma już CV
 * tej osoby, plik poszedł tylko do profilu (15.10.2026).
 */
type ExistingOutcome =
 | {
 kind: "added" | "restored" | "replaced" | "hired" | "profile_only" | "client_cv" | "client_cv_kept";
 candidateId: number;
 name: string;
 stageName?: string | null;
 /** Nazwa pliku z odpowiedzi serwera (wgranie na zgłoszenie). */
 uploadedFilename?: string | null;
 }
 | { kind: "closed"; candidateId: number; name: string; row: ClosedRow };

/**
 * Karta osoby w tej rekrutacji według kolumny Tablicy (`board_column` —
 * ta sama reguła co karta i `proposals/bulk`): lista rezerwowa jest zamknięta,
 * choć nie jest etapem końcowym, a zatrudniony nie jest „zamknięty”.
 */
type CardState = "none" | "in_progress" | "hired" | "closed";

function cardState(card: CandidatePipelineRow | null): CardState {
 if (!card) return "none";
 if (card.board_column === "closed") return "closed";
 if (card.board_column === "hired") return "hired";
 return "in_progress";
}

/** Formaty, które mogą zostać CV rekrutacji (kopia etapu bierze się z głównego CV). */
function canBeStageCv(file: File): boolean {
 return /\.(pdf|docx?)$/i.test(file.name);
}

async function addToJob(jobId: number, candidateId: number): Promise<JobAdd> {
 const response = await proposalsBulkApi.add(jobId, { candidate_ids: [candidateId], source: "quick_add" });
 if (response.total_added > 0) return { kind: "added" };
 const row = response.skipped.find((r) => r.candidate_id === candidateId) ?? response.skipped[0];
 if (row?.reason === "closed_in_job" && row.closed) return { kind: "closed", row: row as ClosedRow };
 if (row?.reason === "already_in_job") return { kind: "already", label: row.reason_label ?? null };
 return {
 kind: "skipped",
 text: row?.reason_label ?? formatReasonCounts(summarizeBulkResult(response).skipped),
 };
}

/** Bieżąca karta osoby w tej rekrutacji (najnowszy wiersz etapu) albo `null`. */
async function jobCard(candidateId: number, jobId: number): Promise<CandidatePipelineRow | null> {
 const { data } = await phase3Api.candidatePipelines(candidateId);
 return data.pipelines.find((row) => row.job_id === jobId) ?? null;
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
 className={cn("flex items-start justify-between gap-3 py-1.5 text-sm",
 low &&"rounded-md bg-amber-50 border border-amber-200 px-2 -mx-2"
 )}
 >
 <dt className="text-muted-foreground">{label}</dt>
 <dd className="text-right text-foreground font-medium flex items-center gap-1.5">
 {low && (
 <AlertTriangle
 aria-label="AI ma niską pewność — zweryfikuj"
 className="h-3.5 w-3.5 text-amber-600"
 />
 )}
 <span>{value || <span className="text-muted-foreground">—</span>}</span>
 </dd>
 </div>
 );
}

export function AddCandidateFromCVModal({ open, onOpenChange, job, onChanged, onOpenPerson }: Props) {
 const queryClient = useQueryClient();
 const fileInputRef = useRef<HTMLInputElement>(null);
 const [file, setFile] = useState<File | null>(null);
 const [dragOver, setDragOver] = useState(false);
 const [result, setResult] = useState<FromCVResponse | null>(null);
 // Nowy kandydat z CV: wynik dodania do „Nowych” tej rekrutacji.
 const [newCandidateAdd, setNewCandidateAdd] = useState<JobAdd | "pending" | "failed" | null>(null);
 const [conflict, setConflict] = useState<ConflictDetail | null>(null);
 // Osoba z bazy: karta w tej rekrutacji (do opisu, co zrobi przycisk).
 const [existingCard, setExistingCard] = useState<CandidatePipelineRow | null | "loading" | "unknown">(null);
 const [outcome, setOutcome] = useState<ExistingOutcome | null>(null);
 const [error, setError] = useState<string | null>(null);

 const reset = () => {
 setFile(null);
 setResult(null);
 setNewCandidateAdd(null);
 setConflict(null);
 setExistingCard(null);
 setOutcome(null);
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
 `/api/candidates/from-cv${force ?"?force=true" :""}`,
 fd,
 {
 headers: {"Content-Type":"multipart/form-data" },
 // Pełny odczyt CV (prompt v7) trwa dłużej niż domyślne 30 s instancji.
 timeout: SLOW_ENDPOINT_TIMEOUT_MS,
 }
 );
 return r.data;
 },
 onSuccess: (data) => {
 setResult(data);
 setConflict(null);
 queryClient.invalidateQueries({ queryKey: ["candidates"] });
 queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 celebrate({ small: true, message: "Kandydat dodany! ✨" });
 // Nowy kandydat z CV od razu trafia do „Nowych” tej rekrutacji.
 setNewCandidateAdd("pending");
 addToJob(job.id, data.candidate.id)
 .then((add) => setNewCandidateAdd(add))
 .catch(() => setNewCandidateAdd("failed"))
 .finally(() => onChanged?.());
 },
 onError: (err: AxiosError<{ detail?: ConflictDetail | string }>) => {
 // 409 → structured duplicate alert; other errors → plain message.
 if (err.response?.status === 409) {
 const detail = err.response.data?.detail;
 if (detail && typeof detail === "object" &&"matches" in detail) {
 setConflict(detail);
 setError(null);
 const top = detail.matches[0];
 if (top) {
 // Tylko do opisu w oknie — akcję i tak rozstrzyga odpowiedź serwera.
 setExistingCard("loading");
 jobCard(top.candidate_id, job.id)
 .then(setExistingCard)
 .catch(() => setExistingCard("unknown"));
 }
 return;
 }
 }
 const msg =
 typeof err.response?.data?.detail === "string"
 ? err.response.data.detail : "Nie udało się przetworzyć pliku. Sprawdź format i spróbuj ponownie.";
 setError(msg);
 },
 });

 // Osoba już jest w bazie (ten sam e-mail albo ten sam plik): CV na górę
 // profilu i osoba w tej rekrutacji — prośba rekruterów z 13.10.2026.
 // Osoba w toku: nowe CV zastępuje kopię CV przy jej zgłoszeniu (jedno
 // żądanie `…/cv/original/upload`). Pozostali: plik jako główne CV
 // (deduplikacja po SHA ustawia też identyczny plik), potem „Nowi”.
 const existingMut = useMutation({
 mutationFn: async (match: ConflictDetail["matches"][number]): Promise<ExistingOutcome> => {
 if (!file) throw new Error("Brak pliku CV");
 const candidateId = match.candidate_id;
 const name = `${match.name ??""} ${match.lastname ??""}`.trim() || "Kandydat";
 // Świeży odczyt karty — opis w oknie mógł powstać przed chwilą zmianą na Tablicy.
 const card = await jobCard(candidateId, job.id);
 const state = cardState(card);
 if (state === "in_progress" && card && canBeStageCv(file)) {
 // Osoba w toku (D5): nowe CV jest głównym CV i kopią przy jej zgłoszeniu.
 // Plik nazwany jak CV do klienta serwer zapisuje jako CV do klienta (15.10.2026).
 const response = await candidateStageCvApi.original.upload(card.candidate_stage_id, file);
 const data = response?.data;
 const uploaded = data?.outcome ?? "original";
 return {
 kind: uploaded === "original" ? "replaced" : uploaded,
 candidateId,
 name,
 stageName: card.stage_name,
 uploadedFilename: data?.uploaded_filename ?? null,
 };
 }
 await api.post(`/api/candidates/${candidateId}/documents`, attachCvFormData(file), {
 headers: {"Content-Type":"multipart/form-data" },
 });
 invalidateCandidateMutation(queryClient, candidateId, "document");
 if (state === "hired") return { kind: "hired", candidateId, name, stageName: card?.stage_name ?? null };
 if (state === "in_progress") return { kind: "profile_only", candidateId, name, stageName: card?.stage_name ?? null };
 const add = await addToJob(job.id, candidateId);
 if (add.kind === "added") return { kind: "added", candidateId, name };
 if (add.kind === "closed") return { kind: "closed", candidateId, name, row: add.row };
 // Karta, której odczyt nie znał (dodana w tej chwili w innym oknie):
 // CV jest w profilu, kopię przy zgłoszeniu podmienia ramka w panelu osoby.
 if (add.kind === "already") return { kind: "profile_only", candidateId, name, stageName: null };
 throw new Error(`CV jest na górze profilu, ale osoba nie trafiła do tej rekrutacji: ${add.text}`);
 },
 onSuccess: (done) => {
 invalidateCandidateMutation(queryClient, done.candidateId, "document");
 queryClient.invalidateQueries({ queryKey: ["cv-original"] });
 if (done.kind === "client_cv") {
 // CV do klienta pary: karta „CV do klienta”, dok, QC i ramka „Następny etap”.
 for (const queryKey of [["cv-branded"], ["cv-generated"], ["cv-qc"], ["cv-editor-issues"], MOVE_REQUIREMENTS_PREFIX]) {
 void queryClient.invalidateQueries({ queryKey });
 }
 }
 setOutcome(done);
 setConflict(null);
 setError(null);
 onChanged?.();
 },
 onError: (err) => {
 setError(
 err instanceof Error && err.message.startsWith("CV jest na górze profilu")
 ? err.message
 : apiErrorMessage(err, assignErrorMessage(err)),
 );
 onChanged?.();
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
 <CheckCircle2 className="h-5 w-5 text-primary" />
 <DialogTitle>Kandydat dodany</DialogTitle>
 </div>
 <DialogDescription>
 {c.name} {c.lastname} — profil utworzony z CV.
 {result.source && (
 <span className="ml-1 text-xs text-muted-foreground">
 (źródło: {result.source})
 </span>
 )}
 </DialogDescription>
 </DialogHeader>
 <DialogBody>
 {lowCount > 0 && (
 <div className="mb-3 flex items-start gap-2 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-900">
 <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
 <span>
 {lowCount}{" "}
 {lowCount === 1 ?"pole wymaga weryfikacji" :"pól wymaga weryfikacji"}{" "}
 — AI nie miało pełnej pewności. Otwórz profil żeby poprawić.
 </span>
 </div>
 )}
 <dl className="divide-y divide-border">
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
 <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Wyciągnięte technologie ({skills.length})
 </div>
 <div className="flex flex-wrap gap-1.5">
 {skills.map((s) => (
 <span
 key={s}
 className="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs text-primary"
 >
 {s}
 </span>
 ))}
 </div>
 </div>
 )}
 <NewCandidateJobLine add={newCandidateAdd} jobTitle={job.title} />
 </DialogBody>
 <DialogFooter>
 <Button variant="ghost" onClick={() => reset()}>
 Dodaj kolejnego
 </Button>
 <Button variant="outline" asChild>
 <Link href={`/candidates/${c.id}`}>Otwórz profil</Link>
 </Button>
 {onOpenPerson && typeof newCandidateAdd === "object" && newCandidateAdd?.kind === "added" ? (
 <Button
 variant="outline"
 onClick={() => {
 onOpenPerson(c.id);
 onOpenChange(false);
 }}
 >
 Otwórz w panelu
 </Button>
 ) : null}
 <Button variant="primary" onClick={() => onOpenChange(false)}>
 Zamknij
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
 }

 // ── osoba z bazy po akcji: w „Nowych”, przywrócona, CV podmienione ──────
 if (outcome) {
 if (outcome.kind === "closed") {
 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="md">
 <DialogHeader>
 <div className="flex items-center gap-2">
 <CheckCircle2 className="h-5 w-5 text-primary" />
 <DialogTitle>CV jest na górze profilu</DialogTitle>
 </div>
 <DialogDescription>
 {outcome.name} ma w tej rekrutacji zamkniętą kartę. Przywróć ją, jeśli osoba ma wrócić do procesu.
 </DialogDescription>
 </DialogHeader>
 <DialogBody>
 <ClosedCardRestore
 job={job}
 row={outcome.row}
 headline={`Karta w rekrutacji „${job.title}” jest zamknięta:`}
 onRestored={() => {
 setOutcome({ kind: "restored", candidateId: outcome.candidateId, name: outcome.name });
 onChanged?.();
 }}
 />
 </DialogBody>
 <DialogFooter>
 <Button variant="primary" onClick={() => onOpenChange(false)}>
 Zamknij
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
 }
 const fileName = file?.name ?? "CV";
 const stageSuffix = outcome.stageName ? ` · ${outcome.stageName}` : "";
 const title =
 outcome.kind === "replaced" ||
 outcome.kind === "profile_only" ||
 outcome.kind === "client_cv" ||
 outcome.kind === "client_cv_kept"
 ? `${outcome.name} jest już w tej rekrutacji${stageSuffix}`
 : outcome.kind === "hired"
 ? `CV dodane do profilu · ${outcome.name}${stageSuffix}`
 : outcome.kind === "restored"
 ? `${outcome.name} jest znowu w „Nowych”`
 : `${outcome.name} jest w „Nowych”`;
 const description =
 outcome.kind === "client_cv"
 ? `Plik ${outcome.uploadedFilename ?? fileName} jest teraz CV do klienta w tej rekrutacji. CV kandydata w profilu bez zmian.`
 : outcome.kind === "client_cv_kept"
 ? `Klient ma już CV tej osoby, więc CV do klienta zostało bez zmian. Plik ${outcome.uploadedFilename ?? fileName} jest w profilu w „CV dla klientów”.`
 : outcome.kind === "replaced"
 ? "Nowe CV jest głównym CV w profilu i zastąpiło CV przy zgłoszeniu w tej rekrutacji. AI odświeży profil za około minutę."
 : outcome.kind === "hired"
 ? "Nowe CV jest głównym CV w profilu. Ta osoba ma w tej rekrutacji kartę zatrudnienia, więc CV przy zgłoszeniu zostaje bez zmian."
 : outcome.kind === "profile_only"
 ? file && !canBeStageCv(file)
 ? "Nowe CV jest głównym CV w profilu. CV przy zgłoszeniu zostało bez zmian, bo plik TXT nie może być CV rekrutacji — wgraj PDF albo DOCX w panelu osoby."
 : "Nowe CV jest głównym CV w profilu. CV przy zgłoszeniu podmienisz w panelu osoby: „W profilu jest nowsze CV” → „Użyj w tej rekrutacji”."
 : `${fileName} jest głównym CV w profilu i CV tej rekrutacji. AI odświeży profil za około minutę.`;
 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="md">
 <DialogHeader>
 <div className="flex items-center gap-2">
 <CheckCircle2 className="h-5 w-5 text-primary" />
 <DialogTitle>{title}</DialogTitle>
 </div>
 <DialogDescription>{description}</DialogDescription>
 </DialogHeader>
 <DialogFooter>
 <Button variant="ghost" onClick={() => reset()}>
 Dodaj kolejne CV
 </Button>
 {onOpenPerson ? (
 <Button
 variant="outline"
 onClick={() => {
 onOpenPerson(outcome.candidateId);
 onOpenChange(false);
 }}
 >
 Otwórz w panelu
 </Button>
 ) : null}
 <Button variant="primary" onClick={() => onOpenChange(false)}>
 Zamknij
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
 }

 // ── conflict view: ta osoba (albo ten plik) już jest w bazie ───────────
 if (conflict) {
 const top = conflict.matches[0];
 const sameFile = isSameFileMatch(top);
 const samePhone = isPhoneAndNameMatch(top);
 const fullName = `${top.name ??""} ${top.lastname ??""}`.trim() || "Kandydat";
 const initials = `${top.name?.[0] ??""}${top.lastname?.[0] ??""}`.toUpperCase() || "?";
 const card = typeof existingCard === "object" ? existingCard : null;
 const state = cardState(card);
 const primaryLabel =
 state === "in_progress"
 ? "Podmień CV w tej rekrutacji"
 : state === "hired"
 ? "Dodaj CV do profilu"
 : sameFile
 ? "Dodaj do rekrutacji"
 : "Dodaj do rekrutacji z tym CV";
 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="md">
 <DialogHeader>
 <div className="flex items-center gap-2">
 <UserCheck className="h-5 w-5 text-warning" />
 <DialogTitle>{fullName} już jest w bazie</DialogTitle>
 </div>
 <DialogDescription>
 {sameFile
 ?"Ten plik leży już w profilu tej osoby, więc nie zakładamy drugiego profilu."
 : samePhone
 ?"Ten sam telefon oraz imię i nazwisko co w CV, więc nie zakładamy drugiego profilu."
 :"Ten sam adres e-mail co w CV, więc nie zakładamy drugiego profilu."}
 </DialogDescription>
 </DialogHeader>
 <DialogBody>
 <div className="space-y-3">
 <div className="flex items-center gap-3 rounded-lg border border-border p-3">
 <span
 aria-hidden
 className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
 >
 {initials}
 </span>
 <div className="min-w-0 flex-1">
 <p className="font-medium text-foreground">{fullName}</p>
 {top.email ? <p className="break-words text-xs text-muted-foreground">{top.email}</p> : null}
 </div>
 <Link
 href={`/candidates/${top.candidate_id}`}
 target="_blank"
 rel="noopener"
 className="shrink-0 text-xs font-medium text-primary hover:underline"
 >
 Otwórz profil ↗
 </Link>
 </div>
 <ul className="space-y-1.5 text-sm" aria-label="Co się stanie">
 <li className="flex items-start gap-2">
 <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
 <span>
 {sameFile
 ?"Ten plik stanie się głównym CV w profilu."
 :"CV trafi na górę profilu jako główne, AI odświeży profil."}
 </span>
 </li>
 <li className="flex items-start gap-2">
 {existingCard === "loading" ? (
 <>
 <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
 <span className="text-muted-foreground">Sprawdzam, czy ta osoba jest już w tej rekrutacji…</span>
 </>
 ) : (
 <>
 <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
 <span>
 {state === "in_progress"
 ? `Jest już w tej rekrutacji (${card?.stage_name ?? "w toku"}) — nowe CV zastąpi CV przy zgłoszeniu.`
 : state === "hired"
 ? `Ma w tej rekrutacji kartę zatrudnienia (${card?.stage_name ?? "zatrudniony"}) — CV trafi tylko do profilu.`
 : state === "closed"
 ? `Ma w tej rekrutacji zamkniętą kartę (${card?.stage_name ?? "zamknięta"}) — po dodaniu CV zdecydujesz, czy ją przywrócić.`
 : `Trafi do „Nowych” w rekrutacji ${job.title}.`}
 </span>
 </>
 )}
 </li>
 </ul>
 {sameFile || samePhone ? (
 <button
 type="button"
 className="text-xs font-medium text-primary hover:underline disabled:opacity-50"
 disabled={uploadMut.isPending || existingMut.isPending}
 onClick={() => handleUpload(true)}
 >
 {sameFile ?"To CV innej osoby? Załóż osobny profil" :"To inna osoba? Załóż osobny profil"}
 </button>
 ) : null}
 {error && (
 <p role="alert" className="text-sm text-destructive">
 {error}
 </p>
 )}
 </div>
 </DialogBody>
 <DialogFooter>
 <Button
 variant="ghost"
 onClick={() => {
 setConflict(null);
 setExistingCard(null);
 setError(null);
 }}
 >
 Anuluj
 </Button>
 <Button
 variant="primary"
 loading={existingMut.isPending}
 disabled={existingMut.isPending || uploadMut.isPending}
 onClick={() => existingMut.mutate(top)}
 >
 <Upload className="h-4 w-4" /> {primaryLabel}
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
 <Sparkles className="h-4 w-4 text-primary" />
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
 if (e.key === "Enter" || e.key === " ") {
 e.preventDefault();
 fileInputRef.current?.click();
 }
 }}
 className={cn("cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors",
 dragOver
 ?"border-primary bg-primary/10"
 :"border-border hover:border-primary/60 hover:bg-background/40"
 )}
 >
 <FileUp className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
 {file ? (
 <div>
 <div className="text-sm font-medium text-foreground">
 {file.name}
 </div>
 <div className="text-xs text-muted-foreground">
 {(file.size / 1024).toFixed(1)} KB
 </div>
 </div>
 ) : (
 <div>
 <div className="text-sm font-medium text-foreground">
 Przeciągnij CV lub kliknij
 </div>
 <div className="text-xs text-muted-foreground mt-1">
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
 className="mt-3 inline-flex items-center gap-2 text-sm text-primary bg-primary/10 px-3 py-2 rounded-md w-full"
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

/** Nowy kandydat z CV: czy trafił do „Nowych” tej rekrutacji. */
function NewCandidateJobLine({
 add,
 jobTitle,
}: {
 add: JobAdd | "pending" | "failed" | null;
 jobTitle: string;
}) {
 if (add == null) return null;
 if (add === "pending") {
 return (
 <p className="mt-3 flex items-center gap-1.5 text-sm text-muted-foreground">
 <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Dodaję do „Nowych” w tej rekrutacji…
 </p>
 );
 }
 if (add === "failed") {
 return (
 <p role="alert" className="mt-3 text-sm text-destructive">
 Profil powstał, ale nie udało się dodać osoby do tej rekrutacji. Dodaj ją przez „Dodaj kandydatów”.
 </p>
 );
 }
 if (add.kind === "added") {
 return (
 <p className="mt-3 flex items-center gap-1.5 text-sm text-foreground">
 <Check className="h-4 w-4 text-success" aria-hidden /> Osoba jest w „Nowych” w rekrutacji {jobTitle}.
 </p>
 );
 }
 const reason =
 add.kind === "skipped" ? add.text : add.kind === "closed" ? add.row.reason_label ?? "zamknięta karta" : add.label ?? "już w rekrutacji";
 return (
 <p role="alert" className="mt-3 text-sm text-destructive">
 Kandydat jest w bazie, ale nie trafił do tej rekrutacji: {reason}.
 </p>
 );
}
