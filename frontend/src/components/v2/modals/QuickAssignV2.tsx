"use client";

import * as React from"react";
import { useEffect, useState } from"react";
import { AlertTriangle, Briefcase, CheckCircle2, Search, Sparkles } from"lucide-react";
import api, {
 recommendationsApi,
 type JobMatch,
 type RecommendationMeta,
} from"@/lib/api";
import {
 Sheet,
 SheetBody,
 SheetContent,
 SheetDescription,
 SheetFooter,
 SheetHeader,
 SheetTitle,
} from"@/components/ui/sheet";
import { Button } from"@/components/ui/button";
import { Badge } from"@/components/ui/badge";
import { Input } from"@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from"@/components/ui/tabs";
import { RiskBadge } from"@/components/v2/RiskBadge";
import type { CandidateRiskProfile } from"@/types/candidate-risk";

interface JobLite {
 id: number;
 title: string;
 location?: string | null;
 seniority?: string | null;
 status?: string;
}

function scoreVariant(
 score: number
): "success" |"soft" |"warning" |"neutral" {
 if (score >= 75) return"success";
 if (score >= 60) return"soft";
 if (score >= 40) return"warning";
 return"neutral";
}

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 candidateId: number;
 candidateName: string;
 onAssigned?: (jobId: number) => void;
}

export function QuickAssignV2({
 open,
 onOpenChange,
 candidateId,
 candidateName,
 onAssigned,
}: Props) {
 const [matches, setMatches] = useState<JobMatch[]>([]);
 const [recommendationMeta, setRecommendationMeta] =
 useState<RecommendationMeta | null>(null);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [assigning, setAssigning] = useState<number | null>(null);
 const [assignedIds, setAssignedIds] = useState<Set<number>>(new Set());
 // Phase 17 (migracja 0068): risk profile dla ostrzeżenia przy assign'ie.
 const [risk, setRisk] = useState<CandidateRiskProfile | null>(null);
 // "AI sugestie" (domyślny) vs "Wszystkie" — pozwala przypisać do dowolnej rekrutacji.
 const [tab, setTab] = useState<"ai" |"all">("ai");
 const [searchQuery, setSearchQuery] = useState("");
 const [allJobs, setAllJobs] = useState<JobLite[]>([]);
 const [allLoading, setAllLoading] = useState(false);
 const [allError, setAllError] = useState<string | null>(null);

 useEffect(() => {
 if (!open) return;
 let cancelled = false;
 const load = async () => {
 setLoading(true);
 setError(null);
 try {
 const [matchRes, riskRes] = await Promise.all([
 recommendationsApi.forCandidate(candidateId, {
 top_k: 10,
 include_breakdown: true,
 }),
 api
 .get<CandidateRiskProfile>(`/api/candidates/${candidateId}/risk`)
 .catch(() => null),
 ]);
 if (cancelled) return;
 setMatches(matchRes.data.matches);
 setRecommendationMeta(matchRes.data.meta ?? null);
 setRisk(riskRes?.data ?? null);
 } catch (e: unknown) {
 if (cancelled) return;
 const msg =
 e && typeof e === "object" &&"response" in e
 ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??"Błąd") : "Błąd";
 setError(msg);
 } finally {
 if (!cancelled) setLoading(false);
 }
 };
 load();
 return () => {
 cancelled = true;
 };
 }, [candidateId, open]);

 // Reset state otwarcia/zamknięcia — żeby search query nie został z poprzedniego kandydata.
 useEffect(() => {
 if (!open) {
 setTab("ai");
 setSearchQuery("");
 setAllJobs([]);
 setAllError(null);
 setAssignedIds(new Set());
 }
 }, [open]);

 // Debounced fetch wszystkich aktywnych rekrutacji (status=published).
 useEffect(() => {
 if (!open || tab !=="all") return;
 const ctrl = new AbortController();
 const timer = setTimeout(async () => {
 setAllLoading(true);
 setAllError(null);
 try {
 const res = await api.get("/api/jobs", {
 params: {
 status:"published",
 page_size: 50,
 ...(searchQuery.trim() ? { q: searchQuery.trim() } : {}),
 },
 signal: ctrl.signal,
 });
 const data = res.data;
 const items: JobLite[] = Array.isArray(data)
 ? data
 : (data.items ?? []);
 setAllJobs(items);
 } catch (e: unknown) {
 if ((e as { name?: string })?.name ==="CanceledError") return;
 const msg =
 e && typeof e === "object" &&"response" in e
 ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??"Nie udało się załadować rekrutacji") : "Nie udało się załadować rekrutacji";
 setAllError(msg);
 } finally {
 setAllLoading(false);
 }
 }, 250);
 return () => {
 ctrl.abort();
 clearTimeout(timer);
 };
 }, [open, tab, searchQuery]);

 const handleAssign = async (jobId: number) => {
 setAssigning(jobId);
 try {
 await recommendationsApi.assignToJob(candidateId, jobId);
 setAssignedIds((prev) => new Set(prev).add(jobId));
 onAssigned?.(jobId);
 } finally {
 setAssigning(null);
 }
 };

 const renderJobRow = (job: {
 id: number;
 title?: string | null;
 location?: string | null;
 seniority?: string | null;
 }, score?: number | null) => {
 const jobId = job.id;
 const assigned = assignedIds.has(jobId);
 const isAssigning = assigning === jobId;
 return (
 <div
 key={jobId}
 className="flex items-start gap-3 p-3 rounded-lg border border-border hover:border-primary/40 transition-colors"
 >
 <div className="flex-1 min-w-0">
 <div className="flex items-center gap-2 flex-wrap">
 <span className="font-medium text-sm text-foreground truncate">
 {job.title ?? `Oferta #${jobId}`}
 </span>
 {typeof score === "number" && (
 <Badge variant={scoreVariant(score)} size="sm">
 {Math.round(score)}%
 </Badge>
 )}
 {score === null && (
 <Badge variant="neutral" size="sm">
 BM25 · tryb awaryjny
 </Badge>
 )}
 </div>
 {job.location && (
 <div className="text-xs text-muted-foreground mt-0.5">
 {job.location}
 {job.seniority ? ` · ${job.seniority}` :""}
 </div>
 )}
 </div>
 {assigned ? (
 <span className="inline-flex items-center gap-1 text-xs font-medium text-[#1d5e31] shrink-0">
 <CheckCircle2 className="h-3.5 w-3.5" /> Przypisano
 </span>
 ) : (
 <Button
 size="sm"
 variant="outline"
 onClick={() => handleAssign(jobId)}
 loading={isAssigning}
 >
 Przypisz
 </Button>
 )}
 </div>
 );
 };

 return (
 <Sheet open={open} onOpenChange={onOpenChange}>
 <SheetContent side="right" size="md">
 <SheetHeader>
 <div className="flex items-center gap-2">
 <Sparkles className="h-4 w-4 text-primary" />
 <SheetTitle>Przypisz do rekrutacji</SheetTitle>
 </div>
 <SheetDescription>
 Wybierz rekrutację dla <strong>{candidateName}</strong>.
 </SheetDescription>
 {risk && <RiskBadge profile={risk} className="mt-2" />}
 </SheetHeader>

 <SheetBody>
 {risk?.level === "high" && (
 <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
 <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
 <div>
 <strong>Wysokie ryzyko wycofania.</strong> Kandydat ma{""}
 {risk.breakdown.early +
 risk.breakdown.interview +
 risk.breakdown.post_accept}{""}
 wycofań w 24mc
 {risk.breakdown.post_accept > 0 &&
 `, w tym ${risk.breakdown.post_accept}× po akceptacji oferty`}
 . Decyzja należy do Ciebie — system tylko ostrzega.
 </div>
 </div>
 )}

 <Tabs value={tab} onValueChange={(v) => setTab(v as"ai" |"all")}>
 <TabsList className="w-full">
 <TabsTrigger value="ai" className="flex-1 justify-center">
 <Sparkles className="h-3.5 w-3.5" />
 AI sugestie
 </TabsTrigger>
 <TabsTrigger value="all" className="flex-1 justify-center">
 <Briefcase className="h-3.5 w-3.5" />
 Wszystkie
 </TabsTrigger>
 </TabsList>

 <TabsContent value="ai">
 {recommendationMeta?.degraded && (
 <div className="mb-3 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
 Ranking awaryjny BM25 — bez standardowego wyniku dopasowania.
 </div>
 )}
 {loading ? (
 <div className="text-sm text-muted-foreground py-8 text-center">
 Analizuję dopasowania…
 </div>
 ) : error ? (
 <div className="text-sm text-primary bg-primary/10 px-3 py-2 rounded-md">
 {error}
 </div>
 ) : matches.length === 0 ? (
 <div className="text-sm text-muted-foreground py-8 text-center">
 <Briefcase className="h-10 w-10 mx-auto mb-2 opacity-40" />
 Brak pasujących ofert. Upewnij się, że CV kandydata zostało wgrane.
 </div>
 ) : (
 <div className="space-y-2">
 {matches.map((m) => renderJobRow(m.job, m.total_score))}
 </div>
 )}
 </TabsContent>

 <TabsContent value="all">
 <div className="space-y-3">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po tytule rekrutacji…"
 value={searchQuery}
 onChange={(e) => setSearchQuery(e.target.value)}
 autoFocus
 />
 {allLoading ? (
 <div className="text-sm text-muted-foreground py-8 text-center">
 Ładuję rekrutacje…
 </div>
 ) : allError ? (
 <div className="text-sm text-primary bg-primary/10 px-3 py-2 rounded-md">
 {allError}
 </div>
 ) : allJobs.length === 0 ? (
 <div className="text-sm text-muted-foreground py-8 text-center">
 <Briefcase className="h-10 w-10 mx-auto mb-2 opacity-40" />
 {searchQuery.trim()
 ?"Brak rekrutacji pasujących do zapytania." :"Brak aktywnych rekrutacji."}
 </div>
 ) : (
 <div className="space-y-2">
 {allJobs.map((j) => renderJobRow(j))}
 </div>
 )}
 </div>
 </TabsContent>
 </Tabs>
 </SheetBody>

 <SheetFooter>
 <Button variant="ghost" onClick={() => onOpenChange(false)}>
 Zamknij
 </Button>
 </SheetFooter>
 </SheetContent>
 </Sheet>
 );
}
