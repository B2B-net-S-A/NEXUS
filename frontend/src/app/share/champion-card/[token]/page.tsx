/**
 * Public Champion Card view (Phase 12).
 *
 * Rendered server-side from a recruiter-issued token. No auth required — the
 * backend enforces `expires_at` + `revoked`. A client can open this URL
 * straight from email to see the filled briefing.
 */
import { notFound } from "next/navigation";

interface PageProps {
  params: Promise<{ token: string }>;
}

// Server-side fetch → prefer the docker-internal service URL so SSR doesn't
// try to hit `localhost:8000` from inside the frontend container.
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

const FIT_LABEL: Record<string, { label: string; color: string }> = {
  fit: { label: "Pasuje", color: "bg-emerald-100 text-emerald-800 border-emerald-300" },
  uncertain: { label: "Niepewnie", color: "bg-amber-100 text-amber-800 border-amber-300" },
  miss: { label: "Nie pasuje", color: "bg-red-100 text-red-700 border-red-200" },
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
  const fitMeta = answers ? FIT_LABEL[answers.overall_fit] ?? FIT_LABEL.uncertain : null;

  return (
    <div className="min-h-screen bg-gradient-to-b from-purple-50 to-white py-8 px-4">
      <div className="max-w-3xl mx-auto bg-white rounded-2xl shadow-xl border border-gray-200 overflow-hidden">
        {/* Header */}
        <header className="bg-gradient-to-r from-purple-600 to-indigo-600 text-white px-6 py-5">
          <p className="text-xs uppercase tracking-widest opacity-80">Rekomendacja kandydata</p>
          <h1 className="text-2xl font-bold mt-1">
            {data.candidate.name} {data.candidate.lastname}
          </h1>
          <p className="text-sm opacity-95 mt-1">
            {data.candidate.competence_category}
            {data.candidate.location ? ` · ${data.candidate.location}` : ""}
            {data.candidate.years_it_experience
              ? ` · ${data.candidate.years_it_experience} lat doświadczenia`
              : ""}
          </p>
          <p className="text-xs opacity-80 mt-3">
            Stanowisko: <strong>{data.job.title}</strong>
            {data.job.location ? ` (${data.job.location})` : ""}
          </p>
        </header>

        {/* Champion basics / context */}
        {(data.champion_profile.basics || data.champion_profile.project_context) && (
          <section className="px-6 py-5 border-b border-gray-100 space-y-3">
            {data.champion_profile.project_context?.about && (
              <div>
                <h3 className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                  O projekcie
                </h3>
                <p className="text-sm text-gray-800 whitespace-pre-line">
                  {data.champion_profile.project_context.about}
                </p>
              </div>
            )}
            {data.champion_profile.project_context?.responsibilities && (
              <div>
                <h3 className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                  Obowiązki na stanowisku
                </h3>
                <p className="text-sm text-gray-800 whitespace-pre-line">
                  {data.champion_profile.project_context.responsibilities}
                </p>
              </div>
            )}
          </section>
        )}

        {/* Screening */}
        <section className="px-6 py-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-purple-800 uppercase tracking-wide flex items-center gap-1.5">
              ✨ Screening rekrutera
            </h2>
            {fitMeta && (
              <span
                className={`text-xs px-2 py-0.5 rounded-md border font-medium ${fitMeta.color}`}
              >
                {fitMeta.label}
              </span>
            )}
          </div>

          {!answers || questions.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              Screening jeszcze nie został przeprowadzony.
            </p>
          ) : (
            <ul className="space-y-3">
              {questions.map((q, i) => {
                const a = answers.answers.find((x) => x.question_id === q.id);
                return (
                  <li
                    key={q.id}
                    className="rounded-lg border border-gray-200 p-3 bg-gray-50"
                  >
                    <div className="flex items-start gap-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-mono mt-0.5 flex-shrink-0">
                        Q{i + 1}
                      </span>
                      <p className="text-sm font-medium text-gray-900 flex-1">
                        {q.question}
                      </p>
                    </div>
                    <p
                      className={`text-sm mt-2 pl-7 ${
                        a?.deal_breaker_hit
                          ? "text-red-700 font-medium"
                          : "text-gray-800"
                      }`}
                    >
                      {a?.response?.trim() || (
                        <span className="italic text-gray-400">brak odpowiedzi</span>
                      )}
                      {a?.deal_breaker_hit && (
                        <span className="ml-2 text-[10px] px-1 py-0.5 rounded bg-red-100 text-red-700 border border-red-200">
                          deal-breaker ✗
                        </span>
                      )}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}

          {answers?.notes && (
            <p className="mt-4 text-[13px] text-gray-600 italic border-l-2 border-purple-300 pl-3">
              {answers.notes}
            </p>
          )}
        </section>

        {/* Footer */}
        <footer className="px-6 py-3 border-t border-gray-100 flex items-center justify-between text-[11px] text-gray-400">
          <span>Dokument udostępniony przez Nexus ATS</span>
          {data.expires_at && (
            <span>
              Ważne do{" "}
              {new Date(data.expires_at).toLocaleDateString("pl-PL", {
                day: "2-digit",
                month: "short",
                year: "numeric",
              })}
            </span>
          )}
        </footer>
      </div>
    </div>
  );
}
