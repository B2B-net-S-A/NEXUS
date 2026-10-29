"use client";

/**
 * Pasek osoby — góra profilu na całą szerokość (od 13.10.2026, decyzja E1):
 * tożsamość, pigułki („Szuka aktywnie”, „Pracuje u nas”, kategoria, ryzyko,
 * konflikt z klientem), kontakt jako ikony z kopiowaniem i akcje w jednym
 * rzędzie: „Przypisz do rekrutacji”, „Dodaj notatkę”, „Nie odebrał”, „Najnowsze
 * CV” (od 22.10.2026, jak w Traffit), menu „⋯” (Kontakt · Dane · Status osoby ·
 * Usuń profil). Czarna lista „u nas” od
 * 17.10.2026 nie jest pigułką, tylko banerem pod paskiem (`BlacklistNotice`
 * w `CandidateDetailV2`) — z tym, kto, kiedy i dlaczego.
 *
 * Fakty (dostępność, stawka, tryb pracy, miasto, języki, narodowość) NIE są
 * tutaj — mają jedno miejsce: kartę „Do propozycji” w lewej kolumnie
 * (`CandidateProfileFactsBar layout="proposal"`). Status dostępności („szuka
 * aktywnie”) stoi wyłącznie w pigułce, wiersz „Dostępność” pokazuje termin.
 *
 * Zdjęte 13.10.2026 (D1–D3, liczby z produkcji): „Obserwuj” (0 przypięć),
 * „Wrzuć na targ” (strona targu zdjęta z menu 21.09, ręcznie 2 wpisy),
 * „Korekta imienia i nazwiska” (wchodzi do „Edytuj dane”), „Generuj CV”
 * z menu (zostaje w zakładce CV i w karcie rekrutacji), przycisk CloudTalk
 * (10 połączeń w historii) i status sprawy kontaktu (0 spraw).
 */

import type { ComponentProps, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  Ban,
  Calendar,
  CalendarPlus,
  Check,
  Combine,
  Copy,
  FileText,
  Linkedin,
  Mail,
  MessageSquare,
  MoreHorizontal,
  PencilLine,
  Phone,
  PhoneMissed,
  ShieldAlert,
  Tags,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AvailabilityPill } from "@/components/ds/AvailabilityPill";
import { EmploymentPill } from "@/components/ds/EmploymentMarker";
import { CandidateNav } from "@/components/v2/CandidateNav";
import { CompetenceCategoryBadge } from "@/components/v2/CompetenceCategoryBadge";
import { RiskBadge } from "@/components/v2/RiskBadge";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { phase5Api } from "@/lib/api";
import { conflictKeys } from "@/lib/conflicts";
import type { EmploymentMarker } from "@/lib/employment-marker";
import { hidesAvailabilityStatus } from "@/lib/contract-availability";
import { formatDate } from "@/lib/utils";
import type { PresenceViewer } from "@/hooks/usePresence";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { getCandidateInitials } from "@/components/v2/pages/candidate-list-helpers";
import { candidateHeadline, linkedinHref, pickHeaderWarning } from "./profile-helpers";
import { AddToListButton } from "./AddToListButton";

import { formatPhone } from "@/lib/phone-format";
/* eslint-disable @typescript-eslint/no-explicit-any -- payload kandydata jest luźno typowany */

// ── Pasek nad profilem: powrót + poprzedni/następny ───────────────────────

type CandidateNavProps = ComponentProps<typeof CandidateNav>;

export function ProfileTopBar({
  embedded,
  nav,
  backJobId,
  backJobTitle,
  backToTalentRadar,
  backSearch,
  pick,
  candidateId,
}: {
  embedded: boolean;
  /** Właściwości paska poprzedni/następny; `null` = brak kontekstu listy. */
  nav: CandidateNavProps | null;
  backJobId: number | null;
  backJobTitle: string | null;
  backToTalentRadar: boolean;
  /** Powrót do wyszukiwania, z którego otwarto profil (okno rekrutacji albo lista). */
  backSearch?: { href: string; context: string | null } | null;
  /** „Wybieram” — osoba wraca zaznaczona w oknie „Szukaj ręcznie” rekrutacji. */
  pick?: { picked: boolean; count: number; onToggle: () => void } | null;
  candidateId: number;
}) {
  if (embedded) return nav ? <CandidateNav {...nav} /> : null;
  const backClass =
    "inline-flex min-h-11 min-w-11 items-center gap-1 px-2 text-sm text-muted-foreground hover:text-primary";
  const backLabel = backJobTitle ? `Wróć do rekrutacji: ${backJobTitle}` : "Wróć do rekrutacji";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {backSearch ? (
        <Link
          href={backSearch.href}
          data-tour="candidate.profile.back-to-search"
          className={`${backClass} min-w-0 flex-1 basis-0 font-medium text-primary`}
          title={backSearch.context ?? undefined}
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          <span className="shrink-0">Wróć do wyników wyszukiwania</span>
          {backSearch.context ? (
            <span className="truncate font-normal text-muted-foreground">· {backSearch.context}</span>
          ) : null}
        </Link>
      ) : backJobId != null ? (
        <Link
          href={`/jobs/${backJobId}?candidate=${candidateId}`}
          className={`${backClass} max-w-88`}
          title={backLabel}
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          <span className="truncate">{backLabel}</span>
        </Link>
      ) : backToTalentRadar ? (
        <Link href="/candidates?mode=request" className={backClass}>
          <ArrowLeft className="h-4 w-4" /> Wróć do wyszukiwania z requestu
        </Link>
      ) : (
        <Link href="/candidates" className={backClass}>
          <ArrowLeft className="h-4 w-4" /> Wróć do kandydatów
        </Link>
      )}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        {pick ? (
          <Button
            size="sm"
            variant="outline"
            onClick={pick.onToggle}
            aria-pressed={pick.picked}
            data-tour="candidate.profile.pick"
            title={`Osoba wróci zaznaczona w oknie wyszukiwania. Wybrani: ${pick.count}`}
            className={`min-h-11 ${pick.picked ? "border-primary bg-primary/10 text-primary hover:bg-primary/15" : ""}`}
          >
            <span
              aria-hidden
              className={`flex h-4 w-4 items-center justify-center rounded border ${
                pick.picked ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground"
              }`}
            >
              {pick.picked ? <Check className="h-3 w-3" /> : null}
            </span>
            Wybieram
            {pick.count > 0 ? (
              <span className="rounded-full bg-muted px-1.5 text-xs tabular-nums text-muted-foreground">
                {pick.count}
              </span>
            ) : null}
          </Button>
        ) : null}
        {nav ? <CandidateNav {...nav} /> : null}
      </div>
    </div>
  );
}

// ── Pasek osoby ───────────────────────────────────────────────────────────

export interface ProfilePersonBarActions {
  onAssign: () => void;
  onAddNote: () => void;
  /** „Nie odebrał” — próba kontaktu jednym kliknięciem. */
  onNoAnswer?: () => void;
  noAnswerSaving?: boolean;
  onEmail: () => void;
  onScheduleInterview: () => void;
  onPrepInvite: () => void;
  /** „Spotkania i follow-up” — tylko gdy jest follow-up albo spotkania Teams. */
  onFollowup?: () => void;
  followupLabel?: string;
  onEdit: () => void;
  onTagsPools: () => void;
  onConflicts: () => void;
  /** Tylko admin (`canHardDeleteCandidate`). */
  onDelete?: () => void;
  /** „Scal z…” — admin i Head of Recruitment (`canMergeCandidates`). */
  onMerge?: () => void;
  /** „Czarna lista…” (17.10.2026) — okno `BlacklistDialog`; tylko z prawem zapisu. */
  onBlacklist?: () => void;
  /** „Najnowsze CV” — bez pliku CV (albo przed wczytaniem listy) przycisku nie ma. */
  latestCv?: CandidateDocument | null;
  onOpenLatestCv?: () => void;
}

export interface ProfilePersonBarProps {
  candidate: any;
  candidateId: number;
  canWrite: boolean;
  riskProfile?: CandidateRiskProfile | null;
  viewers: PresenceViewer[];
  /** Przycisk zamknięcia w szufladzie bez paska nawigacji. */
  onClose?: () => void;
  actions: ProfilePersonBarActions;
}

const CONTACT_CLASS =
  "inline-flex min-h-9 min-w-0 items-center gap-1.5 rounded-md border border-border bg-card px-2 text-xs text-foreground";

export function ProfilePersonBar({
  candidate,
  candidateId,
  canWrite,
  riskProfile,
  viewers,
  onClose,
  actions,
}: ProfilePersonBarProps) {
  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const initials = getCandidateInitials(candidate) || "?";
  const headline = candidateHeadline(candidate);
  const warning = pickHeaderWarning({
    status: candidate.status,
    employmentState: candidate.employment?.state,
    riskLevel: riskProfile?.level,
  });
  const employmentMarker = (candidate.employment_marker ?? null) as EmploymentMarker | null;
  const conflicts = useActiveConflicts(candidateId);

  return (
    <Card variant="default" size="md" className="p-0!">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3 p-4 md:max-2xl:p-3">
        <Avatar size="lg">
          <AvatarFallback>{initials}</AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1 basis-72 space-y-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h1 className="break-words text-xl font-extrabold leading-tight tracking-heading-tight text-foreground">
                {fullName}
              </h1>
              {headline ? (
                <p className="mt-0.5 text-sm text-muted-foreground">{headline}</p>
              ) : null}
            </div>
            <div className="flex shrink-0 items-start gap-1 lg:hidden">
              <ActiveViewers
                resourceType="candidate"
                resourceId={Number.isFinite(candidateId) ? candidateId : null}
                viewers={viewers}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {/* Żywa umowa (D3, 15.10.2026): „Pracuje u nas” zamiast „Szuka
                aktywnie” ze screeningu sprzed zatrudnienia. */}
            {hidesAvailabilityStatus(employmentMarker) ? null : (
              <AvailabilityPill status={candidate.availability_status} />
            )}
            {employmentMarker ? <EmploymentPill marker={employmentMarker} /> : null}
            <CompetenceCategoryBadge
              categoryId={candidate.competence_category_id}
              slug={candidate.competence_category}
              size="sm"
              className="max-w-full whitespace-normal text-left"
            />
            {/* Czarna lista nie ma tu pigułki — baner pod paskiem mówi więcej. */}
            {warning?.kind === "risk" && riskProfile ? (
              <RiskBadge profile={riskProfile} hideLow />
            ) : null}
            {conflicts.length > 0 ? (
              <button
                type="button"
                onClick={actions.onConflicts}
                className="inline-flex h-5 items-center gap-1 rounded-full border border-destructive/30 bg-destructive-muted px-2 text-[11px] font-semibold text-destructive-muted-foreground hover:underline"
                title={conflicts
                  .map((row) => `${row.type_label}${row.client_name ? ` · ${row.client_name}` : ""}`)
                  .join("\n")}
              >
                <ShieldAlert className="size-3" aria-hidden />
                {conflicts.length === 1
                  ? `Konflikt: ${conflicts[0].client_name ?? conflicts[0].type_label}`
                  : `Konflikty z klientami: ${conflicts.length}`}
              </button>
            ) : null}
          </div>

          <ContactRow candidate={candidate} canWrite={canWrite} onEmail={actions.onEmail} />
        </div>

        <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:items-end">
          <div className="hidden items-start gap-1 lg:flex">
            <ActiveViewers
              resourceType="candidate"
              resourceId={Number.isFinite(candidateId) ? candidateId : null}
              viewers={viewers}
            />
            {onClose ? (
              <button
                type="button"
                onClick={onClose}
                aria-label="Zamknij"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            ) : null}
          </div>
          <PersonActions candidate={candidate} actions={actions} canWrite={canWrite} />
        </div>
      </div>
    </Card>
  );
}

/**
 * Aktywne konflikty z klientem — ta sama kwerenda (klucz i parametry) co
 * `ConflictsWidget` w oknie „Konflikty i weta”, więc okno nie pobiera drugi
 * raz. Konflikt to ostrzeżenie, nie blokada (decyzja 17.09.2026) — tu tylko
 * chip, który otwiera okno.
 */
function useActiveConflicts(candidateId: number) {
  const query = useQuery({
    queryKey: conflictKeys.candidate(candidateId, false),
    queryFn: () => phase5Api.conflicts.list(candidateId, true).then((r) => r.data),
    enabled: Number.isFinite(candidateId) && candidateId > 0,
    staleTime: 60_000,
    retry: false,
  });
  return (query.data ?? []).filter((row) => row.active);
}

function ContactRow({
  candidate,
  canWrite,
  onEmail,
}: {
  candidate: any;
  canWrite: boolean;
  onEmail: () => void;
}) {
  const { showError, showSuccess } = useToast();
  const href = linkedinHref(candidate.linkedin);
  const copy = (value: string, what: string) => {
    if (!navigator.clipboard?.writeText) {
      showError(`Nie udało się skopiować — zaznacz ${what} i skopiuj ręcznie.`);
      return;
    }
    navigator.clipboard.writeText(value).then(
      () => showSuccess(`Skopiowano ${what}`),
      () => showError(`Nie udało się skopiować — zaznacz ${what} i skopiuj ręcznie.`),
    );
  };
  if (!candidate.email && !candidate.phone && !href) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
      {candidate.email ? (
        <span className={CONTACT_CLASS}>
          <Mail className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          {canWrite ? (
            // Klik w adres otwiera okno maila z Microsoft 365 (zapis w historii) —
            // dawny `mailto:` szedł obok, z prywatnego programu pocztowego.
            <button
              type="button"
              onClick={onEmail}
              className="min-w-0 truncate text-left hover:text-primary hover:underline"
              title="Napisz maila z Microsoft 365"
            >
              {candidate.email}
            </button>
          ) : (
            <span className="min-w-0 select-all truncate">{candidate.email}</span>
          )}
          <button
            type="button"
            onClick={() => copy(candidate.email, "adres e-mail")}
            aria-label="Kopiuj adres e-mail"
            className="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Copy className="size-3.5" aria-hidden />
          </button>
        </span>
      ) : null}
      {candidate.phone ? (
        <span className={CONTACT_CLASS}>
          <Phone className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="select-all tabular-nums">{formatPhone(candidate.phone)}</span>
          <button
            type="button"
            onClick={() => copy(candidate.phone, "numer telefonu")}
            aria-label="Kopiuj numer telefonu"
            className="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Copy className="size-3.5" aria-hidden />
          </button>
        </span>
      ) : null}
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" className={`${CONTACT_CLASS} hover:text-primary`}>
          <Linkedin className="size-3.5 shrink-0 text-brand-linkedin" aria-hidden />
          LinkedIn
        </a>
      ) : null}
    </div>
  );
}

function MenuItem({
  icon,
  children,
  onSelect,
  disabled,
  title,
  destructive,
}: {
  icon: ReactNode;
  children: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  title?: string;
  destructive?: boolean;
}) {
  // Otwieramy na następnym tiku, gdy Radix skończy zamykać menu — inaczej
  // dialog otwarty z menu potrafił się zamknąć (issue 533).
  return (
    <DropdownMenuItem
      className={destructive ? "min-h-11 text-destructive focus:text-destructive" : "min-h-11"}
      disabled={disabled}
      title={title}
      onSelect={() => setTimeout(onSelect, 0)}
    >
      {icon}
      {children}
    </DropdownMenuItem>
  );
}

function MenuGroupLabel({ children }: { children: ReactNode }) {
  return <DropdownMenuLabel className="pt-2">{children}</DropdownMenuLabel>;
}

function latestCvTitle(doc: CandidateDocument): string {
  const added = [
    `wgrane ${formatDate(doc.uploaded_at ?? doc.created_at)}`,
    doc.uploaded_by_name ? `przez ${doc.uploaded_by_name}` : null,
  ]
    .filter(Boolean)
    .join(" ");
  return `${doc.filename} · ${added}`;
}

function PersonActions({
  candidate,
  actions,
  canWrite,
}: {
  candidate: any;
  actions: ProfilePersonBarActions;
  canWrite: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {canWrite ? (
        <>
          <Button
            size="sm"
            variant="primary"
            className="min-h-11 min-w-11"
            onClick={actions.onAssign}
            data-help="candidate.profile.assign"
          >
            <UserPlus className="h-4 w-4" />
            Przypisz do rekrutacji
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={actions.onAddNote}
            data-help="candidate.profile.note"
          >
            <MessageSquare className="h-4 w-4" />
            Dodaj notatkę
          </Button>
          {actions.onNoAnswer ? (
            <Button
              size="sm"
              variant="outline"
              className="min-h-11 min-w-11"
              onClick={actions.onNoAnswer}
              loading={actions.noAnswerSaving}
              title="Zapisuje próbę kontaktu jednym kliknięciem — trafia do „Prób kontaktu”"
            >
              <PhoneMissed className="h-4 w-4" />
              Nie odebrał
            </Button>
          ) : null}
          {/* Listy ręczne w „Moich ludziach” (prośba Olafa, 25.10.2026). */}
          <AddToListButton candidateId={candidate.id} />
        </>
      ) : null}
      {actions.latestCv && actions.onOpenLatestCv ? (
        <Button
          size="sm"
          variant="outline"
          className="min-h-11 min-w-11"
          onClick={actions.onOpenLatestCv}
          title={latestCvTitle(actions.latestCv)}
        >
          <FileText className="h-4 w-4" />
          Najnowsze CV
        </Button>
      ) : null}
      {/* modal={false} jest nośne: modalne menu zostawia zablokowane
          pointer-events na body podczas zamykania, więc dialog otwarty z menu
          zamykał się w tym samym tiku (issue 533). */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" className="min-h-11 min-w-11" aria-label="Więcej akcji">
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          {canWrite ? (
            <>
              <MenuGroupLabel>Kontakt</MenuGroupLabel>
              <DropdownMenuGroup>
                <MenuItem
                  icon={<Mail className="h-4 w-4" />}
                  disabled={!candidate.email}
                  title={candidate.email ? undefined : "Kandydat nie ma adresu e-mail"}
                  onSelect={actions.onEmail}
                >
                  Napisz maila
                </MenuItem>
                <MenuItem
                  icon={<Calendar className="h-4 w-4" />}
                  disabled={!candidate.email}
                  title={
                    candidate.email
                      ? "Zaproszenie na rozmowę wysyłane z Outlooka (M365)"
                      : "Kandydat nie ma adresu e-mail"
                  }
                  onSelect={actions.onScheduleInterview}
                >
                  Zaplanuj rozmowę
                </MenuItem>
                {/* Osobno od „Zaplanuj rozmowę”: tamto WYSYŁA przez Graph, to daje
                    szkic do własnego Outlooka, żeby rekruter dołożył CV. */}
                <MenuItem
                  icon={<CalendarPlus className="h-4 w-4" />}
                  title="Szkic zaproszenia prep do wysłania z własnego Outlooka (z CV)"
                  onSelect={actions.onPrepInvite}
                >
                  Zaproś na prep
                </MenuItem>
                {actions.onFollowup ? (
                  <MenuItem icon={<CalendarPlus className="h-4 w-4" />} onSelect={actions.onFollowup}>
                    {actions.followupLabel ?? "Spotkania i follow-up"}
                  </MenuItem>
                ) : null}
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
            </>
          ) : null}
          <MenuGroupLabel>Dane</MenuGroupLabel>
          <DropdownMenuGroup>
            {canWrite ? (
              <MenuItem
                icon={<PencilLine className="h-4 w-4" />}
                title="Imię, nazwisko, kontakt i pozostałe dane"
                onSelect={actions.onEdit}
              >
                Edytuj dane
              </MenuItem>
            ) : null}
            <MenuItem icon={<Tags className="h-4 w-4" />} onSelect={actions.onTagsPools}>
              Tagi i pule
            </MenuItem>
            <MenuItem icon={<ShieldAlert className="h-4 w-4" />} onSelect={actions.onConflicts}>
              Konflikty i weta
            </MenuItem>
            {canWrite && actions.onMerge ? (
              <MenuItem icon={<Combine className="h-4 w-4" />} onSelect={actions.onMerge}>
                Scal z…
              </MenuItem>
            ) : null}
          </DropdownMenuGroup>
          {/* 17.10.2026: jedno okno na czarną listę „u nas” i „u klienta” —
              zamiast statusu „Zablokowany” w „Edytuj dane”. */}
          {canWrite && actions.onBlacklist ? (
            <>
              <DropdownMenuSeparator />
              <MenuGroupLabel>Status osoby</MenuGroupLabel>
              <DropdownMenuGroup>
                <MenuItem icon={<Ban className="h-4 w-4" />} destructive onSelect={actions.onBlacklist}>
                  Czarna lista…
                </MenuItem>
              </DropdownMenuGroup>
            </>
          ) : null}
          {/* Trwałe usunięcie — tylko admin. Brak pozycji zamiast `disabled`:
              wyszarzona opcja zapraszałaby do proszenia o nią. */}
          {canWrite && actions.onDelete ? (
            <>
              <DropdownMenuSeparator />
              <MenuItem icon={<Trash2 className="h-4 w-4" />} destructive onSelect={actions.onDelete}>
                Usuń profil
              </MenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
