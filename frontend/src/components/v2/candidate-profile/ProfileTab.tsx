"use client";

/**
 * Zakładka „Profil” (domyślna). Kolumna główna: jedna karta AI
 * („Podsumowanie”), wiersz CV, umiejętności, doświadczenie i zwinięte
 * „Edukacja, certyfikaty i szczegóły”. Prawa kolumna: „W procesie”
 * i „Ostatnia aktywność”.
 *
 * Fakty z nagłówka (lokalizacja, dostępność, stawka, języki) NIE są tu
 * powtarzane — mają jedno miejsce: pasek faktów pod nagłówkiem.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  GraduationCap,
  Link2,
  Sparkles,
} from "lucide-react";

import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ExpandableText } from "@/components/v2/ExpandableText";
import { LinkedinSyncPanel } from "@/components/v2/LinkedinSyncPanel";
import {
  CvRichProfileSections,
  CvTechnologyChips,
} from "@/components/candidates/CvRichProfileSections";
import { CandidateEngagementPanel } from "@/components/candidates/CandidateEngagementPanel";
import { CandidateLocationPanel } from "@/components/candidates/CandidateLocationPanel";
import { CandidateSourcesPanel } from "@/components/candidates/CandidateSourcesPanel";
import { CvReparseAction } from "@/components/candidates/CvReparseAction";
import {
  FilePreviewModal,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { CandidateActivitySummaryCard } from "@/components/v2/pages/CandidateActivitySummaryCard";
import { CandidateNotesFactsCard } from "@/components/v2/pages/CandidateNotesFactsCard";
import { CandidateRecentRecruitmentsCard } from "@/components/v2/pages/CandidateRecentRecruitmentsCard";
import {
  formatEducationYears,
  formatExperienceDate,
  getCvProjectionNotice,
  getEducationList,
  getExperienceDetails,
  getRichCvProfile,
} from "@/components/v2/pages/candidate-profile-helpers";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { JDGPanel } from "./JdgPanel";
import { RecentActivityList } from "./Timeline";
import { screeningConfirmedSkills } from "./profile-helpers";
import { SectionHeading } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload kandydata jest luźno typowany (importy Traffit, CV) */

const SKILL_LEVEL_VARIANT: Record<string, "burgundy" | "success" | "warning" | "neutral"> = {
  expert: "burgundy",
  senior: "success",
  mid: "warning",
  junior: "neutral",
};

export type ProfileNavigate = (
  target:
    | { section: "recruitments" }
    | { section: "activity" }
    | { section: "documents" },
) => void;

export interface ProfileTabProps {
  candidate: any;
  readOnly: boolean;
  embedded?: boolean;
  recentActivity: { items: any[]; isPending: boolean };
  onNavigate: ProfileNavigate;
  /** Otwiera generator CV firmowego. Brak = brak prawa zapisu. */
  onGenerateCv?: () => void;
  /** >0 = rozwiń szczegóły i przewiń do „Dane do umowy” (z zakładki Umowy). */
  jdgFocusRequest?: number;
  onJdgFocusHandled?: () => void;
}

export function ProfileTab({
  candidate,
  readOnly,
  embedded = false,
  recentActivity,
  onNavigate,
  onGenerateCv,
  jdgFocusRequest = 0,
  onJdgFocusHandled,
}: ProfileTabProps) {
  return (
    <div
      className={cn(
        "grid items-start gap-5",
        !embedded && "@4xl:grid-cols-[minmax(0,1fr)_320px]",
      )}
    >
      <div className="min-w-0 space-y-6">
        <CandidateActivitySummaryCard
          candidateId={candidate.id}
          cvSummary={candidate.ai_summary ?? null}
          title="Podsumowanie"
        />
        <CandidateNotesFactsCard candidateId={candidate.id} readOnly={readOnly} />
        <CvRow
          candidate={candidate}
          readOnly={readOnly}
          onGenerateCv={onGenerateCv}
          onOpenFiles={() => onNavigate({ section: "documents" })}
        />
        <SkillsSection candidate={candidate} />
        <ExperienceSection candidate={candidate} />
        <DetailsSection
          candidate={candidate}
          readOnly={readOnly}
          jdgFocusRequest={jdgFocusRequest}
          onJdgFocusHandled={onJdgFocusHandled}
        />
      </div>

      <aside
        className={cn("space-y-4", !embedded && "@4xl:sticky @4xl:top-4")}
        aria-label="Kontekst profilu kandydata"
      >
        <CandidateRecentRecruitmentsCard
          candidateId={candidate.id}
          title="Ostatnie rekrutacje"
          onShowAll={() => onNavigate({ section: "recruitments" })}
        />
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Ostatnia aktywność</CardTitle>
              <button
                type="button"
                onClick={() => onNavigate({ section: "activity" })}
                className="inline-flex min-h-9 items-center px-1 text-xs font-medium text-primary hover:underline"
              >
                Historia →
              </button>
            </div>
          </CardHeader>
          <CardContent>
            {recentActivity.isPending ? (
              <p className="text-sm text-muted-foreground">Ładowanie…</p>
            ) : (
              <RecentActivityList items={recentActivity.items.slice(0, 2)} />
            )}
          </CardContent>
        </Card>
      </aside>
    </div>
  );
}

/** Wiersz CV: plik, data, podgląd, generator CV firmowego, ponowny odczyt. */
function CvRow({
  candidate,
  readOnly,
  onGenerateCv,
  onOpenFiles,
}: {
  candidate: any;
  readOnly: boolean;
  onGenerateCv?: () => void;
  onOpenFiles: () => void;
}) {
  const { showError } = useToast();
  // Podgląd w modalu (PDF/DOCX/obraz) zamiast pobierania — przeglądarka nie
  // renderuje DOCX inline, więc `window.open` wymuszał download.
  const { data: cvDocs } = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.cvDocuments(candidate.id),
    queryFn: async () => {
      const res = await api.get<CandidateDocument[]>(
        `/api/candidates/${candidate.id}/documents?kind=cv`,
      );
      return res.data;
    },
    enabled: !!candidate.id,
    staleTime: 30_000,
  });
  const [previewDoc, setPreviewDoc] = useState<CandidateDocument | null>(null);
  const openCv = () => {
    const docs = cvDocs ?? [];
    const primary =
      docs.find((d) => d.is_primary) ??
      docs.find((d) => d.filename === candidate.cv_filename) ??
      docs[0];
    if (primary) setPreviewDoc(primary);
    else onOpenFiles();
  };
  const notice = getCvProjectionNotice(candidate);

  return (
    <section aria-label="CV kandydata">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-background/40 p-3">
        <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          {candidate.cv_filename ? (
            <>
              <div className="truncate text-sm font-medium text-foreground">
                {candidate.cv_filename}
              </div>
              {candidate.cv_parsed_at ? (
                <div className="text-[11px] text-muted-foreground">
                  Odczytane {formatRelativeTime(candidate.cv_parsed_at)}
                </div>
              ) : null}
            </>
          ) : (
            <span className="text-sm text-muted-foreground">Brak CV w profilu</span>
          )}
        </div>
        {candidate.cv_filename ? (
          <Button size="sm" variant="outline" onClick={openCv}>
            Podgląd
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={onOpenFiles}>
            Pliki →
          </Button>
        )}
        {!readOnly && onGenerateCv ? (
          <Button size="sm" variant="outline" onClick={onGenerateCv}>
            <Sparkles className="h-3.5 w-3.5" />
            Generuj CV firmowe
          </Button>
        ) : null}
      </div>
      {notice ? (
        <p
          role="status"
          className={cn(
            "mt-2 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
            notice.tone === "warning"
              ? "border-warning/30 bg-warning-muted text-warning-muted-foreground"
              : "border-border bg-muted/40 text-muted-foreground",
          )}
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="space-y-2">
            <span className="block">{notice.text}</span>
            {notice.kind === "not_parsed" && !readOnly ? (
              <CvReparseAction candidateId={candidate.id} />
            ) : null}
          </span>
        </p>
      ) : null}
      <FilePreviewModal
        documents={cvDocs ?? []}
        initialDocumentId={previewDoc?.id ?? null}
        candidateId={candidate.id}
        onClose={() => setPreviewDoc(null)}
        onDownload={(d) =>
          downloadDocumentBlob(candidate.id, d).catch(() =>
            showError("Nie udało się pobrać pliku."),
          )
        }
      />
    </section>
  );
}

/**
 * Umiejętności z CV z zaznaczeniem potwierdzonych na screeningu (profil
 * `verified_tech` + agregat screeningów). Potwierdzona technologia spoza CV
 * dostaje własny chip — nie może zniknąć tylko dlatego, że CV jej nie ma.
 */
function SkillsSection({ candidate }: { candidate: any }) {
  const skills: any[] = Array.isArray(candidate.skills) ? candidate.skills : [];
  const aiProfileQuery = useQuery<any>({
    queryKey: candidateQueryKeys.aiProfile(candidate.id),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidate.id}/ai-profile`, { signal })
        .then((r) => r.data),
    enabled: !!candidate.id,
    staleTime: 60_000,
  });
  const confirmed = useMemo(
    () =>
      screeningConfirmedSkills(
        candidate.verified_tech,
        aiProfileQuery.data?.verified_skills_aggregate,
      ),
    [candidate.verified_tech, aiProfileQuery.data],
  );
  const confirmedSet = useMemo(
    () => new Set(confirmed.map((name) => name.toLowerCase())),
    [confirmed],
  );
  const skillNames = new Set(
    skills.map((s: any) => String(s?.name ?? "").toLowerCase()).filter(Boolean),
  );
  const confirmedOnly = confirmed.filter((name) => !skillNames.has(name.toLowerCase()));

  if (skills.length === 0 && confirmed.length === 0) return null;

  return (
    <section aria-labelledby="candidate-skills-heading">
      <SectionHeading id="candidate-skills-heading">Umiejętności</SectionHeading>
      <ul className="flex flex-wrap gap-2">
        {skills.map((s: any, i: number) => {
          const isConfirmed = s?.name && confirmedSet.has(String(s.name).toLowerCase());
          return (
            <li
              key={`${s?.name ?? "skill"}-${i}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5"
            >
              {isConfirmed ? (
                <CheckCircle2
                  className="h-3.5 w-3.5 text-success"
                  aria-label="potwierdzone na screeningu"
                />
              ) : null}
              <span className="text-sm font-medium text-foreground">{s?.name}</span>
              {s?.level ? (
                <Badge size="sm" variant={SKILL_LEVEL_VARIANT[s.level] ?? "neutral"}>
                  {s.level}
                </Badge>
              ) : null}
              {s?.years ? (
                <span className="text-[10px] text-muted-foreground">{s.years} l.</span>
              ) : null}
            </li>
          );
        })}
        {confirmedOnly.map((name) => (
          <li
            key={`confirmed-${name}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5"
          >
            <CheckCircle2
              className="h-3.5 w-3.5 text-success"
              aria-label="potwierdzone na screeningu"
            />
            <span className="text-sm font-medium text-foreground">{name}</span>
          </li>
        ))}
      </ul>
      {confirmed.length > 0 ? (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <CheckCircle2 className="h-3 w-3 text-success" aria-hidden="true" />
          potwierdzone na screeningu
        </p>
      ) : null}
    </section>
  );
}

function ExperienceSection({ candidate }: { candidate: any }) {
  // Backfill (maj 2026) wstawia pusty placeholder na experience[0] dla
  // kandydatów z Traffita — bez pustej karty.
  const experience: any[] = (
    Array.isArray(candidate.experience) ? candidate.experience : []
  ).filter((e: any) => {
    if (!e || typeof e !== "object") return false;
    return Boolean(
      e.role || e.title || e.company || e.start || e.start_date ||
        e.end || e.end_date || e.desc || e.description,
    );
  });
  if (experience.length === 0) return null;
  const aiSource: string = candidate.cv_extracted_data?._source ?? "";
  const aiBadge = aiSource.startsWith("claude") || aiSource.startsWith("ollama");

  return (
    <section aria-labelledby="candidate-experience-heading">
      <SectionHeading
        id="candidate-experience-heading"
        action={
          aiBadge ? (
            <Badge size="sm" variant="info">
              z CV (AI)
            </Badge>
          ) : undefined
        }
      >
        Doświadczenie
      </SectionHeading>
      <div className="space-y-3">
        {experience.map((exp: any, i: number) => {
          const role = exp.role ?? exp.title ?? "";
          const company = exp.company ?? "";
          const start = exp.start ?? exp.start_date ?? "";
          const end = exp.end ?? exp.end_date ?? "";
          const desc = exp.desc ?? exp.description ?? "";
          const expLoc = exp.location ?? "";
          const details = getExperienceDetails(exp);
          return (
            <div key={i} className="rounded-lg border border-border bg-background/40 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  {role ? <div className="font-medium text-foreground">{role}</div> : null}
                  <div className="text-xs text-muted-foreground">
                    {company}
                    {details.client ? ` (dla: ${details.client})` : ""}
                    {expLoc ? ` · ${expLoc}` : ""}
                    {details.employmentType ? ` · ${details.employmentType}` : ""}
                  </div>
                </div>
                {start || end ? (
                  <div className="whitespace-nowrap text-xs text-muted-foreground">
                    {formatExperienceDate(start)} —{" "}
                    {formatExperienceDate(end) || "obecnie"}
                  </div>
                ) : null}
              </div>
              {desc ? <ExpandableText text={desc} maxLines={2} className="mt-2" /> : null}
              <CvTechnologyChips items={details.technologies} />
            </div>
          );
        })}
      </div>
    </section>
  );
}

/**
 * Zwinięte „Edukacja, certyfikaty i szczegóły”: edukacja, pełny profil
 * z odczytu CV v7, „O sobie”, źródło zaproszenia, a dla osób z prawem zapisu
 * panele administracyjne (zaangażowanie, lokalizacja szczegółowa, źródła,
 * dane do umowy JDG, synchronizacja LinkedIn).
 */
function DetailsSection({
  candidate,
  readOnly,
  jdgFocusRequest,
  onJdgFocusHandled,
}: {
  candidate: any;
  readOnly: boolean;
  jdgFocusRequest: number;
  onJdgFocusHandled?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const education = getEducationList(candidate);
  const richCvProfile = getRichCvProfile(candidate);

  // „Uzupełnij dane do umowy” z zakładki Umowy: rozwiń i przewiń do JDG.
  const handledRef = useRef(0);
  useEffect(() => {
    if (jdgFocusRequest <= 0 || readOnly) return;
    if (!open) {
      setOpen(true);
      return;
    }
    if (handledRef.current === jdgFocusRequest) return;
    const el = document.getElementById("candidate-jdg-panel");
    if (!el) return;
    handledRef.current = jdgFocusRequest;
    el.scrollIntoView?.({ block: "start" });
    el.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
    onJdgFocusHandled?.();
  }, [jdgFocusRequest, open, readOnly, onJdgFocusHandled]);

  // Stabilne referencje — nowy literał w każdym renderze resetował wpisywany
  // tekst (panele synchronizują się z `initial`).
  const engagementInitial = useMemo(
    () => ({
      is_ambassador: candidate.is_ambassador,
      wants_to_verify_candidates: candidate.wants_to_verify_candidates,
      open_to_side_projects: candidate.open_to_side_projects,
      open_to_sales_support: candidate.open_to_sales_support,
      open_to_expert_consult: candidate.open_to_expert_consult,
      open_to_side_projects_updated_at: candidate.open_to_side_projects_updated_at,
      open_to_sales_support_updated_at: candidate.open_to_sales_support_updated_at,
      open_to_expert_consult_updated_at: candidate.open_to_expert_consult_updated_at,
      engagement_notes: candidate.engagement_notes,
    }),
    [
      candidate.is_ambassador,
      candidate.wants_to_verify_candidates,
      candidate.open_to_side_projects,
      candidate.open_to_sales_support,
      candidate.open_to_expert_consult,
      candidate.open_to_side_projects_updated_at,
      candidate.open_to_sales_support_updated_at,
      candidate.open_to_expert_consult_updated_at,
      candidate.engagement_notes,
    ],
  );
  const locationInitial = useMemo(
    () => ({
      city: candidate.city,
      country: candidate.country,
      region: candidate.region,
      hub_city: candidate.hub_city,
    }),
    [candidate.city, candidate.country, candidate.region, candidate.hub_city],
  );
  const jdgInitial = useMemo(
    () => ({
      legal_name: candidate.legal_name,
      nip: candidate.nip,
      regon: candidate.regon,
      business_address: candidate.business_address,
      business_form: candidate.business_form,
    }),
    [
      candidate.legal_name,
      candidate.nip,
      candidate.regon,
      candidate.business_address,
      candidate.business_form,
    ],
  );

  const invite = candidate.invite_source;
  const hasContent =
    !readOnly ||
    education.length > 0 ||
    Boolean(richCvProfile) ||
    Boolean(candidate.about) ||
    Boolean(invite);
  if (!hasContent) return null;

  return (
    <section className="rounded-lg border border-border" aria-labelledby="candidate-details-toggle">
      <button
        id="candidate-details-toggle"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center justify-between px-3 text-sm font-medium text-foreground hover:bg-background/40"
        aria-expanded={open}
      >
        Edukacja, certyfikaty i szczegóły
        {open ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open ? (
        <div className="space-y-5 border-t border-border p-3">
          {education.length > 0 ? (
            <div>
              <SectionHeading>
                <span className="inline-flex items-center gap-2">
                  <GraduationCap className="h-3.5 w-3.5" />
                  Wykształcenie
                </span>
              </SectionHeading>
              <div className="space-y-2">
                {education.map((edu, i) => (
                  <div key={i} className="rounded-lg border border-border bg-background/40 p-3">
                    <div className="text-sm font-medium text-foreground">
                      {edu.degree || edu.field || "—"}
                      {edu.field && edu.degree ? ` · ${edu.field}` : ""}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {edu.school}
                      {formatEducationYears(edu) ? ` · ${formatEducationYears(edu)}` : ""}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {richCvProfile ? <CvRichProfileSections profile={richCvProfile} /> : null}

          {candidate.about ? (
            <div>
              <SectionHeading>O sobie</SectionHeading>
              <ExpandableText text={candidate.about} maxLines={3} />
            </div>
          ) : null}

          {invite ? (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
              {invite.previous_created_by_name
                ? `Przez link rekrutera — przejęty: ${invite.previous_created_by_name} → ${invite.created_by_name}`
                : `Dodany przez link rekrutera: ${invite.created_by_name}`}
              {invite.label ? ` · ${invite.label}` : ""}
              {invite.applied_at ? ` (${formatDate(invite.applied_at)})` : ""}
            </p>
          ) : null}

          {!readOnly ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <CandidateEngagementPanel candidateId={candidate.id} initial={engagementInitial} />
                <CandidateLocationPanel candidateId={candidate.id} initial={locationInitial} />
              </div>
              <div className="rounded-xl border border-border bg-card p-4">
                <CandidateSourcesPanel candidateId={candidate.id} />
              </div>
              <JDGPanel candidateId={candidate.id} initial={jdgInitial} />
              <LinkedinSyncPanel candidate={candidate} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
