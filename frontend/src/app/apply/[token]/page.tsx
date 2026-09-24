/**
 * Public candidate apply page — served at /apply/{token}.
 *
 * Renders hero + ApplyForm when the token is valid. On any error (expired,
 * revoked, unknown) we `notFound()` which renders not-found.tsx.
 */
import { notFound } from"next/navigation";
import { Calendar, MapPin, Sparkles } from"lucide-react";
import ApplyForm from"./ApplyForm";
import { forwardedClientHeaders } from "@/lib/server-forwarded";

interface PageProps {
 params: Promise<{ token: string }>;
}

interface ApplyMeta {
 recruiter: { first_name: string };
 job: {
 title: string;
 location: string | null;
 seniority: string | null;
 remote_policy: string | null;
 };
 expires_at: string;
}

function apiBase(): string {
 return (
 process.env.INTERNAL_API_URL ||
 process.env.NEXT_PUBLIC_API_URL ||"http://localhost:8000"
 );
}

/**
 * FE-N01 (audyt 22.09 r2): tylko 404/410 znaczą „link nieważny”. 429 i 5xx
 * to chwilowa awaria — rzucamy (granica błędu), zamiast wyrzucać kandydata
 * na „nie znaleziono” z ważnym linkiem.
 */
async function fetchMeta(token: string): Promise<ApplyMeta | null> {
 const url = `${apiBase()}/api/public/apply/${token}`;
 let res: Response;
 try {
 res = await fetch(url, {
 cache: "no-store",
 headers: await forwardedClientHeaders(),
 });
 } catch {
 throw new Error("Nie udało się wczytać zaproszenia. Spróbuj ponownie.");
 }
 if (res.status === 404 || res.status === 410) return null;
 if (!res.ok) {
 throw new Error("Nie udało się wczytać zaproszenia. Spróbuj ponownie.");
 }
 return (await res.json()) as ApplyMeta;
}

const REMOTE_LABEL: Record<string, string> = {
 remote: "Zdalnie",
 hybrid: "Hybrydowo",
 onsite: "Stacjonarnie",
};

const SENIORITY_LABEL: Record<string, string> = {
 junior: "Junior",
 mid: "Mid",
 senior: "Senior",
 lead: "Lead",
 architect: "Architect",
};

export default async function ApplyPage({ params }: PageProps) {
 const { token } = await params;
 const meta = await fetchMeta(token);
 if (!meta) notFound();

 const expiresLabel = new Date(meta.expires_at).toLocaleDateString("pl-PL", {
 day: "2-digit",
 month: "short",
 year: "numeric",
 });

 return (
 <div className="max-w-2xl mx-auto px-4 sm:px-6 py-10 sm:py-12 md:py-16">
 {/* Header */}
 <header className="flex items-center gap-3 mb-10">
 <div className="h-9 w-9 rounded-md bg-primary text-white flex items-center justify-center font-semibold">
 N
 </div>
 <div className="leading-tight">
 <div className="text-xs font-semibold tracking-eyebrow uppercase text-primary">
 Nexus · Dynaminds
 </div>
 <div className="text-[11px] text-muted-foreground">
 Aplikacja na stanowisko
 </div>
 </div>
 </header>

 {/* Hero */}
 <section className="mb-8 space-y-3">
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 {meta.recruiter.first_name} zaprasza Cię do aplikacji
 </p>
 <h1 className="font-semibold text-2xl sm:text-3xl md:text-4xl font-extrabold break-words hyphens-auto tracking-[-0.025em] text-foreground leading-[1.05]">
 {meta.job.title}
 </h1>

 <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-2 text-sm text-muted-foreground">
 {meta.job.location && (
 <span className="inline-flex items-center gap-1.5">
 <MapPin className="h-3.5 w-3.5" /> {meta.job.location}
 </span>
 )}
 {meta.job.seniority && (
 <span className="inline-flex items-center gap-1.5">
 <Sparkles className="h-3.5 w-3.5" />{" "}
 {SENIORITY_LABEL[meta.job.seniority] ?? meta.job.seniority}
 </span>
 )}
 {meta.job.remote_policy && (
 <span>{REMOTE_LABEL[meta.job.remote_policy] ?? meta.job.remote_policy}</span>
 )}
 <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
 <Calendar className="h-3 w-3" /> Ważne do {expiresLabel}
 </span>
 </div>
 </section>

 {/* Form */}
 <section className="rounded-xl bg-card border border-border shadow-md p-4 sm:p-6 md:p-8">
 <ApplyForm token={token} recruiterFirstName={meta.recruiter.first_name} />
 </section>

 <footer className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between text-[11px] text-muted-foreground pt-6">
 <span>Twoje dane trafią wyłącznie do rekrutera Dynaminds.</span>
 <span className="font-semibold text-foreground">
 Define tomorrow.
 </span>
 </footer>
 </div>
 );
}
