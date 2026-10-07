"use client";

/**
 * „Profil Championa” → zakładka „Brief” (04.10.2026, makieta
 * https://claude.ai/artifact/FwQr2uYhWcRfdDeWdbStUc).
 *
 * To, co rekruter musi wiedzieć przed telefonem, na jednym ekranie: jednym
 * zdaniem o co chodzi, czego szukamy, pytania na rozmowę, co powiedzieć
 * kandydatowi, a w prawej kolumnie warunki, kto prowadzi i co dopytać
 * u klienta. Do 04.10.2026 była to jedna długa strona „Podgląd” (ok. 5 000 px)
 * — słowniczek przeszedł do „Technologie po ludzku”, klient i historia do
 * „Klient i historia”.
 *
 * Tylko odczyt. Profil idzie spod TEGO SAMEGO klucza co edytor
 * (`["champion-profile", jobId]`). „Edytuj” przy bloku otwiera szufladę
 * z sekcjami tego bloku (`onEditBlock`).
 */

import type { ReactNode } from "react";
import { PencilLine } from "lucide-react";

import { Chips, Fact, stackNames } from "@/components/champion/BriefParts";
import { ExperienceChips, useChampionProfile } from "@/components/champion/ChampionBriefForRecruiters";
import { SearchRequirementsEditor } from "@/components/champion/SearchRequirementsEditor";
import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { usePlainBrief } from "@/lib/api/plainKnowledge";
import type { ChampionBlock } from "@/lib/champion-blocks";
import { JOB_WORK_MODE_LABEL, seedChampionFromJob } from "@/lib/champion-job-seed";
import { criticalBriefLine } from "@/lib/critical-skills";
import { formatBudgetHourly, formatJobBudgetLabel, type JobBudgetSource } from "@/lib/job-budget";
import { formatJobDeadline } from "@/lib/job-deadline";
import { recruitersOf, workingRecruiters, type JobTeamSource } from "@/lib/job-team";
import { officeDaysLabel } from "@/lib/office-days";
import { buildGlossaryLookup } from "@/lib/plain-glossary-lookup";
import { resolveViewState } from "@/lib/view-state";

/** Pola rekrutacji, które Brief czyta obok profilu. */
export interface ChampionBriefJob extends JobTeamSource, JobBudgetSource {
  title?: string | null;
  client_id?: number | null;
  client_name?: string | null;
  client_reference?: string | null;
  deadline?: string | null;
  deadline_time?: string | null;
  description?: string | null;
  hiring_manager_name?: string | null;
  delivery_lead_user?: { name?: string | null } | null;
}

export interface ChampionBriefViewProps {
  jobId: number;
  job: ChampionBriefJob;
  /** Brak = rola nie edytuje Championa — przycisków „Edytuj” nie ma. */
  onEditBlock?: (block: ChampionBlock) => void;
  /** „Szukaj ręcznie w bazie” — start od wymagań do wyszukiwania. */
  onOpenManualSearch?: () => void;
  /** „Zmień →” przy „Kto prowadzi” — zakładka „Zespół i ogłoszenie”. */
  onOpenTeam?: () => void;
  /** „Więcej o kliencie” — zakładka „Klient i historia”. */
  onOpenClient?: () => void;
}

/** Kotwice sekcji edytora (`ChampionProfileEditor`, `id=` na kartach). */
export const CHAMPION_EDIT_ANCHOR = {
  basics: "champion-section-basics",
  search: "champion-section-search",
  stack: "champion-section-stack",
  project: "champion-section-project",
  screening: "champion-section-screening",
  client: "champion-section-client",
  insights: "champion-section-insights",
} as const;

const SCREENING_PREVIEW = 3;

export function BriefSection({
  title,
  action,
  onEdit,
  children,
  testId,
  className,
}: {
  title: string;
  action?: ReactNode;
  onEdit?: () => void;
  children: ReactNode;
  testId?: string;
  className?: string;
}) {
  return (
    <section
      className={`space-y-2.5 rounded-xl border border-border bg-card px-4 py-3.5 ${className ?? ""}`}
      data-testid={testId}
      aria-label={title}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[14px] font-semibold text-foreground">{title}</h2>
        <div className="flex items-center gap-3">
          {action}
          {onEdit ? (
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-primary"
              aria-label={`Edytuj: ${title}`}
            >
              <PencilLine className="h-3.5 w-3.5" aria-hidden="true" />
              Edytuj
            </button>
          ) : null}
        </div>
      </div>
      {children}
    </section>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </p>
  );
}

function provenanceLabel(profile: Partial<ChampionProfile>): string | null {
  if (!profile._source) return null;
  return profile._parser?.includes("table-intake") ? "z dokumentu" : "z opisu klienta (AI)";
}

export function ChampionBriefView({
  jobId,
  job,
  onEditBlock,
  onOpenManualSearch,
  onOpenTeam,
  onOpenClient,
}: ChampionBriefViewProps) {
  const query = useChampionProfile(jobId);
  const plainQuery = usePlainBrief(jobId);
  const cvRuleQuery = useClientCvRule(job.client_id ?? null);
  const cvLanguage = cvRuleQuery.data?.is_active ? (cvRuleQuery.data.cv_language ?? null) : null;
  const glossary = buildGlossaryLookup(plainQuery.data?.glossary);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }
  if (state !== "ready" && state !== "empty") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }

  // Ten sam profil, na który patrzy edytor: dla profili sprzed 09.2026 stack
  // i podstawy (budżet, tryb pracy) wczytujemy z kolumn rekrutacji
  // (`seedChampionFromJob`, M04-B02).
  const profile: Partial<ChampionProfile> = query.data
    ? seedChampionFromJob(
        {
          ...EMPTY_CHAMPION_PROFILE,
          ...(query.data.champion_profile as Partial<ChampionProfile>),
        },
        query.data.job_values,
        query.data.job_title,
      ).profile
    : {};
  const basics = profile.basics ?? {};
  const must = stackNames(profile.stack?.must);
  // Krytyczne (30.09.2026): decyzja DL albo podpowiedź, na której działa bramka.
  const criticalResolution = query.data?.critical_resolution ?? null;
  const criticalLine = criticalBriefLine(criticalResolution);
  const nice = stackNames(profile.stack?.nice);
  const questions = profile.screening_questions ?? [];
  const search = profile.search;
  const requirements = search?.requirements ?? [];
  const source = provenanceLabel(profile);
  const edit = (block: ChampionBlock) => (onEditBlock ? () => onEditBlock(block) : undefined);
  const workMode = basics.work_mode
    ? (JOB_WORK_MODE_LABEL[basics.work_mode] ?? basics.work_mode)
    : null;
  const office = [
    basics.onsite_days_per_month
      ? `${officeDaysLabel(null, basics.onsite_days_per_month)} w biurze`
      : basics.onsite_days_per_week
        ? `${basics.onsite_days_per_week} dni w biurze`
        : null,
    basics.candidate_location_pref?.trim() || null,
  ]
    .filter(Boolean)
    .join(" · ");
  const projectAbout = profile.project?.about?.trim() ?? "";
  const responsibilities = (profile.project?.responsibilities ?? "")
    .split(/\n|;/)
    .map((line) => line.replace(/^[-•*]\s*/, "").trim())
    .filter(Boolean);
  const experienceCount =
    (profile.experience?.domains?.length ?? 0) +
    (profile.experience?.certifications?.length ?? 0) +
    (profile.experience?.regulations?.length ?? 0);
  const recruiterNames = workingRecruiters(recruitersOf(job)).map((p) => p.name);
  const sellingPoints = profile.client?.selling_points?.trim() ?? "";

  return (
    <TooltipProvider delayDuration={150}>
      <div
        className="grid grid-cols-1 gap-3.5 xl:grid-cols-[minmax(0,1fr)_300px]"
        data-testid="champion-brief-view"
      >
        <div className="min-w-0 space-y-3.5">
          {/* „Jednym zdaniem” (dawny blok „Po ludzku”, skrócony): słowniczek
              jest w „Technologie po ludzku”, opis klienta w „Klient i historia”. */}
          <PlainBriefBlock jobId={jobId} parts="summary" compact />

          <BriefSection
            title="Czego szukamy"
            onEdit={edit("search")}
            action={
              onOpenManualSearch ? (
                <button
                  type="button"
                  onClick={onOpenManualSearch}
                  className="text-[13px] font-medium text-primary hover:underline"
                >
                  Szukaj w bazie →
                </button>
              ) : null
            }
            testId="brief-search"
          >
            <div className="space-y-1.5">
              <Eyebrow>Musi mieć</Eyebrow>
              {must.length > 0 ? (
                <Chips items={must} tone="must" critical={criticalResolution?.effective ?? []} glossary={glossary} />
              ) : (
                <p className="text-[13px] text-muted-foreground">— brak</p>
              )}
              {criticalLine ? (
                <p
                  className={
                    criticalResolution?.decided
                      ? "text-[13px] text-muted-foreground"
                      : "text-[13px] text-warning-muted-foreground"
                  }
                  data-testid="brief-critical"
                >
                  {criticalLine}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Eyebrow>Mile widziane</Eyebrow>
              {nice.length > 0 ? (
                <Chips items={nice} tone="nice" glossary={glossary} />
              ) : (
                <p className="text-[13px] text-muted-foreground">— brak</p>
              )}
            </div>
            {experienceCount > 0 ? (
              <div className="space-y-1.5">
                <Eyebrow>Doświadczenie poza stackiem</Eyebrow>
                <ExperienceChips experience={profile.experience} />
              </div>
            ) : null}
            {profile.stack?.notes?.trim() ? (
              <p className="text-[13px] text-muted-foreground">Niuanse: {profile.stack.notes}</p>
            ) : null}
            <details className="rounded-lg bg-muted/50 px-3 py-2" data-testid="brief-search-requirements">
              <summary className="cursor-pointer text-[13px] font-medium text-muted-foreground hover:text-foreground">
                {requirements.length > 0
                  ? `Wymagania do wyszukiwania w bazie (${requirements.length})`
                  : "Wymagania do wyszukiwania w bazie — brak"}
              </summary>
              <div className="mt-2 space-y-1.5">
                {requirements.length > 0 ? (
                  <SearchRequirementsEditor
                    rows={requirements}
                    exclude={search?.exclude ?? []}
                    onChange={() => undefined}
                    readOnly
                    countEnabled={false}
                  />
                ) : (
                  <p className="text-[13px] text-muted-foreground">
                    Bez nich rekrutacja nie przejdzie do searchu.
                  </p>
                )}
                {search?.target_companies?.trim() ? (
                  <p className="text-xs text-muted-foreground">Firmy docelowe: {search.target_companies}</p>
                ) : null}
                {(search?.disqualifiers ?? []).length > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Kogo odrzucamy: {(search?.disqualifiers ?? []).join(", ")}
                  </p>
                ) : null}
              </div>
            </details>
          </BriefSection>

          <BriefSection
            title={`Pytania na rozmowę (${questions.length})`}
            onEdit={edit("screening")}
            testId="brief-screening"
          >
            {questions.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">Brak pytań screeningowych.</p>
            ) : (
              <ScreeningList questions={questions} />
            )}
          </BriefSection>

          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
            <BriefSection title="Co powiedzieć kandydatowi" onEdit={edit("client")} testId="brief-pitch">
              <p className={sellingPoints ? "text-sm text-foreground" : "text-[13px] text-muted-foreground"}>
                {sellingPoints || "— brak"}
              </p>
              {onOpenClient ? (
                <button
                  type="button"
                  onClick={onOpenClient}
                  className="text-[13px] font-medium text-primary hover:underline"
                >
                  Więcej o kliencie →
                </button>
              ) : null}
            </BriefSection>

            <BriefSection title="O projekcie" onEdit={edit("project")} testId="brief-project">
              {projectAbout ? (
                <p className="line-clamp-3 text-sm leading-relaxed text-foreground">{projectAbout}</p>
              ) : (
                <p className="text-[13px] text-muted-foreground">Delivery Lead nie opisał jeszcze projektu.</p>
              )}
              {responsibilities.length > 0 ? (
                <details className="text-sm">
                  <summary className="cursor-pointer text-[13px] text-muted-foreground hover:text-foreground">
                    Obowiązki ({responsibilities.length})
                  </summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-foreground">
                    {responsibilities.map((line, i) => (
                      <li key={`${i}-${line}`}>{line}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </BriefSection>
          </div>
        </div>

        <aside className="min-w-0 space-y-3.5" aria-label="Warunki i zespół">
          <BriefSection
            title="Warunki"
            onEdit={edit("conditions")}
            action={
              source ? (
                <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  {source}
                </span>
              ) : null
            }
            testId="brief-order"
          >
            <dl className="divide-y divide-border/60">
              <Fact
                label="Budżet"
                value={
                  // Przedział „od–do” z rekrutacji (0420); bez niego — stawka profilu.
                  formatJobBudgetLabel(job) ??
                  (basics.rate_value != null ? `do ${formatBudgetHourly(basics.rate_value)} PLN/h` : "nie podano")
                }
                muted={basics.rate_value == null && formatJobBudgetLabel(job) == null}
              />
              <Fact
                label="Tryb i biuro"
                value={[workMode, office].filter(Boolean).join(" · ") || "nie podano"}
                muted={!workMode && !office}
              />
              <Fact label="Start" value={basics.start_date?.trim() || "nie podano"} muted={!basics.start_date} />
              <Fact label="Długość" value={basics.contract_length?.trim() || "nie podano"} muted={!basics.contract_length} />
              <Fact
                label="Doświadczenie"
                value={basics.seniority_min_years != null ? `${basics.seniority_min_years}+ lat` : "nie podano"}
                muted={basics.seniority_min_years == null}
              />
              <Fact label="Język pracy" value={basics.language?.trim() || "nie podano"} muted={!basics.language} />
              <Fact
                label="Język CV"
                value={cvLanguage ? `${cvLanguage.toUpperCase()} (reguła klienta)` : "brak reguły klienta"}
                muted={!cvLanguage}
              />
              <Fact
                label="Termin"
                value={formatJobDeadline(job.deadline, job.deadline_time) ?? "nie ustawiono"}
                muted={!job.deadline}
              />
              <Fact label="Nazwa od klienta" value={job.title?.trim() || "—"} />
              <Fact
                label="Numer u klienta"
                value={job.client_reference?.trim() || "nie podano"}
                muted={!job.client_reference}
              />
            </dl>
            {job.description?.trim() ? (
              <details className="text-sm">
                <summary className="cursor-pointer text-[13px] text-muted-foreground hover:text-foreground">
                  Oryginalny opis od klienta
                </summary>
                <p className="mt-2 max-h-80 overflow-y-auto whitespace-pre-line text-[13px] leading-relaxed text-foreground">
                  {job.description}
                </p>
              </details>
            ) : null}
          </BriefSection>

          <BriefSection
            title="Kto prowadzi"
            action={
              onOpenTeam ? (
                <button
                  type="button"
                  onClick={onOpenTeam}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  Zespół →
                </button>
              ) : null
            }
            testId="brief-team"
          >
            <dl className="divide-y divide-border/60">
              <Fact
                label="Delivery Lead"
                value={job.delivery_lead_user?.name?.trim() || "nie przypisano"}
                muted={!job.delivery_lead_user?.name}
              />
              <Fact
                label="Rekruter"
                value={recruiterNames.length > 0 ? recruiterNames.join(", ") : "bez rekrutera"}
                muted={recruiterNames.length === 0}
              />
              <Fact
                label="Hiring manager"
                value={job.hiring_manager_name?.trim() || "nie przypisano"}
                muted={!job.hiring_manager_name}
              />
            </dl>
          </BriefSection>

          <AskClientList profile={profile} onEdit={edit("insights")} />
        </aside>
      </div>
    </TooltipProvider>
  );
}

function ScreeningList({ questions }: { questions: ChampionProfile["screening_questions"] }) {
  const first = questions.slice(0, SCREENING_PREVIEW);
  const rest = questions.slice(SCREENING_PREVIEW);
  const item = (q: ChampionProfile["screening_questions"][number], index: number) => (
    <li key={q.id || `${index}-${q.question}`} className="border-t border-border py-2 first:border-t-0 first:pt-0">
      <p className="text-sm font-medium text-foreground">
        {index + 1}. {q.question}
      </p>
      {q.ideal_answer?.trim() ? (
        <p className="mt-0.5 text-[13px] text-muted-foreground">Idealnie: {q.ideal_answer}</p>
      ) : null}
      {q.deal_breaker?.trim() ? (
        <p className="mt-0.5 text-[13px] text-destructive-muted-foreground">Odpada, gdy: {q.deal_breaker}</p>
      ) : null}
    </li>
  );
  return (
    <div>
      <ol className="list-none">{first.map(item)}</ol>
      {rest.length > 0 ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-[13px] font-medium text-muted-foreground hover:text-foreground">
            Pokaż {rest.length} kolejne
          </summary>
          <ol className="mt-2 list-none">{rest.map((q, i) => item(q, i + SCREENING_PREVIEW))}</ol>
        </details>
      ) : null}
    </div>
  );
}

/** „Do dopytania u klienta” (notatki `ask_client`) — odhacza się w edycji. */
export function AskClientList({
  profile,
  onEdit,
}: {
  profile: Partial<ChampionProfile>;
  onEdit?: () => void;
}) {
  const items = (profile.insights ?? []).filter((n) => n.topic === "ask_client" && n.text.trim());
  if (items.length === 0) return null;
  return (
    <section
      className="space-y-1.5 rounded-xl border border-warning/40 bg-warning-muted px-4 py-3"
      aria-label="Do dopytania u klienta"
      data-testid="brief-ask-client"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-warning-muted-foreground">
          Do dopytania u klienta · {items.length}
        </p>
        {onEdit ? (
          <button
            type="button"
            onClick={onEdit}
            className="text-xs font-medium text-muted-foreground hover:text-primary"
            aria-label="Edytuj: Do dopytania u klienta"
          >
            Edytuj
          </button>
        ) : null}
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-foreground">
        {items.map((n) => (
          <li key={n.id}>{n.text}</li>
        ))}
      </ul>
    </section>
  );
}
