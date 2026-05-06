"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  Calendar,
  ChevronDown,
  ChevronUp,
  Loader2,
  Mail,
  MapPin,
  MoreVertical,
  Send,
  Sparkles,
  TrendingDown,
  User,
} from "lucide-react";
import { recommendationsApi, type SeekingContractorRow } from "@/lib/api";
import { EmailDraftDialog } from "./EmailDraftDialog";

interface Props {
  row: SeekingContractorRow;
}

interface DraftState {
  title: string;
  to?: string;
  subject: string;
  textBody: string;
  htmlBody?: string;
}

function ScoreChip({ score }: { score: number }) {
  const color =
    score >= 80
      ? "bg-green-100 text-green-700 border-green-300"
      : score >= 60
        ? "bg-primary/15 text-primary border-primary/30"
        : score >= 40
          ? "bg-amber-100 text-amber-700 border-amber-300"
          : "bg-muted text-muted-foreground border-border";
  return (
    <span
      className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${color}`}
    >
      {score.toFixed(0)}
    </span>
  );
}

function SourceBadge({ row }: { row: SeekingContractorRow }) {
  if (row.source === "ending_contract" && row.contract_end_date) {
    const daysLeft = Math.max(
      0,
      Math.round(
        (new Date(row.contract_end_date).getTime() - Date.now()) /
          (1000 * 60 * 60 * 24),
      ),
    );
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/15 text-destructive border border-red-300">
        <Calendar className="w-3 h-3" />
        Kontrakt kończy się za {daysLeft} dni
      </span>
    );
  }
  if (row.candidate.availability_status === "actively_looking") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 border border-orange-300">
        <Sparkles className="w-3 h-3" />
        Aktywnie szuka
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary border border-primary/30">
      <Sparkles className="w-3 h-3" />
      Otwarty na oferty
    </span>
  );
}

export function ContractorMatchCard({ row }: Props) {
  const c = row.candidate;
  const [assigningJobId, setAssigningJobId] = useState<number | null>(null);
  const [assignedIds, setAssignedIds] = useState<Set<number>>(new Set());
  const [openMenuJobId, setOpenMenuJobId] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftState | null>(null);

  const handleProposal = async (jobId: number) => {
    setActionLoading(`proposal-${jobId}`);
    setOpenMenuJobId(null);
    try {
      const res = await recommendationsApi.prepareClientProposal({
        candidate_id: c.id,
        job_id: jobId,
      });
      setDraft({
        title: "Propozycja kandydata dla klienta",
        subject: res.data.draft_email.subject,
        textBody: res.data.draft_email.text_body,
        htmlBody: res.data.draft_email.html_body,
      });
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd")
          : "Błąd";
      alert(`Nie udało się wygenerować propozycji: ${msg}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleShortlist = async () => {
    if (row.top_matches.length === 0) {
      alert("Brak ofert do wysłania w shortliście.");
      return;
    }
    setActionLoading("shortlist");
    try {
      const res = await recommendationsApi.sendCandidateShortlistEmail({
        candidate_id: c.id,
        job_ids: row.top_matches.map((m) => m.job.id),
      });
      setDraft({
        title: "Shortlist mailem do kandydata",
        to: res.data.to,
        subject: res.data.subject,
        textBody: res.data.text_body,
        htmlBody: res.data.html_body,
      });
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd")
          : "Błąd";
      alert(`Nie udało się wygenerować shortlistu: ${msg}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleAssign = async (jobId: number) => {
    setAssigningJobId(jobId);
    try {
      await recommendationsApi.assignToJob(c.id, jobId);
      setAssignedIds((prev) => new Set(prev).add(jobId));
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd")
          : "Błąd";
      alert(`Nie udało się przypisać: ${msg}`);
    } finally {
      setAssigningJobId(null);
    }
  };

  const initials = `${(c.name || "?")[0]}${(c.lastname || "?")[0]}`.toUpperCase();

  return (
    <article
      className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4 shadow-sm hover:shadow-md transition-shadow"
      data-testid={`contractor-card-${c.id}`}
    >
      {/* Header */}
      <header className="flex items-start gap-3 mb-3">
        {c.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={c.avatar_url}
            alt={`${c.name} ${c.lastname}`}
            className="w-12 h-12 rounded-full object-cover shrink-0"
          />
        ) : (
          <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white font-bold shrink-0">
            {initials}
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              href={`/candidates/${c.id}`}
              className="font-semibold text-foreground dark:text-foreground hover:underline truncate"
            >
              {c.name} {c.lastname}
            </Link>
            {c.champion && (
              <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                ★ CHAMPION
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground flex items-center gap-2 mt-0.5 flex-wrap">
            {c.competence_category && (
              <span className="flex items-center gap-1">
                <User className="w-3 h-3" /> {c.competence_category}
              </span>
            )}
            {c.years_it_experience !== null && (
              <span>{c.years_it_experience} lat doświadczenia</span>
            )}
            {c.location && (
              <span className="flex items-center gap-1">
                <MapPin className="w-3 h-3" /> {c.location}
              </span>
            )}
          </div>
        </div>

        <SourceBadge row={row} />

        <button
          onClick={handleShortlist}
          disabled={actionLoading !== null}
          title="Wyślij do kandydata maila z listą tych ofert"
          className="ml-2 text-xs flex items-center gap-1 bg-purple-600 hover:bg-purple-700 text-white px-2 py-1 rounded-md disabled:opacity-50"
          data-testid={`shortlist-${c.id}`}
        >
          {actionLoading === "shortlist" ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Send className="w-3 h-3" />
          )}
          Shortlist mailem
        </button>
      </header>

      {/* Top matches */}
      {row.top_matches.length === 0 ? (
        <div className="rounded bg-muted dark:bg-card/40 p-3 text-sm text-muted-foreground text-center">
          Brak ofert spełniających próg dopasowania.
        </div>
      ) : (
        <ul className="space-y-1.5" aria-label="Top dopasowania">
          {row.top_matches.map((m) => {
            const j = m.job;
            const assigned = assignedIds.has(j.id);
            return (
              <li
                key={j.id}
                className="flex items-center gap-3 rounded-md border border-border dark:border-border bg-muted dark:bg-card/40 px-3 py-2"
                data-testid={`top-match-${j.id}`}
              >
                <Briefcase className="w-4 h-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <Link
                    href={`/jobs/${j.id}`}
                    className="font-medium text-sm text-foreground dark:text-foreground hover:underline truncate block"
                  >
                    {j.title}
                  </Link>
                  <div className="text-[11px] text-muted-foreground flex items-center gap-2 mt-0.5">
                    {j.location && <span>📍 {j.location}</span>}
                    {j.salary_min && j.salary_max && (
                      <span>
                        💰 {j.salary_min.toLocaleString()}–
                        {j.salary_max.toLocaleString()} PLN
                      </span>
                    )}
                    {j.seniority && <span>🎯 {j.seniority}</span>}
                  </div>
                </div>
                {m.warning && (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-800 border border-yellow-300"
                    title={m.warning}
                  >
                    <AlertTriangle className="w-3 h-3" /> {m.warning}
                  </span>
                )}
                <ScoreChip score={m.total_score} />
                <button
                  onClick={() => handleAssign(j.id)}
                  disabled={assigningJobId === j.id || assigned}
                  className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                    assigned
                      ? "bg-green-100 text-green-700 border-green-300"
                      : "bg-primary text-white border-primary hover:bg-primary/90 disabled:opacity-50"
                  }`}
                  data-testid={`assign-${c.id}-${j.id}`}
                >
                  {assigned ? (
                    "✓ Przypisany"
                  ) : assigningJobId === j.id ? (
                    <Loader2 className="w-3 h-3 animate-spin inline" />
                  ) : (
                    "Przypisz"
                  )}
                </button>
                <div className="relative">
                  <button
                    onClick={() =>
                      setOpenMenuJobId(openMenuJobId === j.id ? null : j.id)
                    }
                    aria-label="Więcej akcji"
                    className="text-muted-foreground hover:text-foreground p-1 rounded"
                    data-testid={`actions-menu-${c.id}-${j.id}`}
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>
                  {openMenuJobId === j.id && (
                    <div className="absolute right-0 top-full mt-1 z-10 bg-card dark:bg-muted border border-border dark:border-border rounded-md shadow-lg w-56">
                      <button
                        onClick={() => handleProposal(j.id)}
                        disabled={actionLoading === `proposal-${j.id}`}
                        className="w-full text-left text-sm px-3 py-2 hover:bg-muted dark:hover:bg-muted flex items-center gap-2 disabled:opacity-50"
                        data-testid={`proposal-${c.id}-${j.id}`}
                      >
                        {actionLoading === `proposal-${j.id}` ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Mail className="w-3 h-3" />
                        )}
                        Wygeneruj propozycję dla klienta
                      </button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Below threshold */}
      {row.below_threshold_count > 0 && (
        <BelowThresholdSection count={row.below_threshold_count} />
      )}

      {draft && (
        <EmailDraftDialog
          title={draft.title}
          to={draft.to}
          subject={draft.subject}
          textBody={draft.textBody}
          htmlBody={draft.htmlBody}
          onClose={() => setDraft(null)}
        />
      )}
    </article>
  );
}

function BelowThresholdSection({ count }: { count: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 pt-3 border-t border-border dark:border-border">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
      >
        <TrendingDown className="w-3 h-3" />
        Słabe dopasowania ({count}){" "}
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {open && (
        <p className="mt-2 text-xs text-muted-foreground italic">
          {count} ofert poniżej progu jakości — kliknij &ldquo;Pokaż wszystkie&rdquo;
          przy karcie aby zobaczyć pełną listę (TODO).
        </p>
      )}
    </div>
  );
}
