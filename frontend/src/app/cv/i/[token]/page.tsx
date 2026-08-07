"use client";

/**
 * Interaktywne CV — publiczny widok wygenerowanego CV (Generator B2B).
 *
 * Jeden link (`/cv/i/{token}`), dwa widoki przełączane przez hiring managera:
 *  - „Klasyczne"    — dokument HTML 1:1 z render_payload (sekcje jak DOCX),
 *  - „Interaktywne" — kafelki wymagań must/nice-have z dowodami-cytatami
 *    (klik w dowód podświetla pozycję doświadczenia) + chat AI.
 *
 * Dane: GET /api/public/cv-i/{token} — client-safe payload (bez warnings,
 * przy blind bez nazwiska i nazw firm). Chat: POST /api/public/cv-i/{token}/chat
 * (odpowiada wyłącznie na podstawie tego profilu; 429 = dzienny limit).
 * Druk: window.print() — elementy interaktywne mają `print:hidden`.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import axios from "axios";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  CircleSlash,
  LayoutList,
  Loader2,
  MessageCircle,
  Printer,
  Send,
  Sparkles,
} from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.dynaminds.pl";

// ── Typy (kontrakt GET /api/public/cv-i/{token}) ────────────────────────────

interface CvExperience {
  dates: string;
  company: string;
  industry: string;
  position: string;
  responsibilities: string[];
  technologies: string[];
}

interface PublicCvPayload {
  language: "pl" | "en";
  blind: boolean;
  candidate_name: string;
  position: string;
  considered_for: string | null;
  why_points: string[];
  education: {
    dates: string;
    institution: string;
    degree: string;
    location: string;
  }[];
  skills: { label: string; content: string }[];
  certifications: string[];
  languages: string[];
  experience: CvExperience[];
  highlight_keywords: string[];
}

interface RequirementEvidence {
  experience_index: number | null;
  quote: string;
}

interface RequirementItem {
  requirement: string;
  kind: "must" | "nice";
  status: "met" | "partial" | "no_data";
  note: string | null;
  evidence: RequirementEvidence[];
}

interface PublicCvIView {
  cv: PublicCvPayload;
  requirements: RequirementItem[] | null;
  chat_enabled: boolean;
  expires_at: string | null;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// ── Etykiety PL/EN (język UI = język CV) ────────────────────────────────────

const LABELS = {
  pl: {
    pageKicker: "Profil kandydata",
    consideredFor: "Rozważany na stanowisko:",
    why: "Dlaczego nasz kandydat?",
    summary: "Podsumowanie",
    education: "Edukacja",
    skills: "Umiejętności",
    certs: "Certyfikaty",
    langs: "Języki",
    experience: "Doświadczenie",
    scope: "Zakres zadań:",
    tech: "Technologie:",
    classic: "Klasyczne",
    interactive: "Interaktywne",
    print: "Drukuj / PDF",
    requirementsTitle: "Dopasowanie do wymagań",
    requirementsHint:
      "Kliknij wymaganie, aby zobaczyć dowody z CV. Kliknięcie cytatu podświetla pozycję w doświadczeniu.",
    must: "must-have",
    nice: "nice-to-have",
    met: "Potwierdzone w CV",
    partial: "Częściowo / pośrednio",
    noData: "Brak danych w CV",
    evidence: "Dowody z CV",
    noEvidence: "CV nie zawiera informacji o tym wymaganiu.",
    chatTitle: "Zapytaj o kandydata",
    chatHint:
      "Asystent AI odpowiada wyłącznie na podstawie tego profilu. W sprawach stawek i dostępności — skontaktuj się z opiekunem procesu.",
    chatPlaceholder: "Zadaj pytanie o doświadczenie kandydata…",
    chatEmpty: "Zadaj pytanie — np.:",
    linkActiveTo: "Link aktywny do",
    expiredTitle: "Link wygasł",
    unavailableTitle: "Link niedostępny",
    unavailableBody: "Skontaktuj się z osobą, która udostępniła Ci ten link.",
    loading: "Ładowanie profilu…",
    chatLimit: "Dzienny limit pytań dla tego linku został wyczerpany.",
    chatUnavailable: "Chat jest chwilowo niedostępny. Spróbuj ponownie później.",
    chatFailed: "Nie udało się uzyskać odpowiedzi. Spróbuj ponownie.",
  },
  en: {
    pageKicker: "Candidate profile",
    consideredFor: "Considered for:",
    why: "Why our candidate?",
    summary: "Summary",
    education: "Education",
    skills: "Skills",
    certs: "Certifications",
    langs: "Languages",
    experience: "Experience",
    scope: "Responsibilities:",
    tech: "Technologies:",
    classic: "Classic",
    interactive: "Interactive",
    print: "Print / PDF",
    requirementsTitle: "Requirements match",
    requirementsHint:
      "Click a requirement to see evidence from the CV. Clicking a quote highlights the matching experience entry.",
    must: "must-have",
    nice: "nice-to-have",
    met: "Confirmed in CV",
    partial: "Partial / indirect",
    noData: "No data in CV",
    evidence: "Evidence from CV",
    noEvidence: "The CV does not cover this requirement.",
    chatTitle: "Ask about the candidate",
    chatHint:
      "The AI assistant answers only from this profile. For rates and availability, contact your process owner.",
    chatPlaceholder: "Ask about the candidate's experience…",
    chatEmpty: "Ask a question — e.g.:",
    linkActiveTo: "Link active until",
    expiredTitle: "Link expired",
    unavailableTitle: "Link unavailable",
    unavailableBody: "Contact the person who shared this link with you.",
    loading: "Loading profile…",
    chatLimit: "The daily question limit for this link has been reached.",
    chatUnavailable: "Chat is temporarily unavailable. Please try again later.",
    chatFailed: "Could not get an answer. Please try again.",
  },
} as const;

type Labels = Record<keyof (typeof LABELS)["pl"], string>;

const STATUS_STYLE: Record<
  RequirementItem["status"],
  { chip: string; icon: typeof CheckCircle2 }
> = {
  met: {
    chip: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    icon: CheckCircle2,
  },
  partial: {
    chip: "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
    icon: CircleDashed,
  },
  no_data: {
    chip: "border-border bg-muted text-muted-foreground",
    icon: CircleSlash,
  },
};

function getErrorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response
    ?.data?.detail;
  return detail ?? fallback;
}

// ── Sekcje dokumentu CV (wspólne dla obu widoków) ───────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold uppercase tracking-wider text-primary mt-6 mb-2 first:mt-0">
      {children}
    </h2>
  );
}

function CvDocument({
  cv,
  t,
  highlightedExp,
}: {
  cv: PublicCvPayload;
  t: Labels;
  highlightedExp: number | null;
}) {
  return (
    <article className="rounded-lg border border-border bg-card shadow-xs p-6 sm:p-8">
      {/* Nagłówek dokumentu */}
      <header className="border-b border-border pb-4 mb-4">
        <h1 className="text-2xl font-semibold text-foreground">
          {cv.blind ? cv.position : `${cv.position} – ${cv.candidate_name}`}
        </h1>
        {cv.considered_for ? (
          <p className="mt-1 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              {t.consideredFor}
            </span>{" "}
            {cv.considered_for}
          </p>
        ) : null}
      </header>

      {/* Dlaczego nasz kandydat / Podsumowanie */}
      {cv.why_points.length > 0 && (
        <>
          <SectionTitle>{cv.blind ? t.summary : t.why}</SectionTitle>
          <ul className="space-y-1.5">
            {cv.why_points.map((point, i) => (
              <li key={i} className="flex gap-2 text-sm text-foreground">
                <span className="text-primary mt-0.5">•</span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Edukacja */}
      {cv.education.length > 0 && (
        <>
          <SectionTitle>{t.education}</SectionTitle>
          <div className="space-y-2">
            {cv.education.map((edu, i) => (
              <div key={i} className="grid sm:grid-cols-[140px_1fr] gap-x-4 text-sm">
                <div className="text-muted-foreground">{edu.dates}</div>
                <div>
                  <span className="font-medium text-foreground">
                    {edu.institution}
                  </span>
                  {edu.degree ? (
                    <span className="text-muted-foreground"> — {edu.degree}</span>
                  ) : null}
                  {edu.location ? (
                    <span className="text-muted-foreground">
                      {" "}
                      · {edu.location}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Umiejętności */}
      {cv.skills.length > 0 && (
        <>
          <SectionTitle>{t.skills}</SectionTitle>
          <div className="space-y-1.5">
            {cv.skills.map((group, i) => {
              // Payload bywa z dwukropkiem w labelu ("Big Data i ETL:") —
              // zdejmujemy go, żeby nie renderować "ETL:: Hadoop…".
              const label = (group.label || "").replace(/:+\s*$/, "");
              return (
                <p key={i} className="text-sm text-foreground">
                  {label ? <span className="font-medium">{label}: </span> : null}
                  <span className="text-muted-foreground">{group.content}</span>
                </p>
              );
            })}
          </div>
        </>
      )}

      {/* Certyfikaty */}
      {cv.certifications.length > 0 && (
        <>
          <SectionTitle>{t.certs}</SectionTitle>
          <ul className="space-y-1 text-sm text-foreground">
            {cv.certifications.map((cert, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-primary mt-0.5">•</span>
                <span>{cert}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Języki */}
      {cv.languages.length > 0 && (
        <>
          <SectionTitle>{t.langs}</SectionTitle>
          <p className="text-sm text-muted-foreground">
            {cv.languages.join(" · ")}
          </p>
        </>
      )}

      {/* Doświadczenie */}
      {cv.experience.length > 0 && (
        <>
          <SectionTitle>{t.experience}</SectionTitle>
          <div className="space-y-5">
            {cv.experience.map((job, i) => (
              <div
                key={i}
                id={`cvi-exp-${i}`}
                className={`rounded-md -mx-2 px-2 py-1.5 transition-shadow duration-500 ${
                  highlightedExp === i
                    ? "ring-2 ring-primary/60 bg-primary/5"
                    : ""
                }`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                  <p className="text-sm font-semibold text-foreground">
                    {job.position}
                  </p>
                  <p className="text-xs text-muted-foreground">{job.dates}</p>
                </div>
                <p className="text-sm text-muted-foreground">
                  {job.company}
                  {job.industry ? ` · ${job.industry}` : ""}
                </p>
                {job.responsibilities.length > 0 && (
                  <div className="mt-1.5">
                    <p className="text-xs font-medium text-foreground mb-1">
                      {t.scope}
                    </p>
                    <ul className="space-y-1">
                      {job.responsibilities.map((r, j) => (
                        <li
                          key={j}
                          className="flex gap-2 text-sm text-foreground"
                        >
                          <span className="text-primary mt-0.5">•</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {job.technologies.length > 0 && (
                  <p className="mt-1.5 text-sm">
                    <span className="text-xs font-medium text-foreground">
                      {t.tech}
                    </span>{" "}
                    <span className="text-muted-foreground">
                      {job.technologies.join(", ")}
                    </span>
                  </p>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </article>
  );
}

// ── Kafelki wymagań ─────────────────────────────────────────────────────────

function RequirementTiles({
  items,
  t,
  onQuoteClick,
}: {
  items: RequirementItem[];
  t: Labels;
  onQuoteClick: (expIndex: number | null) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const groups: { kind: "must" | "nice"; label: string }[] = [
    { kind: "must", label: t.must },
    { kind: "nice", label: t.nice },
  ];
  const statusLabel: Record<RequirementItem["status"], string> = {
    met: t.met,
    partial: t.partial,
    no_data: t.noData,
  };

  return (
    <section className="rounded-lg border border-border bg-card shadow-xs p-4 sm:p-5 print:hidden">
      <div className="flex items-center gap-2 mb-1">
        <LayoutList className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold text-foreground">
          {t.requirementsTitle}
        </h2>
      </div>
      <p className="text-xs text-muted-foreground mb-3">{t.requirementsHint}</p>
      <div className="space-y-3">
        {groups.map((group) => {
          const groupItems = items.filter((i) => i.kind === group.kind);
          if (groupItems.length === 0) return null;
          return (
            <div key={group.kind}>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                {group.label}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {groupItems.map((item) => {
                  const style = STATUS_STYLE[item.status];
                  const Icon = style.icon;
                  const key = `${item.kind}:${item.requirement}`;
                  const isOpen = expanded === key;
                  return (
                    <div
                      key={key}
                      className={`rounded-md border text-left ${style.chip}`}
                    >
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : key)}
                        className="w-full flex items-center gap-2 px-3 py-2"
                        aria-expanded={isOpen}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        <span className="text-sm font-medium truncate flex-1">
                          {item.requirement}
                        </span>
                        <ChevronDown
                          className={`h-3.5 w-3.5 shrink-0 transition-transform ${
                            isOpen ? "rotate-180" : ""
                          }`}
                        />
                      </button>
                      {isOpen && (
                        <div className="px-3 pb-3 pt-0.5 space-y-2">
                          <p className="text-[11px] font-medium uppercase tracking-wide opacity-80">
                            {statusLabel[item.status]}
                          </p>
                          {item.note ? (
                            <p className="text-sm">{item.note}</p>
                          ) : null}
                          {item.evidence.length > 0 ? (
                            <div>
                              <p className="text-[11px] font-medium uppercase tracking-wide opacity-80 mb-1">
                                {t.evidence}
                              </p>
                              <ul className="space-y-1.5">
                                {item.evidence.map((ev, i) => (
                                  <li key={i}>
                                    <button
                                      type="button"
                                      onClick={() =>
                                        onQuoteClick(ev.experience_index)
                                      }
                                      className="w-full text-left text-sm italic rounded bg-background/60 dark:bg-background/30 border border-border/60 px-2 py-1.5 hover:border-primary/50 transition-colors"
                                    >
                                      „{ev.quote}"
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : item.status === "no_data" ? (
                            <p className="text-sm opacity-80">{t.noEvidence}</p>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── Chat ────────────────────────────────────────────────────────────────────

function ChatPanel({
  token,
  t,
  suggestions,
}: {
  token: string;
  t: Labels;
  suggestions: string[];
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, sending]);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || sending) return;
    setChatError(null);
    setMessages((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setSending(true);
    try {
      const res = await axios.post<{ answer: string }>(
        `${API_BASE}/api/public/cv-i/${token}/chat`,
        { question: q },
      );
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.data.answer },
      ]);
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response
        ?.status;
      if (status === 429) setChatError(t.chatLimit);
      else if (status === 503) setChatError(t.chatUnavailable);
      else setChatError(getErrorMessage(e, t.chatFailed));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card shadow-xs flex flex-col print:hidden lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)]">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageCircle className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">
            {t.chatTitle}
          </h2>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">{t.chatHint}</p>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-[220px] max-h-[420px] lg:max-h-none"
      >
        {messages.length === 0 && (
          <div className="text-sm text-muted-foreground">
            <p className="mb-2">{t.chatEmpty}</p>
            <div className="flex flex-col gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => ask(s)}
                  className="text-left text-sm rounded-md border border-border bg-background px-3 py-1.5 hover:border-primary/50 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={msg.role === "user" ? "flex justify-end" : "flex"}
          >
            <div
              className={
                msg.role === "user"
                  ? "max-w-[85%] rounded-lg bg-primary text-white px-3 py-2 text-sm whitespace-pre-wrap"
                  : "max-w-[85%] rounded-lg bg-muted text-foreground px-3 py-2 text-sm whitespace-pre-wrap"
              }
            >
              {msg.content}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />…
          </div>
        )}
        {chatError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {chatError}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="border-t border-border p-3 flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={500}
          placeholder={t.chatPlaceholder}
          className="flex-1 h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-primary/40"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-primary text-white disabled:opacity-50 hover:bg-primary/90 transition-colors"
          aria-label={t.chatTitle}
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </section>
  );
}

// ── Strona ──────────────────────────────────────────────────────────────────

export default function PublicInteractiveCvPage() {
  const params = useParams();
  const token = String(params?.token ?? "");

  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<PublicCvIView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [mode, setMode] = useState<"classic" | "interactive">("classic");
  const [highlightedExp, setHighlightedExp] = useState<number | null>(null);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await axios.get<PublicCvIView>(
          `${API_BASE}/api/public/cv-i/${token}`,
        );
        setView(res.data);
        // Wersja interaktywna jest esencją tego linku — otwieramy ją domyślnie
        // gdy jest dostępna; przełącznik pozwala wrócić do klasycznego widoku.
        if (
          (res.data.requirements && res.data.requirements.length > 0) ||
          res.data.chat_enabled
        ) {
          setMode("interactive");
        }
      } catch (e) {
        setErrorStatus(
          (e as { response?: { status?: number } })?.response?.status ?? null,
        );
        setError(getErrorMessage(e, "…"));
      } finally {
        setLoading(false);
      }
    }
    if (token) load();
  }, [token]);

  const t: Labels = LABELS[view?.cv.language === "en" ? "en" : "pl"];

  const suggestions = useMemo(() => {
    if (!view) return [];
    const en = view.cv.language === "en";
    const reqs = (view.requirements ?? [])
      .filter((r) => r.kind === "must")
      .slice(0, 2)
      .map((r) =>
        en
          ? `What experience does the candidate have with ${r.requirement}?`
          : `Jakie doświadczenie z ${r.requirement} ma kandydat?`,
      );
    return [
      ...reqs,
      en
        ? "Summarize the candidate's last role."
        : "Podsumuj ostatnią rolę kandydata.",
    ];
  }, [view]);

  function handleQuoteClick(expIndex: number | null) {
    if (expIndex === null) return;
    document
      .getElementById(`cvi-exp-${expIndex}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    setHighlightedExp(expIndex);
    highlightTimer.current = setTimeout(() => setHighlightedExp(null), 2500);
  }

  if (loading) {
    return (
      <main className="max-w-4xl mx-auto p-6 pt-16">
        <div className="animate-pulse text-center text-sm text-muted-foreground">
          {LABELS.pl.loading}
        </div>
      </main>
    );
  }

  if (error || !view) {
    const heading =
      errorStatus === 410 ? LABELS.pl.expiredTitle : LABELS.pl.unavailableTitle;
    return (
      <main className="max-w-xl mx-auto p-6 pt-16">
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 dark:border-red-900 dark:bg-red-950 p-6 text-center">
          <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-3" />
          <h2 className="text-lg font-semibold mb-1">{heading}</h2>
          <p className="text-sm text-destructive dark:text-red-300">
            {error && error !== "…" ? error : LABELS.pl.unavailableBody}
          </p>
        </div>
      </main>
    );
  }

  const cv = view.cv;
  const hasInteractive =
    (view.requirements !== null && view.requirements.length > 0) ||
    view.chat_enabled;
  const showInteractive = mode === "interactive" && hasInteractive;

  const expiresLabel = view.expires_at
    ? new Date(view.expires_at).toLocaleDateString(
        cv.language === "en" ? "en-GB" : "pl-PL",
        { day: "numeric", month: "long", year: "numeric" },
      )
    : null;

  return (
    <main className="max-w-6xl mx-auto p-4 sm:p-6">
      {/* Nagłówek strony */}
      <div className="mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 print:hidden">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            {t.pageKicker}
          </p>
          <h1 className="text-xl sm:text-2xl font-semibold text-foreground">
            {cv.candidate_name || cv.position}
            {cv.considered_for ? (
              <span className="ml-2 text-base font-normal text-muted-foreground">
                — {cv.considered_for}
              </span>
            ) : null}
          </h1>
          {expiresLabel ? (
            <p className="text-xs text-muted-foreground mt-1">
              {t.linkActiveTo} {expiresLabel}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {hasInteractive && (
            <div
              className="inline-flex rounded-md border border-border bg-card p-0.5 text-sm"
              role="tablist"
              aria-label="Widok CV"
            >
              <button
                type="button"
                role="tab"
                aria-selected={!showInteractive}
                onClick={() => setMode("classic")}
                className={`px-3 py-1.5 rounded transition-colors ${
                  !showInteractive
                    ? "bg-primary text-white"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.classic}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={showInteractive}
                onClick={() => setMode("interactive")}
                className={`px-3 py-1.5 rounded transition-colors ${
                  showInteractive
                    ? "bg-primary text-white"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.interactive}
              </button>
            </div>
          )}
          <button
            onClick={() => window.print()}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card hover:bg-muted text-foreground px-3 py-2 text-sm font-medium shadow-xs transition-colors"
          >
            <Printer className="h-4 w-4" />
            {t.print}
          </button>
        </div>
      </div>

      {showInteractive ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] items-start">
          <div className="space-y-4 min-w-0">
            {view.requirements && view.requirements.length > 0 && (
              <RequirementTiles
                items={view.requirements}
                t={t}
                onQuoteClick={handleQuoteClick}
              />
            )}
            <CvDocument cv={cv} t={t} highlightedExp={highlightedExp} />
          </div>
          {view.chat_enabled && (
            <ChatPanel token={token} t={t} suggestions={suggestions} />
          )}
        </div>
      ) : (
        <CvDocument cv={cv} t={t} highlightedExp={null} />
      )}

      <footer className="mt-6 flex items-center justify-center gap-2 text-xs text-muted-foreground print:hidden">
        <Sparkles className="h-3.5 w-3.5" />
        <span>Nexus · B2B.net S.A.</span>
      </footer>
    </main>
  );
}
