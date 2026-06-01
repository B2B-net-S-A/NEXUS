"use client";

import * as React from"react";
import { useRef, useState } from"react";
import Link from"next/link";
import type { AxiosError } from"axios";
import {
 AlertTriangle,
 ArrowLeft,
 CheckCircle2,
 FileUp,
 Loader2,
 Upload,
 UserCheck,
 XCircle,
} from"lucide-react";
import api from"@/lib/api";
import { cn } from"@/lib/utils";
import { Button } from"@/components/ui/button";
import { useQueryClient } from"@tanstack/react-query";

/**
 * Per-file upload state shown in the progress table.
 *
 * pending – queued, not started yet
 * parsing – POST in flight
 * success – 201 response, candidate created (id + name stored)
 * duplicate – 409 response, existing candidate found (id stored so UI links)
 * error – any other failure, message stored for display
 */
type Status ="pending" |"parsing" |"success" |"duplicate" |"error";

interface Row {
 id: string; // uuid-ish, stable across renders
 file: File;
 status: Status;
 candidateId?: number;
 candidateName?: string;
 lowConfidenceCount?: number;
 error?: string;
 duplicateOfId?: number;
 duplicateOfName?: string;
}

/** Batch size for parallel uploads – keeps Voyage + Claude APIs responsive. */
const CONCURRENCY = 3;
const ALLOWED_EXT = [".pdf",".docx",".txt"];
const LOW_CONFIDENCE = 0.7;

function newId(): string {
 // crypto.randomUUID is available in all supported browsers/Node 18+.
 if (typeof crypto !== "undefined" &&"randomUUID" in crypto) {
 return crypto.randomUUID();
 }
 return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isAllowed(f: File): boolean {
 const lower = f.name.toLowerCase();
 return ALLOWED_EXT.some((ext) => lower.endsWith(ext));
}

function StatusBadge({ status }: { status: Status }) {
 const config: Record<
 Status,
 { label: string; className: string; icon: React.ReactNode }
 > = {
 pending: {
 label: "W kolejce",
 className: "bg-[hsl(var(--border))]/40 text-muted-foreground",
 icon: null,
 },
 parsing: {
 label: "Parsowanie…",
 className: "bg-primary/10 text-primary",
 icon: <Loader2 className="h-3 w-3 animate-spin" />,
 },
 success: {
 label: "Dodano",
 className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
 icon: <CheckCircle2 className="h-3 w-3" />,
 },
 duplicate: {
 label: "Duplikat",
 className: "bg-amber-50 text-amber-800 border border-amber-200",
 icon: <UserCheck className="h-3 w-3" />,
 },
 error: {
 label: "Błąd",
 className: "bg-destructive/10 text-destructive border border-destructive/20",
 icon: <XCircle className="h-3 w-3" />,
 },
 };
 const c = config[status];
 return (
 <span
 className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
 c.className
 )}
 >
 {c.icon}
 {c.label}
 </span>
 );
}

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

async function uploadOne(row: Row): Promise<Partial<Row>> {
 const fd = new FormData();
 fd.append("file", row.file);
 try {
 const r = await api.post<{
 candidate: {
 id: number;
 name: string;
 lastname: string;
 };
 confidence: Record<string, number>;
 }>("/api/candidates/from-cv", fd, {
 headers: {"Content-Type":"multipart/form-data" },
 });
 const low = Object.values(r.data.confidence || {}).filter(
 (v) => typeof v === "number" && v < LOW_CONFIDENCE
 ).length;
 return {
 status: "success",
 candidateId: r.data.candidate.id,
 candidateName: `${r.data.candidate.name} ${r.data.candidate.lastname}`,
 lowConfidenceCount: low,
 };
 } catch (err) {
 const axiosErr = err as AxiosError<{ detail?: ConflictDetail | string }>;
 if (axiosErr.response?.status === 409) {
 const detail = axiosErr.response.data?.detail;
 if (detail && typeof detail === "object" &&"existing_candidate_id" in detail) {
 const top = detail.matches?.[0];
 return {
 status: "duplicate",
 duplicateOfId: detail.existing_candidate_id,
 duplicateOfName: top
 ? `${top.name ??""} ${top.lastname ??""}`.trim()
 : undefined,
 };
 }
 }
 const msg =
 typeof axiosErr.response?.data?.detail === "string"
 ? axiosErr.response.data.detail
 : axiosErr.message ||"Nie udało się przetworzyć pliku.";
 return { status: "error", error: msg };
 }
}

export function BulkImportCVsV2() {
 const queryClient = useQueryClient();
 const fileInputRef = useRef<HTMLInputElement>(null);
 const [dragOver, setDragOver] = useState(false);
 const [rows, setRows] = useState<Row[]>([]);
 const [running, setRunning] = useState(false);

 const addFiles = (files: File[]) => {
 const allowed = files.filter(isAllowed);
 const rejected = files.length - allowed.length;
 const next = allowed.map<Row>((f) => ({
 id: newId(),
 file: f,
 status: "pending",
 }));
 setRows((prev) => [...prev, ...next]);
 if (rejected > 0) {
 // Cheap inline alert via a single error row – keeps UI simple.
 setRows((prev) => [
 ...prev,
 {
 id: newId(),
 file: new File([], `(pominięto ${rejected} plików o nieobsługiwanym formacie)`),
 status: "error",
 error: `Dozwolone: ${ALLOWED_EXT.join(",")}`,
 },
 ]);
 }
 };

 const runUploads = async () => {
 if (running) return;
 setRunning(true);
 try {
 // Process in batches of CONCURRENCY. Each batch awaits before starting
 // the next – this keeps DB + LLM pressure bounded and gives steady UI
 // updates.
 const queue = rows
 .filter((r) => r.status === "pending")
 .map((r) => r.id);
 for (let i = 0; i < queue.length; i += CONCURRENCY) {
 const batchIds = queue.slice(i, i + CONCURRENCY);

 // Flip the whole batch to"parsing" up-front so the user sees
 // activity across all slots, not just the first.
 setRows((prev) =>
 prev.map((r) =>
 batchIds.includes(r.id) ? { ...r, status: "parsing" } : r
 )
 );

 const batchRows = batchIds
 .map((id) => rows.find((r) => r.id === id))
 .filter((r): r is Row => Boolean(r));

 const results = await Promise.all(
 batchRows.map(async (r) => ({
 id: r.id,
 patch: await uploadOne(r),
 }))
 );

 setRows((prev) =>
 prev.map((r) => {
 const hit = results.find((x) => x.id === r.id);
 return hit ? { ...r, ...hit.patch } : r;
 })
 );
 }
 // Refresh list + detail queries so the newly-added candidates appear
 // immediately elsewhere in the app.
 queryClient.invalidateQueries({ queryKey: ["candidates"] });
 queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 } finally {
 setRunning(false);
 }
 };

 const removeRow = (id: string) =>
 setRows((prev) => prev.filter((r) => r.id !== id));

 const clearAll = () => setRows([]);

 const summary = React.useMemo(() => {
 let success = 0;
 let duplicate = 0;
 let error = 0;
 let pending = 0;
 for (const r of rows) {
 if (r.status === "success") success += 1;
 else if (r.status === "duplicate") duplicate += 1;
 else if (r.status === "error") error += 1;
 else pending += 1;
 }
 return { success, duplicate, error, pending, total: rows.length };
 }, [rows]);

 const anyPending = summary.pending > 0;

 return (
 <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
 <div className="flex items-center justify-between">
 <div>
 <Link
 href="/candidates"
 className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
 >
 <ArrowLeft className="h-4 w-4" /> Wróć do listy kandydatów
 </Link>
 <h1 className="mt-2 text-2xl font-semibold text-foreground">
 Bulk import CV
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Wrzuć wiele PDF/DOCX naraz – każdy plik trafia do osobnego kandydata.
 Duplikaty są wyłapywane po emailu / telefonie / LinkedIn.
 </p>
 </div>
 </div>

 <div
 onDragOver={(e) => {
 e.preventDefault();
 setDragOver(true);
 }}
 onDragLeave={() => setDragOver(false)}
 onDrop={(e) => {
 e.preventDefault();
 setDragOver(false);
 addFiles(Array.from(e.dataTransfer.files || []));
 }}
 onClick={() => fileInputRef.current?.click()}
 role="button"
 tabIndex={0}
 onKeyDown={(e) => {
 if (e.key === "Enter" || e.key === "") fileInputRef.current?.click();
 }}
 className={cn("cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition-colors",
 dragOver
 ?"border-primary bg-primary/10"
 :"border-border hover:border-primary/60 hover:bg-background/40"
 )}
 >
 <FileUp className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
 <div className="text-sm font-medium text-foreground">
 Przeciągnij wiele plików CV lub kliknij żeby wybrać
 </div>
 <div className="text-xs text-muted-foreground mt-1">
 PDF · DOCX · TXT · parsowane równolegle po {CONCURRENCY}
 </div>
 <input
 ref={fileInputRef}
 type="file"
 multiple
 accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
 hidden
 onChange={(e) => {
 addFiles(Array.from(e.target.files || []));
 e.target.value ="";
 }}
 />
 </div>

 {rows.length > 0 && (
 <div className="space-y-3">
 <div className="flex items-center justify-between">
 <div className="flex items-center gap-2 text-sm text-muted-foreground">
 <span>
 Łącznie: <strong>{summary.total}</strong>
 </span>
 {summary.success > 0 && (
 <span className="text-emerald-700">
 · Dodano: <strong>{summary.success}</strong>
 </span>
 )}
 {summary.duplicate > 0 && (
 <span className="text-amber-700">
 · Duplikaty: <strong>{summary.duplicate}</strong>
 </span>
 )}
 {summary.error > 0 && (
 <span className="text-destructive">
 · Błędy: <strong>{summary.error}</strong>
 </span>
 )}
 {summary.pending > 0 && (
 <span>
 · W kolejce: <strong>{summary.pending}</strong>
 </span>
 )}
 </div>
 <div className="flex items-center gap-2">
 <Button
 size="sm"
 variant="ghost"
 onClick={clearAll}
 disabled={running}
 >
 Wyczyść listę
 </Button>
 <Button
 size="sm"
 variant="primary"
 onClick={runUploads}
 disabled={!anyPending || running}
 loading={running}
 >
 <Upload className="h-4 w-4" />
 {running
 ?"Parsowanie…"
 : anyPending
 ? `Parsuj ${summary.pending} plików`
 :"Brak plików w kolejce"}
 </Button>
 </div>
 </div>

 <div className="overflow-hidden rounded-lg border border-border">
 <table className="w-full text-sm">
 <thead className="bg-background/40">
 <tr className="text-left text-xs uppercase tracking-[0.08em] text-muted-foreground">
 <th className="px-4 py-2 font-semibold">Plik</th>
 <th className="px-4 py-2 font-semibold">Status</th>
 <th className="px-4 py-2 font-semibold">Kandydat</th>
 <th className="px-4 py-2 font-semibold">Uwagi</th>
 <th className="px-4 py-2 font-semibold"></th>
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {rows.map((r) => (
 <tr key={r.id} className="align-top">
 <td className="px-4 py-2">
 <div className="font-medium text-foreground">
 {r.file.name}
 </div>
 {r.file.size > 0 && (
 <div className="text-[11px] text-muted-foreground">
 {(r.file.size / 1024).toFixed(1)} KB
 </div>
 )}
 </td>
 <td className="px-4 py-2">
 <StatusBadge status={r.status} />
 </td>
 <td className="px-4 py-2">
 {r.status === "success" && r.candidateId && (
 <Link
 href={`/candidates/${r.candidateId}`}
 className="text-primary hover:underline"
 >
 {r.candidateName}
 </Link>
 )}
 {r.status === "duplicate" && r.duplicateOfId && (
 <Link
 href={`/candidates/${r.duplicateOfId}`}
 className="text-amber-700 hover:underline"
 >
 {r.duplicateOfName || `#${r.duplicateOfId}`}
 </Link>
 )}
 </td>
 <td className="px-4 py-2 text-muted-foreground">
 {r.status === "success" &&
 typeof r.lowConfidenceCount === "number" &&
 r.lowConfidenceCount > 0 ? (
 <span className="inline-flex items-center gap-1 text-amber-700">
 <AlertTriangle className="h-3 w-3" />
 {r.lowConfidenceCount} pól do weryfikacji
 </span>
 ) : null}
 {r.status === "error" && r.error ? (
 <span className="text-destructive">{r.error}</span>
 ) : null}
 </td>
 <td className="px-4 py-2 text-right">
 {r.status === "pending" && !running && (
 <button
 type="button"
 onClick={() => removeRow(r.id)}
 className="text-[11px] text-muted-foreground hover:text-destructive"
 >
 Usuń
 </button>
 )}
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 </div>
 )}
 </div>
 );
}
