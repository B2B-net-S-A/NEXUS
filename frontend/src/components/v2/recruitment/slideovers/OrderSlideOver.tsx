"use client";

/**
 * Okno „Zlecenie" — wszystko, co opisuje rekrutację, obok tabeli osób
 * (makieta V3Zlecenie). Zastępuje panel „Zespół i priorytet" z nagłówka,
 * zakładkę `?tab=portals` (dziś otwiera samo okno) i skróty edycji/ogłoszenia
 * z menu nagłówka.
 *
 * Okno NIE ma własnych reguł ani formularzy: składa istniejące klocki
 * (`JobOwnershipPanel`, `HiringManagerPicker`, `JobSettingsPanel`,
 * `JobPriorityContext`, `JobCloseWithReasonDialog`,
 * `JobReadinessDock`) i każdy z nich zapisuje po swojemu, natychmiast. Stąd
 * brak przycisku „Zapisz" z makiety — nie miałby czego zapisywać.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  ChampionInsightsDigest,
  ExperienceChips,
  useChampionProfile,
} from "@/components/champion/ChampionBriefForRecruiters";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";
import { JobPortalsSection } from "@/components/v2/recruitment/JobPortalsSection";
import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import { JobReadinessDock } from "@/components/v2/jobs/JobReadinessDock";
import { JobSettingsPanel } from "@/components/v2/jobs/JobSettingsPanel";
import { formatJobLocation } from "@/components/v2/jobs/JobSummaryCard";
import { JobPriorityContext } from "@/components/v2/priority-work";
import type { RecruitmentSlideOver } from "@/components/v2/recruitment/types";
import api from "@/lib/api";
import { formatBudgetHourly, jobBudgetHourly } from "@/lib/job-budget";
import { extractSkills } from "@/lib/job-skills";
import { countPl } from "@/lib/plural-pl";
import { formatDate } from "@/lib/utils";
import { httpStatusFromError, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

import { RecruitmentSheet } from "./RecruitmentSheet";

export type OrderSlideOverSection = "team" | "close";

export interface OrderSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** `canWritePipeline && job.update` — edycja pól, HM, ustawień, zamknięcie. */
  canEdit: boolean;
  /**
   * Edycja TREŚCI (opis, ogłoszenia) — `can_edit` z serwera: także rekruter
   * prowadzący i współpracownicy (22.09.2026). Brak = `canEdit`.
   */
  canEditContent?: boolean;
  /** Przejście do pełnego widoku (dziś tylko Profil Championa). */
  onNavigate: (target: "champion") => void;
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
   * (dawny krok 08 otwierał je jednym kliknięciem).
   */
  initialSection?: OrderSlideOverSection | null;
  /**
   * Ilu zatrudnionych — podpowiada powód zamknięcia „Obsadzone przez nas"
   * (lustro kroku „Umowa"). Wyboru nie dokonuje za człowieka.
   */
  hiredCount?: number;
}

// Lustro `GATE_ROLES` z `JobReadinessDock`: `GET /jobs/{id}/readiness` to
// `DeliveryLeadPlus`. Dla innych ról zapytanie ZAWSZE kończy się 403, więc go
// nie wysyłamy.
const GATE_ROLES = ["admin", "delivery_lead"] as const;

/** Rozwijany wiersz-link: etykieta po lewej, akcja po prawej (makieta). */
function DisclosureRow({
  label,
  hint,
  open,
  onToggle,
  children,
  sectionRef,
}: {
  label: string;
  hint?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  sectionRef?: React.Ref<HTMLDivElement>;
}) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div ref={sectionRef} className="border-b border-border/70 last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 py-2.5 text-left text-[13px] text-foreground hover:text-primary"
      >
        <span className="min-w-0">{label}</span>
        <span className="flex shrink-0 items-center gap-1 font-medium text-primary">
          {hint ? <span className="max-w-[14rem] truncate">{hint}</span> : null}
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
      </button>
      {open ? <div className="pb-4 pt-1">{children}</div> : null}
    </div>
  );
}

/**
 * „Brakuje N rzeczy" — werdykt OFICJALNEJ bramki „Przekaż do searchu".
 *
 * Lista braków przychodzi z serwera (`blockers`), więc okno nie powtarza
 * żadnej reguły gotowości: jedna lista braków, ta sama co w doku i przy
 * przycisku handoffu (wspólny klucz `["job-readiness", jobId]`).
 */
function MissingBlock({ jobId, canSeeGate }: { jobId: number; canSeeGate: boolean }) {
  const query = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data),
    enabled: canSeeGate,
    staleTime: 30_000,
    retry: false,
  });

  if (!canSeeGate) return null;
  if (query.isLoading) return <Skeleton className="h-16 w-full rounded-xl" />;
  if (query.isError) {
    // 403 = Delivery Lead spoza zakresu klienta. To nie awaria — po prostu
    // nie jego bramka; pełna kompletność niżej działa dla każdej roli.
    if (httpStatusFromError(query.error) === 403) return null;
    return (
      <div className="flex items-center justify-between gap-2 rounded-xl border border-dashed border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
        <span>Nie udało się sprawdzić, czego brakuje w zleceniu.</span>
        <button
          type="button"
          className="shrink-0 font-medium text-primary hover:underline"
          onClick={() => void query.refetch()}
        >
          Ponów
        </button>
      </div>
    );
  }
  const data = query.data;
  if (!data || data.closed) return null;

  const blockers: string[] = Array.isArray(data.blockers) ? data.blockers : [];
  if (data.already_handed_off || data.ready || blockers.length === 0) {
    return (
      <section
        className="rounded-xl border border-success/20 bg-success-muted px-4 py-3 text-sm font-semibold text-success-muted-foreground"
        data-testid="order-missing-block"
      >
        {data.already_handed_off
          ? "Zlecenie przekazane do searchu — niczego nie brakuje."
          : "Niczego nie brakuje — zlecenie gotowe do przekazania do searchu."}
      </section>
    );
  }

  return (
    <section
      className="space-y-2 rounded-xl border border-warning/25 bg-warning-muted px-4 py-3 text-warning-muted-foreground"
      data-testid="order-missing-block"
      aria-label="Braki w zleceniu"
    >
      <h3 className="text-sm font-semibold">
        Brakuje {countPl(blockers.length, "rzeczy", "rzeczy", "rzeczy")}
      </h3>
      <ul className="list-disc space-y-1 pl-5 text-[13px]">
        {blockers.map((blocker) => (
          <li key={blocker}>{blocker}</li>
        ))}
      </ul>
      <p className="text-xs">
        Hiring managera, termin i zespół uzupełnisz niżej; wymagania i pytania —
        w Profilu Championa.
      </p>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold text-muted-foreground">{label}</dt>
      <dd className="text-[13px] text-foreground">{value}</dd>
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
  onOpenAiWriter,
  onOpenInviteLink,
  initialSection,
  hiredCount,
  closeSheet,
}: Omit<OrderSlideOverProps, "open" | "onOpenChange"> & {
  hiredCount: number;
  closeSheet: () => void;
}) {
  const queryClient = useQueryClient();
  const authUser = useAuthStore((s) => s.user);
  const canSeeGate = authUser ? hasRole(authUser, ...GATE_ROLES) : false;

  const [teamOpen, setTeamOpen] = useState(initialSection === "team");
  const [priorityOpen, setPriorityOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [readinessOpen, setReadinessOpen] = useState(false);
  const [closeDialogOpen, setCloseDialogOpen] = useState(false);
  const closeRequestHandled = useRef(false);

  const teamRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLDivElement | null>(null);

  // Ten sam klucz co strona rekrutacji i dok gotowości (`["job", "<id>"]`) —
  // jedna kopia zlecenia; zapis HM albo ustawień odświeża okno i nagłówek naraz.
  const jobQuery = useQuery({
    queryKey: ["job", String(jobId)],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then((r) => r.data),
    retry: false,
  });
  const jobLoaded = jobQuery.isSuccess;
  // Sekcje 4 i 8 Championa — ten sam klucz co edytor profilu.
  const championQuery = useChampionProfile(jobId);
  const champion = championQuery.data?.champion_profile;

  // Przewijamy dopiero PO wczytaniu zlecenia: wcześniej sekcji nie ma w DOM.
  useEffect(() => {
    if (!jobLoaded || !initialSection) return;
    if (initialSection === "close") {
      closeRef.current?.scrollIntoView?.({ block: "end" });
      // Raz: zamknięcie okna dialogu nie może otwierać go ponownie przy
      // odświeżeniu zlecenia w tle. Bramka (`canEdit`, status) stoi niżej —
      // bez niej dialogu po prostu nie ma w drzewie.
      if (!closeRequestHandled.current) {
        closeRequestHandled.current = true;
        setCloseDialogOpen(true);
      }
      return;
    }
    teamRef.current?.scrollIntoView?.({ block: "start" });
  }, [jobLoaded, initialSection]);

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
        <Skeleton className="h-32 w-full" />
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
  const budget = jobBudgetHourly(job);
  const budgetLabel =
    budget != null
      ? `do ${formatBudgetHourly(budget)} PLN/h`
      : job.has_budget_hourly === true
        ? "ustawiony (kwota niewidoczna dla Twojej roli)"
        : "nie ustawiono";
  const isClosed = job.status === "closed";

  // Modale strony (`EditJobModal`, AI writer, link aplikacyjny) żyją POZA tym
  // oknem. Otwarty Radix Dialog wyłącza `pointer-events` reszcie dokumentu
  // i więzi fokus, więc modal wyrenderowany obok byłby nieklikalny — dlatego
  // najpierw zamykamy okno, potem wołamy akcję.
  const leaveFor = (action: () => void) => () => {
    closeSheet();
    action();
  };

  const invalidateJob = () => {
    void queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
  };

  const collaboratorNames = (job.collaborators ?? [])
    .map((c: { name?: string | null }) => c.name?.trim())
    .filter(Boolean)
    .join(", ");

  return (
    <div className="space-y-4">
      <MissingBlock jobId={jobId} canSeeGate={canSeeGate} />

      {/* Makieta „Zlecenie" (22.09.2026): trzy bloki — co zamówił klient,
          zespół, ogłoszenie — a rzadsze ustawienia zwinięte w „Więcej". */}
      <OrderBlock
        title="Co zamówił klient"
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={leaveFor(() => onNavigate("champion"))}
              aria-label="Profil Championa i pytania na screening — Otwórz pełne"
            >
              Profil Championa ↗
            </Button>
            {canEditContent ? (
              <Button type="button" variant="ghost" size="sm" onClick={leaveFor(onEdit)}>
                Edytuj rekrutację
              </Button>
            ) : null}
          </>
        }
      >
        <dl className="grid grid-cols-2 gap-3">
          <Fact label="Budżet" value={budgetLabel} />
          <Fact label="Tryb i lokalizacja" value={formatJobLocation(job)} />
          <Fact
            label="Termin dla klienta"
            value={job.deadline ? formatDate(job.deadline) : "nie ustawiono"}
          />
          <Fact label="Klient" value={job.client_name?.trim() || "—"} />
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

      <OrderBlock
        title="Wiedza z rozmów"
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={leaveFor(() => onNavigate("champion"))}
            aria-label="Wiedza z rozmów — otwórz w Profilu Championa"
          >
            Wszystko w profilu ↗
          </Button>
        }
      >
        {championQuery.isError ? (
          <p className="text-xs text-muted-foreground">
            Nie udało się wczytać notatek z Profilu Championa.
          </p>
        ) : championQuery.isSuccess ? (
          <ChampionInsightsDigest profile={champion} />
        ) : (
          <Skeleton className="h-12 w-full" />
        )}
      </OrderBlock>

      <OrderBlock title="Zespół" sectionRef={teamRef}>
        <dl className="grid grid-cols-2 gap-3">
          <Fact label="Prowadzi" value={job.primary_owner?.name ?? "nieprzypisany"} />
          <Fact
            label="Hiring manager"
            value={job.hiring_manager_name?.trim() || "— wybierz"}
          />
          <Fact label="Współpracują" value={collaboratorNames || "—"} />
        </dl>
        <DisclosureRow
          label="Zmień zespół i hiring managera"
          open={teamOpen}
          onToggle={() => setTeamOpen((v) => !v)}
        >
          <div className="space-y-4">
            <JobOwnershipPanel
              jobId={jobId}
              jobTitle={job.title}
              primaryOwner={job.primary_owner ?? null}
              collaborators={job.collaborators ?? []}
            />
            <HiringManagerPicker
              jobId={jobId}
              clientId={job.client_id ?? null}
              value={job.hiring_manager_contact_id ?? null}
              valueName={job.hiring_manager_name ?? null}
              canEdit={canEdit}
              onSaved={invalidateJob}
            />
          </div>
        </DisclosureRow>
      </OrderBlock>

      <OrderBlock title="Ogłoszenie i link aplikacyjny">
        {onOpenAiWriter || onOpenInviteLink ? (
          <div className="flex flex-wrap gap-2">
            {onOpenAiWriter ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={leaveFor(onOpenAiWriter)}
              >
                Napisz ogłoszenie z AI
              </Button>
            ) : null}
            {onOpenInviteLink ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={leaveFor(onOpenInviteLink)}
              >
                Wygeneruj link aplikacyjny
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Ogłoszenie i link aplikacyjny są dostępne dla opublikowanej
            rekrutacji i ról z prawem jej edycji.
          </p>
        )}
      </OrderBlock>

      <section aria-label="Więcej ustawień" className="px-1">
        <h3 className="pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Więcej
        </h3>
        <DisclosureRow
          label="Priorytet"
          open={priorityOpen}
          onToggle={() => setPriorityOpen((v) => !v)}
        >
          <JobPriorityContext jobId={jobId} />
        </DisclosureRow>
        <DisclosureRow
          label="Ustawienia rekrutacji"
          hint="Delivery Lead i termin"
          open={settingsOpen}
          onToggle={() => setSettingsOpen((v) => !v)}
        >
          <JobSettingsPanel
            jobId={jobId}
            clientId={job.client_id ?? null}
            deliveryLeadId={job.delivery_lead_id ?? null}
            deadline={job.deadline ?? null}
            canEdit={canEdit}
          />
        </DisclosureRow>
        {/* Pełna checklista kompletności to ISTNIEJĄCY dok — montowany dopiero
            po rozwinięciu, bo sam odpytuje pipeline i Championa. */}
        <DisclosureRow
          label="Pełna kompletność zlecenia"
          open={readinessOpen}
          onToggle={() => setReadinessOpen((v) => !v)}
        >
          <JobReadinessDock jobId={jobId} variant="list" />
        </DisclosureRow>
        {/* Multiposting (Pracuj.pl, JustJoinIT) — renderuje się dopiero, gdy
            backend zgłasza gotowy portal (dziś flagi są wyłączone). */}
        <JobPortalsSection jobId={jobId} readOnly={!canEditContent} />
      </section>

      <p className="text-xs text-muted-foreground">
        Każda zmiana zlecenia zapisuje się od razu i odświeża propozycje z bazy
        w tle.
      </p>

      {canEdit && !isClosed ? (
        <div ref={closeRef} className="border-t border-border pt-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full justify-center text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setCloseDialogOpen(true)}
          >
            Zamknij rekrutację
          </Button>
          <JobCloseWithReasonDialog
            open={closeDialogOpen}
            onOpenChange={setCloseDialogOpen}
            jobId={jobId}
            jobTitle={job.title ?? `Rekrutacja #${jobId}`}
            clientId={job.client_id ?? null}
            defaultReason={hiredCount > 0 ? "filled_by_us" : "other"}
            onClosed={closeSheet}
          />
        </div>
      ) : null}
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
  hiredCount = 0,
  ...rest
}: OrderSlideOverProps) {
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Zlecenie"
      description="Czego brakuje, najważniejsze fakty i ustawienia tej rekrutacji."
      descriptionHidden
      data-testid="order-slideover"
    >
      {/* `key` z sekcji startowej: ponowne otwarcie starym linkiem ma rozwinąć
          właściwą sekcję, a stan rozwinięć jest czytany przy montażu. Radix
          i tak odmontowuje treść po zamknięciu okna. */}
      <OrderBody
        key={rest.initialSection ?? "default"}
        {...rest}
        hiredCount={hiredCount}
        closeSheet={() => onOpenChange(false)}
      />
    </RecruitmentSheet>
  );
}
