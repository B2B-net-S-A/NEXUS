"use client";

/**
 * Okno „Zlecenie" — SKRÓT zlecenia otwierany z Tablicy (krok „Zlecenie” na
 * ścieżce rekrutacji). Od 29.09.2026 (makieta „Zlecenie i Champion — jedno
 * miejsce zamiast trzech”) okno pokazuje braki z szybką poprawką budżetu
 * i trybu pracy, najważniejsze fakty i wymagania, a zespół, ogłoszenie,
 * priorytet i portale otwiera w panelu obok Profilu Championa — dotąd żyły
 * w trzech miejscach naraz. „Zamknij rekrutację” jest w menu „⋯” nagłówka.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import {
  ExperienceChips,
  useChampionProfile,
} from "@/components/champion/ChampionBriefForRecruiters";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { MissingBlock, scrollToWhenReady } from "@/components/v2/recruitment/OrderMissingBlock";
import { formatJobLocation } from "@/components/v2/jobs/JobSummaryCard";
import type { RecruitmentSlideOver } from "@/components/v2/recruitment/types";
import api from "@/lib/api";
import { formatJobBudgetLabel } from "@/lib/job-budget";
import { extractSkills } from "@/lib/job-skills";
import { countPl } from "@/lib/plural-pl";
import { formatJobDeadline } from "@/lib/job-deadline";
import { recruitersOf, recruitersSummary } from "@/lib/job-team";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { blockForAnchor, type ChampionBlock } from "@/lib/champion-blocks";

import { RecruitmentSheet } from "./RecruitmentSheet";

export type OrderSlideOverSection = "team" | "close" | "portals";

/**
 * Zakładka Profilu Championa, do której prowadzi skrót (04.10.2026: „team”
 * = „Zespół i ogłoszenie”, „announce” = ta sama zakładka z portalami).
 */
export type OrderPanelTarget = "brief" | "team" | "announce";

export interface OrderNavigateOptions {
  panelTab?: OrderPanelTarget;
  edit?: boolean;
  /** Szuflada edycji bloku Briefu (brak w zleceniu wskazuje sekcję). */
  block?: ChampionBlock;
}

export interface OrderSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** `canWritePipeline && job.update` — edycja pól, HM, ustawień, zamknięcie. */
  canEdit: boolean;
  /**
   * Edycja TREŚCI (opis, ogłoszenia) — `can_edit` z serwera: także osoby
   * w roli „Rekruter” (22.09.2026). Brak = `canEdit`.
   */
  canEditContent?: boolean;
  /**
   * Przejście do „Profilu Championa”: `panelTab` otwiera zakładkę, `block`
   * szufladę edycji bloku, `edit` — pełny formularz.
   */
  onNavigate: (target: "champion", opts?: OrderNavigateOptions) => void;
  /** Otwarcie innego okna wysuwanego (np. „Baza pytań"). */
  onOpenSlideOver: (slideOver: RecruitmentSlideOver) => void;
  /** Pełny formularz edycji (`EditJobModal` renderuje strona). */
  onEdit: () => void;
  /** `undefined` = rola nie może pisać ogłoszenia — przycisk się nie renderuje. */
  onOpenAiWriter?: () => void;
  /** `undefined` = rekrutacja nieopublikowana albo brak uprawnienia do linku. */
  onOpenInviteLink?: () => void;
  /**
   * Sekcja rozwinięta i przewinięta przy otwarciu. `close` = wejście z podpowiedzi
   * „Obsada kompletna" w panelu osoby: od razu okno zamknięcia z powodem
   * (dawny krok 08 otwierał je jednym kliknięciem). `portals` = wejście
   * z `/jobs/new` po nieudanej publikacji na portalu (`?tab=portals`).
   */
  initialSection?: OrderSlideOverSection | null;
  /**
   * Ilu zatrudnionych — podpowiada powód zamknięcia „Obsadzone przez nas"
   * (lustro kroku „Umowa"). Wyboru nie dokonuje za człowieka.
   */
  hiredCount?: number;
}

// Lustro bramki z `JobReadinessDock`: `GET /jobs/{id}/readiness` wymaga
// uprawnienia „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”.
// Bez niego zapytanie ZAWSZE kończy się 403, więc go nie wysyłamy.
const GATE_PERMISSION = "recruitment_manage" as const;



function Fact({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  /** Podpowiedź z pełną treścią, gdy `value` jest skrótem (np. „+2”). */
  title?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold text-muted-foreground">{label}</dt>
      <dd className="text-[13px] text-foreground" title={title}>
        {value}
      </dd>
    </div>
  );
}

function OrderBody({
  jobId,
  canEdit,
  canEditContent = canEdit,
  onNavigate,
  onOpenSlideOver,
  onEdit,
  closeSheet,
}: Omit<OrderSlideOverProps, "open" | "onOpenChange" | "hiredCount"> & {
  closeSheet: () => void;
}) {
  const authUser = useAuthStore((s) => s.user);
  const canSeeGate = hasPermission(authUser, GATE_PERMISSION);

  // Ten sam klucz co strona rekrutacji i dok gotowości (`["job", "<id>"]`) —
  // jedna kopia zlecenia; zapis budżetu albo trybu pracy odświeża okno i nagłówek.
  const jobQuery = useQuery({
    queryKey: ["job", String(jobId)],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then((r) => r.data),
    retry: false,
  });
  // Sekcje 4 i 5 Championa — ten sam klucz co edytor profilu.
  const championQuery = useChampionProfile(jobId);
  const champion = championQuery.data?.champion_profile;

  const viewState = resolveViewState({
    isLoading: jobQuery.isLoading,
    isError: jobQuery.isError,
    error: jobQuery.error,
    isSuccess: jobQuery.isSuccess,
  });

  if (viewState === "loading") {
    return (
      <div className="space-y-3">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (viewState === "forbidden" || viewState === "not_found" || viewState === "error") {
    return (
      <QueryStateNotice
        state={viewState}
        className="rounded-xl"
        onRetry={() => void jobQuery.refetch()}
      />
    );
  }

  const job = jobQuery.data;
  const must = extractSkills(job.must_skills);
  const nice = extractSkills(job.nice_skills);
  // Pole podlega redakcji finansowej: rola bez uprawnień dostaje `null`.
  // „Brak" twierdziłoby, że budżetu nie ustalono — dlatego przy `null`
  // czytamy `has_budget_hourly` (sam fakt, bez kwoty) i mówimy, co wiemy.
  const budget = formatJobBudgetLabel(job);
  const budgetLabel =
    budget != null
      ? budget
      : job.has_budget_hourly === true
        ? "ustawiony (kwota niewidoczna dla Twojej roli)"
        : "nie ustawiono";
  const projectAbout = (champion?.project?.about ?? "").trim();
  const questionCount = champion?.screening_questions?.length ?? 0;
  const team = recruitersSummary(recruitersOf(job));

  // Modale strony (`EditJobModal`) żyją POZA tym oknem. Otwarty Radix Dialog
  // wyłącza `pointer-events` reszcie dokumentu i więzi fokus, więc modal
  // wyrenderowany obok byłby nieklikalny — najpierw zamykamy okno.
  const leaveFor = (action: () => void) => () => {
    closeSheet();
    action();
  };
  const goPanel = (panelTab: OrderPanelTarget) =>
    leaveFor(() => onNavigate("champion", { panelTab }));

  return (
    <div className="space-y-4" data-testid="order-shortcut">
      <MissingBlock
        jobId={jobId}
        job={job}
        canSeeGate={canSeeGate}
        canEditChampion={canEditContent}
        canEditJob={canEdit}
        onGoChampion={(anchor) => {
          closeSheet();
          const block = blockForAnchor(anchor);
          if (block) {
            onNavigate("champion", { block });
            return;
          }
          onNavigate("champion", { edit: true });
          if (anchor) scrollToWhenReady(anchor);
        }}
        onGoTeam={goPanel("team")}
        onEditJob={leaveFor(onEdit)}
      />

      {/* Skrót zlecenia (makieta 29.09.2026): najważniejsze fakty pod ręką na
          Tablicy. Zespół, ogłoszenie, priorytet i portale mieszkają w panelu
          obok Profilu Championa — okno tylko tam prowadzi, nie jest ich kopią. */}
      <OrderBlock
        title="Co zamówił klient"
        actions={
          canEditContent ? (
            <Button type="button" variant="ghost" size="sm" onClick={leaveFor(onEdit)}>
              Edytuj rekrutację
            </Button>
          ) : null
        }
      >
        <dl className="grid grid-cols-2 gap-3">
          <Fact label="Budżet" value={budgetLabel} />
          <Fact label="Tryb i lokalizacja" value={formatJobLocation(job)} />
          <Fact
            label="Termin dla klienta"
            value={formatJobDeadline(job.deadline, job.deadline_time) ?? "nie ustawiono"}
          />
          <Fact label="Klient" value={job.client_name?.trim() || "—"} />
          {/* 0380: to, co idzie do klienta — nazwa i numer z jego zapytania. */}
          <Fact label="Nazwa od klienta" value={job.title?.trim() || "—"} />
          <Fact
            label="Numer u klienta"
            value={job.client_reference?.trim() || "nie podano"}
          />
          {/* 02.10.2026: „Rekruter” to wszyscy, którzy pracują nad rekrutacją
              (pierwsza osoba i „+N”); propozycja automatu to jeszcze nie praca. */}
          <Fact
            label="Rekruter"
            value={
              team.names.length > 0
                ? `${team.names[0]}${team.more > 0 ? ` +${team.more}` : ""}`
                : "Bez rekrutera"
            }
            title={team.tooltip || undefined}
          />
          <Fact
            label="Hiring manager"
            value={job.hiring_manager_name?.trim() || "nie przypisano"}
          />
        </dl>
        {must.length > 0 || nice.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Wymagania">
            {must.map((skill) => (
              <li
                key={`must:${skill}`}
                className="inline-flex h-[26px] items-center rounded-full bg-primary/10 px-2.5 text-xs font-medium text-primary"
              >
                {skill}
              </li>
            ))}
            {nice.map((skill) => (
              <li
                key={`nice:${skill}`}
                className="inline-flex h-[26px] items-center rounded-full bg-muted px-2.5 text-xs font-medium text-muted-foreground"
              >
                {skill} — mile widziane
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            Brak wymagań must / nice — dodaj je w Profilu Championa (sekcja Stack).
          </p>
        )}
        <ExperienceChips experience={champion?.experience} />
        {projectAbout ? (
          <p className="text-[13px] leading-relaxed text-foreground">{projectAbout}</p>
        ) : null}
        {questionCount > 0 ? (
          <p className="text-xs text-muted-foreground">
            {countPl(questionCount, "pytanie screeningowe", "pytania screeningowe", "pytań screeningowych")} w profilu.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
          {/* Karta klienta: SLA, limity CV, zasady procesu. Link do Pomocy, nie
              do `/clients/*` — tamta trasa jest bramkowana sekcją Delivery,
              a kartę czyta każda rola operacyjna. */}
          {job.client_id != null ? (
            <Link
              href={`/help?tab=clients&client=${job.client_id}`}
              aria-label={`Karta klienta${job.client_name ? ` ${job.client_name}` : ""} — otwórz`}
              className="font-medium text-primary hover:underline"
            >
              Karta klienta ↗
            </Link>
          ) : null}
          <button
            type="button"
            onClick={() => onOpenSlideOver("questions")}
            aria-label="Baza pytań — Otwórz"
            className="font-medium text-primary hover:underline"
          >
            Baza pytań
          </button>
        </div>
      </OrderBlock>

      <div className="flex flex-wrap gap-2 border-t border-border pt-3">
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={leaveFor(() => onNavigate("champion"))}
          aria-label="Profil Championa i pytania na screening — Otwórz pełne"
        >
          Otwórz Profil Championa
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={goPanel("team")}>
          Zespół i priorytet
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={goPanel("announce")}>
          Ogłoszenie i portale
        </Button>
      </div>
    </div>
  );
}

/** Blok okna Zlecenia — tytuł z akcjami po prawej i treść pod spodem. */
function OrderBlock({
  title,
  actions,
  children,
  sectionRef,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  sectionRef?: React.Ref<HTMLElement>;
}) {
  return (
    <section
      ref={sectionRef}
      aria-label={title}
      className="space-y-3 rounded-xl border border-border p-4"
    >
      <div className="flex items-center gap-2">
        <h3 className="flex-1 text-sm font-semibold text-foreground">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function OrderSlideOver({
  open,
  onOpenChange,
  // Zamknięcie rekrutacji i jego podpowiedź przeszły do strony (menu „⋯”).
  hiredCount: _hiredCount,
  initialSection: _initialSection,
  ...rest
}: OrderSlideOverProps) {
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Zlecenie"
      description="Czego brakuje i najważniejsze fakty tej rekrutacji."
      descriptionHidden
      data-testid="order-slideover"
    >
      {/* `key` z sekcji startowej: ponowne otwarcie starym linkiem ma rozwinąć
          właściwą sekcję, a stan rozwinięć jest czytany przy montażu. Radix
          i tak odmontowuje treść po zamknięciu okna. */}
      <OrderBody {...rest} closeSheet={() => onOpenChange(false)} />
    </RecruitmentSheet>
  );
}
