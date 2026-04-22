/**
 * Public candidate apply page — served at /apply/{token}.
 *
 * Renders hero + ApplyForm when the token is valid. On any error (expired,
 * revoked, unknown) we `notFound()` which renders not-found.tsx.
 */
import { notFound } from "next/navigation";
import { Calendar, MapPin, Sparkles } from "lucide-react";
import ApplyForm from "./ApplyForm";

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
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  );
}

async function fetchMeta(token: string): Promise<ApplyMeta | null> {
  const url = `${apiBase()}/api/public/apply/${token}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as ApplyMeta;
  } catch {
    return null;
  }
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
    <div className="max-w-2xl mx-auto px-6 py-12 md:py-16">
      {/* Header */}
      <header className="flex items-center gap-3 mb-10">
        <div className="h-9 w-9 rounded-v2-s bg-[hsl(var(--accent))] text-white flex items-center justify-center font-display font-extrabold">
          N
        </div>
        <div className="leading-tight">
          <div className="text-xs font-semibold tracking-[0.22em] uppercase text-[hsl(var(--accent))]">
            Nexus · Dynaminds
          </div>
          <div className="text-[11px] text-[hsl(var(--text-muted))]">
            Aplikacja na stanowisko
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="mb-8 space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
          {meta.recruiter.first_name} zaprasza Cię do aplikacji
        </p>
        <h1 className="font-display text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] leading-[1.05]">
          {meta.job.title}
        </h1>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-2 text-sm text-[hsl(var(--text-muted))]">
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
          <span className="inline-flex items-center gap-1.5 text-[11px] text-[hsl(var(--text-muted))]">
            <Calendar className="h-3 w-3" /> Ważne do {expiresLabel}
          </span>
        </div>
      </section>

      {/* Form */}
      <section className="rounded-v2-l bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] shadow-v2-xl p-6 md:p-8">
        <ApplyForm token={token} recruiterFirstName={meta.recruiter.first_name} />
      </section>

      <footer className="flex items-center justify-between text-[11px] text-[hsl(var(--text-muted))] pt-6">
        <span>Twoje dane trafią wyłącznie do rekrutera Dynaminds.</span>
        <span className="font-display font-semibold text-[hsl(var(--text-title))]">
          Define tomorrow.
        </span>
      </footer>
    </div>
  );
}
