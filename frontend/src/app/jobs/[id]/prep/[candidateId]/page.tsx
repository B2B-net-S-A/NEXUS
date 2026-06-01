"use client";

import { useEffect, useMemo, useState } from"react";
import Link from"next/link";
import { useParams, useRouter } from"next/navigation";
import {
 Card,
 CardTitle,
 CardDescription,
 Badge,
 Button,
} from"@/components/ui";
import { QuestionCard } from"@/components/prep/QuestionCard";
import {
 interviewQuestionsApi,
 prepKitApi,
 type SuggestedQuestion,
 type PrepKitResponse,
} from"@/lib/api";

type LoadState ="idle" |"loading" |"ready" |"error";

export default function PrepPage() {
 const params = useParams<{ id: string; candidateId: string }>();
 const router = useRouter();
 const jobId = Number(params.id);
 const candidateId = Number(params.candidateId);

 const [state, setState] = useState<LoadState>("idle");
 const [prepKit, setPrepKit] = useState<PrepKitResponse | null>(null);
 const [suggestions, setSuggestions] = useState<SuggestedQuestion[]>([]);
 const [error, setError] = useState<string | null>(null);

 const load = async () => {
 setState("loading");
 setError(null);
 try {
 const [kitRes, suggRes] = await Promise.all([
 prepKitApi.generate(jobId, candidateId),
 interviewQuestionsApi.suggestedForJob(jobId, {
 candidate_id: candidateId,
 target_count: 15,
 }),
 ]);
 setPrepKit(kitRes.data);
 setSuggestions(suggRes.data);
 setState("ready");
 } catch (err) {
 const message =
 err instanceof Error ? err.message : "Błąd wczytywania prep-kita";
 setError(message);
 setState("error");
 }
 };

 useEffect(() => {
 if (Number.isFinite(jobId) && Number.isFinite(candidateId)) {
 void load();
 }
 // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [jobId, candidateId]);

 const pinnedOrLegacy = useMemo(
 () =>
 suggestions.filter(
 (s) =>
 s.source_tier === "pinned" || s.source_tier === "legacy_champion",
 ),
 [suggestions],
 );

 const suggested = useMemo(
 () =>
 suggestions.filter(
 (s) =>
 s.source_tier !== "pinned" && s.source_tier !== "legacy_champion",
 ),
 [suggestions],
 );

 if (!Number.isFinite(jobId) || !Number.isFinite(candidateId)) {
 return (
 <div className="p-6 max-w-3xl mx-auto">
 <Card variant="default" size="md">
 <CardTitle>Nieprawidłowe parametry URL</CardTitle>
 <CardDescription>
 Brak job_id lub candidate_id – wróć do listy kandydatów.
 </CardDescription>
 </Card>
 </div>
 );
 }

 return (
 <div className="p-6 max-w-5xl mx-auto print:p-4 print:max-w-none">
 <header className="flex items-start justify-between gap-4 mb-6 print:mb-4">
 <div>
 <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
 Przygotowanie do rozmowy
 </p>
 <h1 className="text-2xl font-bold text-foreground">
 Prep kit · Job #{jobId} · Kandydat #{candidateId}
 </h1>
 </div>
 <div className="flex items-center gap-2 print:hidden">
 <Button
 variant="outline"
 size="sm"
 onClick={() => window.print()}
 >
 🖨️ Drukuj
 </Button>
 <Button
 variant="ghost"
 size="sm"
 onClick={() => router.push(`/jobs/${jobId}`)}
 >
 ← Projekt
 </Button>
 </div>
 </header>

 {state === "loading" && (
 <Card variant="default" size="md">
 <CardDescription>Wczytywanie prep-kita…</CardDescription>
 </Card>
 )}

 {state === "error" && (
 <Card variant="default" size="md">
 <CardTitle>Nie udało się wczytać prep-kita</CardTitle>
 <CardDescription>{error}</CardDescription>
 <div className="mt-3 print:hidden">
 <Button variant="primary" size="sm" onClick={() => void load()}>
 Spróbuj ponownie
 </Button>
 </div>
 </Card>
 )}

 {state === "ready" && prepKit && (
 <div className="grid gap-4">
 {/* Client overview */}
 <Card variant="default" size="md">
 <CardTitle>Klient / Projekt</CardTitle>
 <p className="mt-2 whitespace-pre-wrap text-foreground leading-relaxed">
 {prepKit.client_overview}
 </p>
 </Card>

 {/* Candidate strengths + gaps – grid */}
 <div className="grid grid-cols-1 md:grid-cols-2 gap-4 print:grid-cols-2">
 <Card variant="default" size="md">
 <CardTitle>Mocne strony kandydata</CardTitle>
 <ul className="mt-2 space-y-1 list-disc list-inside text-foreground">
 {prepKit.candidate_strengths.map((s, i) => (
 <li key={i}>{s}</li>
 ))}
 </ul>
 </Card>
 <Card variant="default" size="md">
 <CardTitle>Potencjalne luki</CardTitle>
 <ul className="mt-2 space-y-1 list-disc list-inside text-foreground">
 {prepKit.candidate_gaps.map((g, i) => (
 <li key={i}>{g}</li>
 ))}
 </ul>
 </Card>
 </div>

 {/* Selling points */}
 <Card variant="default" size="md">
 <CardTitle>Argumenty sprzedażowe</CardTitle>
 <ul className="mt-2 space-y-1 list-disc list-inside text-foreground">
 {prepKit.selling_points.map((s, i) => (
 <li key={i}>{s}</li>
 ))}
 </ul>
 </Card>

 {/* Recommended strategy */}
 <Card variant="default" size="md">
 <CardTitle>Strategia rozmowy</CardTitle>
 <p className="mt-2 text-foreground leading-relaxed">
 {prepKit.recommended_strategy}
 </p>
 </Card>

 {/* Pinned / legacy questions */}
 <section>
 <h2 className="text-xl font-bold text-foreground mb-3">
 Pytania do kandydata
 </h2>

 {pinnedOrLegacy.length > 0 && (
 <div className="grid gap-3 mb-4">
 {pinnedOrLegacy.map((q, i) => (
 <QuestionCard
 key={`pin-${q.question_id ?? i}-${q.text.slice(0, 20)}`}
 question={q}
 jobId={jobId}
 candidateId={candidateId}
 onRated={() => void load()}
 />
 ))}
 </div>
 )}

 {suggested.length > 0 && (
 <>
 <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-2 print:mt-4">
 Podpowiedzi (z podobnych projektów / auto-generowane)
 </h3>
 <div className="grid gap-3">
 {suggested.map((q, i) => (
 <QuestionCard
 key={`sugg-${q.question_id ?? i}-${q.text.slice(0, 20)}`}
 question={q}
 jobId={jobId}
 candidateId={candidateId}
 onPin={() => void load()}
 onRated={() => void load()}
 />
 ))}
 </div>
 </>
 )}

 {pinnedOrLegacy.length === 0 && suggested.length === 0 && (
 <Card variant="default" size="md">
 <CardDescription>
 Brak pytań dla tego projektu. Dodaj pytania na{""}
 <Link
 href={`/jobs/${jobId}?tab=questions`}
 className="text-primary underline"
 >
 zakładce Baza pytań
 </Link>
 .
 </CardDescription>
 </Card>
 )}
 </section>

 <div className="flex items-center gap-2 text-xs text-muted-foreground mt-4 print:hidden">
 <Badge variant="neutral" size="sm">
 {suggestions.length} pytań łącznie
 </Badge>
 <span>Źródła: przypięte → podobne projekty → auto-gen</span>
 </div>
 </div>
 )}
 </div>
 );
}
