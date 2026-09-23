"use client";

/**
 * Nagłówek profilu kandydata — JEDNA karta: tożsamość, jeden status, jedna
 * kategoria kompetencji, najwyżej jedno ostrzeżenie, kontakt, akcje i pasek
 * faktów (dostępność, stawka B2B, lokalizacja, języki — jedyne miejsce, gdzie
 * te fakty są pokazywane i edytowane).
 */

import type { ComponentProps, ReactNode } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Ban,
  Calendar,
  CalendarPlus,
  FileText,
  Linkedin,
  Mail,
  MessageSquare,
  MoreHorizontal,
  PencilLine,
  Store,
  Trash2,
  UserPlus,
  UserRoundPen,
  X,
} from "lucide-react";

import CallButton from "@/components/calls/CallButton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CandidateNav } from "@/components/v2/CandidateNav";
import { CompetenceCategoryBadge } from "@/components/v2/CompetenceCategoryBadge";
import { PinButton } from "@/components/v2/PinButton";
import { RiskBadge } from "@/components/v2/RiskBadge";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import type { CandidateContactCase } from "@/lib/candidate-contact";
import type { PresenceViewer } from "@/hooks/usePresence";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import { CandidateProfileFactsBar } from "@/components/v2/pages/CandidateProfileFactsBar";
import { IdentityEditor } from "@/components/v2/pages/CandidateIdentityEditor";
import {
  getCandidateInitials,
  getTagName,
} from "@/components/v2/pages/candidate-list-helpers";
import { candidateHeadline, pickHeaderWarning } from "./profile-helpers";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload kandydata jest luźno typowany */

const STATUS_VARIANT: Record<string, "success" | "warning" | "neutral"> = {
  active: "success",
  passive: "warning",
};
const STATUS_LABELS: Record<string, string> = {
  active: "Aktywny",
  passive: "Pasywny",
};

// ── Pasek nad nagłówkiem: powrót + poprzedni/następny ─────────────────────

type CandidateNavProps = ComponentProps<typeof CandidateNav>;

export function ProfileTopBar({
  embedded,
  nav,
  backJobId,
  backJobTitle,
  backToTalentRadar,
  candidateId,
}: {
  embedded: boolean;
  /** Właściwości paska poprzedni/następny; `null` = brak kontekstu listy. */
  nav: CandidateNavProps | null;
  backJobId: number | null;
  backJobTitle: string | null;
  backToTalentRadar: boolean;
  candidateId: number;
}) {
  if (embedded) return nav ? <CandidateNav {...nav} /> : null;
  const backClass =
    "inline-flex min-h-11 min-w-11 items-center gap-1 px-2 text-sm text-muted-foreground hover:text-primary";
  const backLabel = backJobTitle
    ? `Wróć do rekrutacji: ${backJobTitle}`
    : "Wróć do rekrutacji";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {backJobId != null ? (
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
      {nav ? <CandidateNav {...nav} className="ml-auto" /> : null}
    </div>
  );
}

// ── Karta nagłówka ─────────────────────────────────────────────────────────

export interface ProfileHeaderActions {
  onAssign: () => void;
  onAddNote: () => void;
  onEmail: () => void;
  onScheduleInterview: () => void;
  onPrepInvite: () => void;
  onGenerateCv: () => void;
  onEdit: () => void;
  onMarketplace: () => void;
  /** Korekta imienia/nazwiska z blokadą synchronizacji Traffita. */
  onEditIdentity?: () => void;
  /** Tylko admin (`canHardDeleteCandidate`). */
  onDelete?: () => void;
}

export interface ProfileHeaderProps {
  candidate: any;
  candidateId: number;
  canWrite: boolean;
  /** CloudTalk: przycisk dzwonienia zamiast samego numeru. */
  canCall: boolean;
  riskProfile?: CandidateRiskProfile | null;
  contactCase?: CandidateContactCase | null;
  showContactStatus: boolean;
  /** „Zaloguj wynik” — kolejka kontaktu właściciela sprawy. */
  onLogContactOutcome?: () => void;
  viewers: PresenceViewer[];
  editingIdentity: boolean;
  onCloseIdentityEditor: () => void;
  /** Przycisk zamknięcia w szufladzie bez paska nawigacji. */
  onClose?: () => void;
  actions: ProfileHeaderActions;
}

export function ProfileHeader({
  candidate,
  candidateId,
  canWrite,
  canCall,
  riskProfile,
  contactCase,
  showContactStatus,
  onLogContactOutcome,
  viewers,
  editingIdentity,
  onCloseIdentityEditor,
  onClose,
  actions,
}: ProfileHeaderProps) {
  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const initials = getCandidateInitials(candidate) || "?";
  const headline = candidateHeadline(candidate);
  const warning = pickHeaderWarning({
    status: candidate.status,
    employmentState: candidate.employment?.state,
    riskLevel: riskProfile?.level,
  });
  const tagNames: string[] = Array.isArray(candidate.tags)
    ? Array.from(
        new Set(
          (candidate.tags as unknown[])
            .map((t) => getTagName(t))
            .filter((n): n is string => typeof n === "string"),
        ),
      )
    : [];

  return (
    <Card variant="default" size="md" className="overflow-hidden p-0!">
      <div className="space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-start gap-4">
          <Avatar size="xl">
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>

          <div className="min-w-0 flex-1">
            {editingIdentity && canWrite ? (
              <IdentityEditor candidate={candidate} onClose={onCloseIdentityEditor} />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-extrabold tracking-heading-tight text-foreground md:text-3xl">
                    {fullName}
                  </h1>
                  {warning?.kind !== "blacklist" && STATUS_LABELS[candidate.status] ? (
                    <Badge variant={STATUS_VARIANT[candidate.status] ?? "neutral"} size="md">
                      {STATUS_LABELS[candidate.status]}
                    </Badge>
                  ) : null}
                  <CompetenceCategoryBadge
                    categoryId={candidate.competence_category_id}
                    slug={candidate.competence_category}
                    size="md"
                  />
                  {warning?.kind === "blacklist" ? (
                    <Badge variant="danger" size="md">
                      <Ban className="h-3 w-3" />
                      Czarna lista
                    </Badge>
                  ) : warning?.kind === "risk" && riskProfile ? (
                    <RiskBadge profile={riskProfile} hideLow />
                  ) : null}
                </div>
                {headline ? (
                  <p className="mt-0.5 text-sm text-foreground">{headline}</p>
                ) : null}

                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-foreground">
                  {candidate.email ? (
                    <a
                      href={`mailto:${candidate.email}`}
                      className="inline-flex min-h-11 min-w-0 items-center gap-1.5 break-all hover:text-primary"
                    >
                      <Mail className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      {candidate.email}
                    </a>
                  ) : null}
                  {candidate.phone && canWrite && canCall ? (
                    <CallButton
                      candidateId={candidateId}
                      phone={candidate.phone}
                      compact
                      className="min-h-11 min-w-11"
                    />
                  ) : candidate.phone ? (
                    <span className="inline-flex items-center gap-1.5">{candidate.phone}</span>
                  ) : null}
                  {candidate.linkedin_url ? (
                    <a
                      href={candidate.linkedin_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex min-h-11 min-w-11 items-center gap-1.5 hover:text-primary"
                    >
                      <Linkedin className="h-3.5 w-3.5 shrink-0 text-brand-linkedin" />
                      LinkedIn
                    </a>
                  ) : null}
                  {showContactStatus ? (
                    <ContactStatusBadge contactCase={contactCase} size="sm" />
                  ) : null}
                  {onLogContactOutcome ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="min-h-11 min-w-11"
                      onClick={onLogContactOutcome}
                    >
                      Zaloguj wynik
                    </Button>
                  ) : null}
                </div>

                {tagNames.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {tagNames.map((name) => (
                      <span
                        key={name}
                        className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary"
                      >
                        #{name}
                      </span>
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ActiveViewers
              resourceType="candidate"
              resourceId={Number.isFinite(candidateId) ? candidateId : null}
              viewers={viewers}
            />
            {canWrite ? (
              <HeaderActions candidate={candidate} actions={actions} />
            ) : null}
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
        </div>

        <CandidateProfileFactsBar candidate={candidate} />
      </div>
    </Card>
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
  // dialog otwarty z menu w szufladzie potrafił się zamknąć (issue 533).
  return (
    <DropdownMenuItem
      className={
        destructive
          ? "min-h-11 text-destructive focus:text-destructive"
          : "min-h-11"
      }
      disabled={disabled}
      title={title}
      onSelect={() => setTimeout(onSelect, 0)}
    >
      {icon}
      {children}
    </DropdownMenuItem>
  );
}

function HeaderActions({
  candidate,
  actions,
}: {
  candidate: any;
  actions: ProfileHeaderActions;
}) {
  return (
    <>
      <PinButton candidateId={candidate.id} iconOnly className="min-h-11 min-w-11" />
      <Button size="sm" variant="outline" className="min-h-11 min-w-11" onClick={actions.onAddNote} data-help="candidate.profile.note">
        <MessageSquare className="h-4 w-4" />
        Dodaj notatkę
      </Button>
      <Button size="sm" variant="primary" className="min-h-11 min-w-11" onClick={actions.onAssign} data-help="candidate.profile.assign">
        <UserPlus className="h-4 w-4" />
        Przypisz do rekrutacji
      </Button>
      {/* modal={false} jest nośne: modalne menu zostawia zablokowane
          pointer-events na body podczas zamykania, więc dialog otwarty z menu
          w szufladzie zamykał się w tym samym tiku (issue 533). */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            className="min-h-11 min-w-11"
            aria-label="Więcej akcji"
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
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
          <MenuItem icon={<FileText className="h-4 w-4" />} onSelect={actions.onGenerateCv}>
            Generuj CV
          </MenuItem>
          <DropdownMenuSeparator />
          <MenuItem icon={<PencilLine className="h-4 w-4" />} onSelect={actions.onEdit}>
            Edytuj dane
          </MenuItem>
          {actions.onEditIdentity ? (
            <MenuItem
              icon={<UserRoundPen className="h-4 w-4" />}
              title="Imię, nazwisko i kontakt z informacją o synchronizacji z Traffita"
              onSelect={actions.onEditIdentity}
            >
              Korekta imienia i nazwiska
            </MenuItem>
          ) : null}
          <MenuItem icon={<Store className="h-4 w-4" />} onSelect={actions.onMarketplace}>
            Wrzuć na targ
          </MenuItem>
          {/* Trwałe usunięcie — tylko admin. Brak pozycji zamiast `disabled`:
              wyszarzona opcja zapraszałaby do proszenia o nią. */}
          {actions.onDelete ? (
            <>
              <DropdownMenuSeparator />
              <MenuItem
                icon={<Trash2 className="h-4 w-4" />}
                destructive
                onSelect={actions.onDelete}
              >
                Usuń profil
              </MenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
