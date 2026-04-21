/**
 * Public Champion Card view — v2 redesign (theme-dark).
 *
 * Rendered server-side from a recruiter-issued token. No auth required —
 * backend enforces `expires_at` + `revoked`. The page uses Dynaminds
 * theme-dark palette (black canvas, plum cards, cream text, burgundy
 * accents) for a premium client-facing feel.
 */
import { notFound } from "next/navigation";
import { AlertCircle, Calendar, CheckCircle2, Sparkles, XCircle } from "lucide-react";

interface PageProps {
  params: Promise<{ token: string }>;
}

function apiBase(): string {
  return (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  );
}

interface Question {
  id: string;
  question: string;
  ideal_answer: string;
  deal_breaker: string;
}

interface AnswerItem {
  question_id: string;
  response: string;
  deal_breaker_hit: boolean;
}

interface ShareResponse {
  candidate: {
    name: string | null;
    lastname: string | null;
    competence_category: string | null;
    location: string | null;
    years_it_experience: number | null;
  };
  job: {
    title: string | null;
    location: string | null;
    seniority: string | null;
  };
  champion_profile: {
    basics?: { onsite_days_per_week?: number | null; language?: string | null };
    project_context?: {
      about?: string;
      responsibilities?: string;
      selling_points?: string;
    };
    screening_questions?: Question[];
  };
  screening_answers: {
    answers: AnswerItem[];
    overall_fit: "fit" | "uncertain" | "miss";
    notes: string;
  } | null;
  expires_at: string | null;
}

const FIT_META: Record<
  string,
  { label: string; chipBg: string; chipText: string; icon: React.ReactNode }
> = {
  fit: {
    label: "Pasuje",
    chipBg: "bg-[#1d5e31]/20 border border-[#1d5e31]/40",
    chipText: "text-[#7fcf8e]",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
  },
  uncertain: {
    label: "Niepewnie",
    chipBg: "bg-amber-500/15 border border-amber-500/40",
    chipText: "text-amber-300",
    icon: <AlertCircle className="h-3.5 w-3.5" />,
  },
  miss: {
    label: "Nie pasuje",
    chipBg: "bg-[hsl(var(--accent))]/20 border border-[hsl(var(--accent))]/40",
    chipText: "text-[#d48b95]",
    icon: <XCircle className="h-3.5 w-3.5" />,
  },
};

async function fetchShare(token: string): Promise<ShareResponse | null> {
  const url = `${apiBase()}/api/public/champion-card/${token}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      console.error("[share] upstream", res.status, url);
      return null;
    }
    return (await res.json()) as ShareResponse;
  } catch (e) {
    console.error("[share] fetch error", url, e);
    return null;
  }
}

export default async function PublicChampionCardPage({ params }: PageProps) {
  const { token } = await params;
  const data = await fetchShare(token);
  if (!data) notFound();

  const questions: Question[] = data.champion_profile.screening_questions ?? [];
  const answers = data.screening_answers;
  const fitMeta = answers ? FIT_META[answers.overall_fit] ?? FIT_META.uncertain : null;
  const fullName = `${data.candidate.name ?? ""} ${data.candidate.lastname ?? ""}`.trim();

  return (
    <div
      data-ui="v2"
      data-ui-theme="share-dark"
      className="min-h-screen bg-[hsl(var(--bg-canvas))] text-[hsl(var(--text-body))]"
    >
      {/* Ambient glow */}
      <div
        className="pointer-events-none fixed inset-0"
        style={{
          background:
            "radial-gradient(ellipse 80% 40% at 50% 0%, hsl(var(--accent))/15, transparent 70%)",
        }}
        aria-hidden="true"
      />

      {/* Top bar */}
      <header className="relative z-10 max-w-4xl mx-auto px-6 pt-8 pb-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-v2-s bg-[hsl(var(--accent))] text-white flex items-center justify-center font-display font-extrabold text-sm">
            N
          </div>
          <div className="leading-tight">
            <div className="text-xs font-semibold tracking-[0.22em] uppercase text-[hsl(var(--accent))]">
              Nexus · Dynaminds
            </div>
            <div className="text-[10px] opacity-60">Rekomendacja kandydata</div>
          </div>
        </div>
        {data.expires_at && (
          <div className="inline-flex items-center gap-1.5 text-[11px] opacity-70">
            <Calendar className="h-3 w-3" />
            Ważne do{" "}
            {new Date(data.expires_at).toLocaleDateString("pl-PL", {
              day: "2-digit",
              month: "short",
              year: "numeric",
            })}
          </div>
        )}
      </header>

      {/* Hero */}
      <section className="relative z-10 max-w-4xl mx-auto px-6 pt-4 pb-8">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))] mb-2">
          {data.candidate.competence_category ?? "Kandydat"}
        </p>
        <h1 className="font-display text-4xl md:text-5xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] leading-[1.02]">
          {fullName || "Kandydat"}
        </h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-sm opacity-80">
          {data.candidate.location && <span>{data.candidate.location}</span>}
          {data.candidate.years_it_experience && (
            <>
              <span className="opacity-40">·</span>
              <span>{data.candidate.years_it_experience} lat doświadczenia</span>
            </>
          )}
        </div>

        {/* Role chip */}
        <div className="mt-5 inline-flex items-center gap-2 rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))]/40 px-4 py-2">
          <Sparkles className="h-4 w-4 text-[hsl(var(--accent))]" />
          <span className="text-sm">
            Rekomendacja na stanowisko:{" "}
            <strong className="text-[hsl(var(--text-title))]">{data.job.title}</strong>
            {data.job.location && (
              <span className="opacity-70"> · {data.job.location}</span>
            )}
          </span>
        </div>
      </section>

      {/* Main content */}
      <main className="relative z-10 max-w-4xl mx-auto px-6 pb-12 space-y-5">
        {/* Project context */}
        {(data.champion_profile.project_context?.about ||
          data.champion_profile.project_context?.responsibilities) && (
          <section className="rounded-v2-l bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] shadow-v2-xl p-6 space-y-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[hsl(var(--accent))]">
              Kontekst projektu
            </p>
            {data.champion_profile.project_context.about && (
              <div>
                <h3 className="font-display font-bold text-lg text-[hsl(var(--text-title))] mb-1">
                  O projekcie
                </h3>
                <p className="text-sm leading-relaxed whitespace-pre-line">
                  {data.champion_profile.project_context.about}
                </p>
              </div>
            )}
            {data.champion_profile.project_context.responsibilities && (
              <div>
                <h3 className="font-display font-bold text-lg text-[hsl(var(--text-title))] mb-1">
                  Obowiązki
                </h3>
                <p className="text-sm leading-relaxed whitespace-pre-line">
                  {data.champion_profile.project_context.responsibilities}
                </p>
              </div>
            )}
          </section>
        )}

        {/* Screening */}
        <section className="rounded-v2-l bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] shadow-v2-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[hsl(var(--accent))]">
              Screening rekrutera
            </p>
            {fitMeta && (
              <span
                className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ${fitMeta.chipBg} ${fitMeta.chipText}`}
              >
                {fitMeta.icon}
                {fitMeta.label}
              </span>
            )}
          </div>

          {!answers || questions.length === 0 ? (
            <p className="text-sm opacity-60 italic py-6 text-center">
              Screening jeszcze nie został przeprowadzony.
            </p>
          ) : (
            <ul className="space-y-3">
              {questions.map((q, i) => {
                const a = answers.answers.find((x) => x.question_id === q.id);
                return (
                  <li
                    key={q.id}
                    className="rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-canvas))]/40 p-4"
                  >
                    <div className="flex items-start gap-2 mb-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded-v2-xs font-mono bg-[hsl(var(--accent))]/20 text-[hsl(var(--accent))] mt-0.5 shrink-0">
                        Q{i + 1}
                      </span>
                      <p className="text-sm font-semibold text-[hsl(var(--text-title))] flex-1">
                        {q.question}
                      </p>
                    </div>
                    <p
                      className={`text-sm pl-8 ${
                        a?.deal_breaker_hit
                          ? "text-[#d48b95] font-medium"
                          : "text-[hsl(var(--text-body))]"
                      }`}
                    >
                      {a?.response?.trim() || (
                        <span className="italic opacity-50">brak odpowiedzi</span>
                      )}
                      {a?.deal_breaker_hit && (
                        <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-v2-xs bg-[hsl(var(--accent))]/20 text-[#d48b95] border border-[hsl(var(--accent))]/40">
                          deal-breaker
                        </span>
                      )}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}

          {answers?.notes && (
            <div className="mt-5 pt-4 border-t border-[hsl(var(--border-subtle))]">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[hsl(var(--accent))] mb-1">
                Komentarz rekrutera
              </p>
              <p className="text-sm italic opacity-90 whitespace-pre-line">{answers.notes}</p>
            </div>
          )}
        </section>

        {/* Footer */}
        <footer className="flex items-center justify-between text-[11px] opacity-60 pt-2">
          <span>Dokument udostępniony przez Nexus ATS · B2B.net S.A.</span>
          <span className="font-display font-semibold text-[hsl(var(--text-title))]">
            Define tomorrow.
          </span>
        </footer>
      </main>
    </div>
  );
}
