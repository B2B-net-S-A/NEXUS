"use client";

/**
 * „Zlecenie i Champion” → tryb „Podgląd” (makieta 29.09.2026): zlecenie
 * czytane jak brief, nie jak formularz. Do tej pory rekruter dostawał wyłącznie
 * edytor — ten sam formularz co Delivery Lead, z pustymi polami i polami
 * w kolejności 1, 3, 4, 2, 5…
 *
 * Tylko odczyt. Profil idzie spod TEGO SAMEGO klucza co edytor
 * (`["champion-profile", jobId]`), więc po zapisie w „Edytuj” oba widoki są
 * spójne. Każda sekcja z przyciskiem „Edytuj” prowadzi do tej samej sekcji
 * w trybie edycji — niczego nie da się tu zmienić po cichu.
 */

import type { ReactNode } from "react";
import { PencilLine, Star } from "lucide-react";

import {
  ChampionInsightsDigest,
  ExperienceChips,
  useChampionProfile,
} from "@/components/champion/ChampionBriefForRecruiters";
import { SearchRequirementsEditor } from "@/components/champion/SearchRequirementsEditor";
import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { ChampionClientQuestionsPanel } from "@/components/ChampionClientQuestionsPanel";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import { ClientPlaybookCard } from "@/components/client-playbook/ClientPlaybookCard";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { clientPlaybookEditHref } from "@/lib/client-playbooks";
import { JOB_WORK_MODE_LABEL, seedChampionFromJob } from "@/lib/champion-job-seed";
import { formatBudgetHourly } from "@/lib/job-budget";
import { criticalBriefLine, includesLabel } from "@/lib/critical-skills";
import { formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { officeDaysLabel } from "@/lib/office-days";

/** Pola rekrutacji, które Podgląd czyta obok profilu. */
export interface ChampionBriefJob {
  title?: string | null;
  client_id?: number | null;
  client_name?: string | null;
  client_reference?: string | null;
  deadline?: string | null;
  description?: string | null;
}

export interface ChampionBriefViewProps {
  jobId: number;
  job: ChampionBriefJob;
  /** Brak = rola nie edytuje Championa — przycisków „Edytuj” nie ma. */
  onEditSection?: (anchor: string) => void;
  /** „Szukaj ręcznie w bazie” — start od wymagań z sekcji 2. */
  onOpenManualSearch?: () => void;
  /**
   * Wcześniejsze zapytania tego klienta (Otwórz, Skopiuj jako template).
   * Do 29.09.2026 zakładka „Historia” panelu — widziała ją każda rola, więc
   * Podgląd też. `null` = sekcji nie ma (harness, testy).
   */
  requestHistory?: { readOnly: boolean } | null;
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

function Section({
  title,
  source,
  action,
  onEdit,
  children,
  testId,
}: {
  title: string;
  source?: string | null;
  action?: ReactNode;
  onEdit?: () => void;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-card px-5 py-4"
      data-testid={testId}
      aria-label={title}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
        <div className="flex items-center gap-3">
          {source ? (
            <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
              {source}
            </span>
          ) : null}
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

function Fact({ label, value, muted = false }: { label: string; value: ReactNode; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={muted ? "mt-0.5 text-sm text-muted-foreground" : "mt-0.5 text-sm font-medium text-foreground"}>
        {value}
      </dd>
    </div>
  );
}

function Chips({
  items,
  tone,
  critical = [],
}: {
  items: string[];
  tone: "must" | "nice";
  /** Pozycje, na których działa bramka (gwiazdka „krytyczna”). */
  critical?: readonly string[];
}) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((name) => {
        const isCritical = includesLabel(critical, name);
        return (
          <li
            key={`${tone}:${name}`}
            className={
              tone === "must"
                ? `inline-flex h-[26px] items-center gap-1 rounded-full bg-primary/10 px-2.5 text-xs font-medium text-primary${isCritical ? " ring-1 ring-primary" : ""}`
                : "inline-flex h-[26px] items-center rounded-full bg-muted px-2.5 text-xs font-medium text-muted-foreground"
            }
            data-critical={isCritical || undefined}
          >
            {isCritical ? <Star className="h-3 w-3 fill-current" aria-hidden /> : null}
            {name}
            {isCritical ? <span className="sr-only"> — krytyczna</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </p>
  );
}

function stackNames(items: ChampionProfile["stack"]["must"] | undefined): string[] {
  return (items ?? []).map((item) => item?.name?.trim() ?? "").filter(Boolean);
}

function provenanceLabel(profile: Partial<ChampionProfile>): string | null {
  if (!profile._source) return null;
  return profile._parser?.includes("table-intake") ? "z dokumentu" : "z opisu klienta (AI)";
}

export function ChampionBriefView({
  jobId,
  job,
  onEditSection,
  onOpenManualSearch,
  requestHistory = null,
}: ChampionBriefViewProps) {
  const query = useChampionProfile(jobId);
  const cvRuleQuery = useClientCvRule(job.client_id ?? null);
  const cvLanguage = cvRuleQuery.data?.is_active ? (cvRuleQuery.data.cv_language ?? null) : null;

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
  // (`seedChampionFromJob`, M04-B02). Surowy `champion_profile` dawał
  // rekruterowi „brak wymagań” tam, gdzie „Edytuj” pokazywał listę technologii.
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
  const edit = (anchor: string) => () => onEditSection?.(anchor);
  const clientId = job.client_id ?? null;
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

  return (
    <div className="min-w-0 space-y-3.5" data-testid="champion-brief-view">
      {/* „Po ludzku” (29.09.2026): wyjaśnienie rekrutacji dla rekrutera bez
          zaplecza technicznego — przed brief, bo od niego zaczyna się czytanie. */}
      <PlainBriefBlock jobId={jobId} />
      <Section
        title="Co zamówił klient"
        source={source}
        onEdit={onEditSection ? edit(CHAMPION_EDIT_ANCHOR.basics) : undefined}
        testId="brief-order"
      >
        <dl className="grid grid-cols-2 gap-x-5 gap-y-3.5 sm:grid-cols-4">
          <Fact
            label="Budżet (sufit)"
            value={basics.rate_value != null ? `do ${formatBudgetHourly(basics.rate_value)} PLN/h` : "nie podano"}
            muted={basics.rate_value == null}
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
          <Fact label="Język CV" value={cvLanguage ? `${cvLanguage.toUpperCase()} (reguła klienta)` : "brak reguły klienta"} muted={!cvLanguage} />
          <Fact
            label="Termin dla klienta"
            value={job.deadline ? formatDate(job.deadline) : "nie ustawiono"}
            muted={!job.deadline}
          />
          <Fact label="Nazwa od klienta" value={job.title?.trim() || "—"} />
          <Fact label="Numer u klienta" value={job.client_reference?.trim() || "nie podano"} muted={!job.client_reference} />
          <Fact label="Klient" value={job.client_name?.trim() || "—"} />
        </dl>
        {job.description?.trim() ? (
          <details className="text-sm">
            <summary className="cursor-pointer text-[13px] text-muted-foreground hover:text-foreground">
              Oryginalny opis od klienta
            </summary>
            <p className="mt-2 whitespace-pre-line text-[13px] leading-relaxed text-foreground">
              {job.description}
            </p>
          </details>
        ) : null}
      </Section>

      <Section
        title="Czego szukamy"
        onEdit={onEditSection ? edit(CHAMPION_EDIT_ANCHOR.stack) : undefined}
        action={
          onOpenManualSearch ? (
            <button
              type="button"
              onClick={onOpenManualSearch}
              className="text-[13px] font-medium text-primary hover:underline"
            >
              Szukaj ręcznie w bazie →
            </button>
          ) : null
        }
        testId="brief-search"
      >
        <div className="space-y-1.5">
          <Eyebrow>Musi mieć</Eyebrow>
          {must.length > 0 ? (
            <Chips items={must} tone="must" critical={criticalResolution?.effective ?? []} />
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
          {nice.length > 0 ? <Chips items={nice} tone="nice" /> : <p className="text-[13px] text-muted-foreground">— brak</p>}
        </div>
        {profile.stack?.notes?.trim() ? (
          <p className="text-[13px] text-muted-foreground">Niuanse: {profile.stack.notes}</p>
        ) : null}
        <div className="space-y-1.5">
          <Eyebrow>Doświadczenie poza stackiem</Eyebrow>
          <ExperienceChips experience={profile.experience} />
          {!profile.experience ||
          (profile.experience.domains?.length ?? 0) +
            (profile.experience.certifications?.length ?? 0) +
            (profile.experience.regulations?.length ?? 0) ===
            0 ? (
            <p className="text-[13px] text-muted-foreground">— brak (dziedzina, certyfikaty, regulacje)</p>
          ) : null}
        </div>
        <div className="space-y-1.5 rounded-lg bg-muted/50 px-3.5 py-3">
          <Eyebrow>Wymagania do wyszukiwania w bazie</Eyebrow>
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
              Brak — bez nich rekrutacja nie przejdzie do searchu.
            </p>
          )}
          {search?.keywords?.trim() ? (
            <p className="text-xs text-muted-foreground">Frazy do LinkedIna: {search.keywords}</p>
          ) : null}
          {search?.target_companies?.trim() ? (
            <p className="text-xs text-muted-foreground">Firmy docelowe: {search.target_companies}</p>
          ) : null}
          {(search?.disqualifiers ?? []).length > 0 ? (
            <p className="text-xs text-muted-foreground">
              Kogo odrzucamy: {(search?.disqualifiers ?? []).join(", ")}
            </p>
          ) : null}
        </div>
      </Section>

      <Section
        title="O projekcie"
        onEdit={onEditSection ? edit(CHAMPION_EDIT_ANCHOR.project) : undefined}
        testId="brief-project"
      >
        {projectAbout ? (
          <p className="text-sm leading-relaxed text-foreground">{projectAbout}</p>
        ) : (
          <p className="text-[13px] text-muted-foreground">Delivery Lead nie opisał jeszcze projektu.</p>
        )}
        {responsibilities.length > 0 ? (
          <div className="space-y-1">
            <Eyebrow>Obowiązki</Eyebrow>
            <ul className="list-disc space-y-0.5 pl-5 text-sm text-foreground">
              {responsibilities.map((line, i) => (
                <li key={`${i}-${line}`}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Section>

      <Section
        title={`Pytania screeningowe (${questions.length})`}
        onEdit={onEditSection ? edit(CHAMPION_EDIT_ANCHOR.screening) : undefined}
        testId="brief-screening"
      >
        {questions.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Brak pytań screeningowych.</p>
        ) : (
          <ScreeningList questions={questions} />
        )}
      </Section>

      <Section
        title="O kliencie"
        onEdit={onEditSection ? edit(CHAMPION_EDIT_ANCHOR.client) : undefined}
        testId="brief-client"
      >
        <div className="space-y-1">
          <Eyebrow>Co przekona kandydata</Eyebrow>
          <p className={profile.client?.selling_points?.trim() ? "text-sm text-foreground" : "text-[13px] text-muted-foreground"}>
            {profile.client?.selling_points?.trim() || "— brak"}
          </p>
        </div>
        {(profile.client?.sectors ?? []).length > 0 ? (
          <p className="text-[13px] text-muted-foreground">
            Branże klienta: {(profile.client?.sectors ?? []).join(", ")}
          </p>
        ) : null}
        {clientId != null ? (
          <ClientPlaybookCard
            clientId={clientId}
            variant="compact"
            editHref={clientPlaybookEditHref(clientId)}
          />
        ) : null}
        <ChampionClientQuestionsPanel
          jobId={jobId}
          screeningQuestions={questions.map((q) => q.question)}
          historicalQuestions={profile.client?.historical_questions ?? ""}
          canEdit={false}
          onAddScreening={() => undefined}
          onAddHistorical={() => undefined}
        />
      </Section>

      <Section
        title="Wiedza z rozmów"
        onEdit={onEditSection ? edit(CHAMPION_EDIT_ANCHOR.insights) : undefined}
        testId="brief-insights"
      >
        <AskClientList profile={profile} />
        <ChampionInsightsDigest profile={profile} limit={8} historyLimit={5} />
      </Section>

      {requestHistory ? (
        <Section title="Wcześniejsze zapytania klienta" testId="brief-request-history">
          <RequestHistorySection
            jobId={jobId}
            clientId={job.client_id ?? null}
            readOnly={requestHistory.readOnly}
            compact
            narrow
            maxItems={5}
          />
        </Section>
      ) : null}
    </div>
  );
}

function ScreeningList({ questions }: { questions: ChampionProfile["screening_questions"] }) {
  const first = questions.slice(0, SCREENING_PREVIEW);
  const rest = questions.slice(SCREENING_PREVIEW);
  const item = (q: ChampionProfile["screening_questions"][number], index: number) => (
    <li key={q.id || `${index}-${q.question}`} className="border-t border-border py-2.5 first:border-t-0 first:pt-0">
      <p className="text-sm font-medium text-foreground">
        {index + 1}. {q.question}
      </p>
      {q.ideal_answer?.trim() ? (
        <p className="mt-1 text-[13px] text-muted-foreground">Idealnie: {q.ideal_answer}</p>
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

/** „Do dopytania u klienta” (notatki `ask_client`) — lista do odhaczenia w edycji. */
function AskClientList({ profile }: { profile: Partial<ChampionProfile> }) {
  const items = (profile.insights ?? []).filter((n) => n.topic === "ask_client" && n.text.trim());
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-warning/40 bg-warning-muted px-3.5 py-3">
      <p className="text-[13px] font-semibold text-warning-muted-foreground">
        Do dopytania u klienta · {items.length}
      </p>
      <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[13px] text-foreground">
        {items.map((n) => (
          <li key={n.id}>{n.text}</li>
        ))}
      </ul>
    </div>
  );
}
