"use client";

/**
 * Karta osoby — górna część lewej kolumny profilu (od 04.10.2026, wariant B):
 * tożsamość, jeden status, jedna kategoria kompetencji, najwyżej jedno
 * ostrzeżenie, kontakt, „Pracuje u nas”, akcje i menu „⋯” w grupach.
 *
 * Fakty (dostępność, stawka, tryb pracy, miasto, języki, narodowość) NIE są
 * tutaj — mają jedno miejsce: kartę „Podsumowanie” (`CandidateProfileFactsBar`
 * w układzie `column`) zaraz pod tą kartą. Tagi i pule są w „⋯ → Tagi i pule”.
 */

import type { ComponentProps, ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  Ban,
  Calendar,
  CalendarPlus,
  Combine,
  FileText,
  Linkedin,
  Mail,
  MessageSquare,
  MoreHorizontal,
  PencilLine,
  PhoneMissed,
  Pin,
  PinOff,
  ShieldAlert,
  Store,
  Tags,
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
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CandidateNav } from "@/components/v2/CandidateNav";
import { CompetenceCategoryBadge } from "@/components/v2/CompetenceCategoryBadge";
import { AtOurClientBanner } from "@/components/v2/CandidateHighlights";
import { candidatePinsApi } from "@/lib/api";
import { RiskBadge } from "@/components/v2/RiskBadge";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import type { CandidateContactCase } from "@/lib/candidate-contact";
import type { PresenceViewer } from "@/hooks/usePresence";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import { IdentityEditor } from "@/components/v2/pages/CandidateIdentityEditor";
import { getCandidateInitials } from "@/components/v2/pages/candidate-list-helpers";
import { candidateHeadline, linkedinHref, pickHeaderWarning } from "./profile-helpers";

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
  const backLabel = backJobTitle ? `Wróć do rekrutacji: ${backJobTitle}` : "Wróć do rekrutacji";
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

// ── Karta osoby ────────────────────────────────────────────────────────────

export interface ProfileHeaderActions {
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
  onGenerateCv: () => void;
  onEdit: () => void;
  onTagsPools: () => void;
  onConflicts: () => void;
  onMarketplace: () => void;
  /** Korekta imienia/nazwiska z blokadą synchronizacji Traffita. */
  onEditIdentity?: () => void;
  /** Tylko admin (`canHardDeleteCandidate`). */
  onDelete?: () => void;
  /** „Scal z…” — admin i Head of Recruitment (`canMergeCandidates`). */
  onMerge?: () => void;
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

const CONTACT_LINK_CLASS =
  "inline-flex min-h-11 max-2xl:pointer-fine:min-h-7 min-w-0 items-center gap-1.5 hover:text-primary";

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

  return (
    <Card variant="default" size="md" className="overflow-hidden p-0!">
      <div className="space-y-3 p-4 md:max-2xl:p-3">
        <div className="flex items-start gap-3">
          <Avatar size="lg">
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>

          <div className="min-w-0 flex-1">
            {editingIdentity && canWrite ? (
              <IdentityEditor candidate={candidate} onClose={onCloseIdentityEditor} />
            ) : (
              <>
                <h1 className="break-words text-xl font-extrabold leading-tight tracking-heading-tight text-foreground">
                  {fullName}
                </h1>
                {headline ? (
                  <p className="mt-0.5 text-sm text-muted-foreground">{headline}</p>
                ) : null}
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {warning?.kind !== "blacklist" && STATUS_LABELS[candidate.status] ? (
                    <Badge variant={STATUS_VARIANT[candidate.status] ?? "neutral"} size="sm">
                      {STATUS_LABELS[candidate.status]}
                    </Badge>
                  ) : null}
                  <CompetenceCategoryBadge
                    categoryId={candidate.competence_category_id}
                    slug={candidate.competence_category}
                    size="sm"
                  />
                  {warning?.kind === "blacklist" ? (
                    <Badge variant="danger" size="sm">
                      <Ban className="h-3 w-3" />
                      Czarna lista
                    </Badge>
                  ) : warning?.kind === "risk" && riskProfile ? (
                    <RiskBadge profile={riskProfile} hideLow />
                  ) : null}
                </div>
              </>
            )}
          </div>

          <div className="flex shrink-0 items-start gap-1">
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
        </div>

        {!editingIdentity ? (
          <div className="flex flex-col gap-y-0.5 text-sm text-foreground">
            {candidate.email ? (
              <a href={`mailto:${candidate.email}`} className={`${CONTACT_LINK_CLASS} break-all`}>
                <Mail className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 break-all">{candidate.email}</span>
              </a>
            ) : null}
            {candidate.phone && canWrite && canCall ? (
              <CallButton
                candidateId={candidateId}
                phone={candidate.phone}
                compact
                className="min-h-11 max-2xl:pointer-fine:min-h-7 min-w-11 self-start"
              />
            ) : candidate.phone ? (
              <span className="inline-flex min-h-7 items-center gap-1.5 tabular-nums">
                {candidate.phone}
              </span>
            ) : null}
            {linkedinHref(candidate.linkedin) ? (
              <a
                href={linkedinHref(candidate.linkedin) ?? undefined}
                target="_blank"
                rel="noreferrer"
                className={`${CONTACT_LINK_CLASS} self-start`}
              >
                <Linkedin className="h-3.5 w-3.5 shrink-0 text-brand-linkedin" />
                LinkedIn
              </a>
            ) : null}
            {showContactStatus || onLogContactOutcome ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
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
            ) : null}
          </div>
        ) : null}

        {candidate.employment ? (
          <AtOurClientBanner employment={candidate.employment} variant="compact" />
        ) : null}

        {/* Bez prawa zapisu zostaje samo menu „⋯” z oknami do odczytu
            (tagi i pule, konflikty i weta) — przed 04.10.2026 te listy stały
            na widoku dla każdej roli. */}
        <HeaderActions candidate={candidate} actions={actions} canWrite={canWrite} />
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

/**
 * „Obserwuj” = osobiste przypięcie kandydata (lista nad „Kandydatami”).
 * Dawniej ikona pinezki w nagłówku — ta sama nazwa co przypięcie notatki
 * dla zespołu, choć to dwie różne rzeczy.
 */
function useCandidateWatch(candidateId: number) {
  const queryClient = useQueryClient();
  const state = useQuery({
    queryKey: ["candidate-pin-state", candidateId],
    queryFn: () => candidatePinsApi.getState(candidateId).then((r) => r.data),
    enabled: Number.isFinite(candidateId) && candidateId > 0,
    staleTime: 30_000,
  });
  const toggle = useMutation({
    mutationFn: () => candidatePinsApi.toggle(candidateId).then((r) => r.data),
    onSuccess: (resp) => {
      queryClient.setQueryData(["candidate-pin-state", candidateId], resp);
      void queryClient.invalidateQueries({ queryKey: ["candidate-pins"] });
    },
  });
  return {
    watching: Boolean(state.data?.pinned),
    disabled: state.isLoading || toggle.isPending,
    toggle: () => toggle.mutate(),
  };
}

function MenuGroupLabel({ children }: { children: ReactNode }) {
  return <DropdownMenuLabel className="pt-2">{children}</DropdownMenuLabel>;
}

function HeaderActions({
  candidate,
  actions,
  canWrite,
}: {
  candidate: any;
  actions: ProfileHeaderActions;
  canWrite: boolean;
}) {
  const watch = useCandidateWatch(Number(candidate.id));
  return (
    <div className="space-y-2">
      <div className={canWrite ? "flex items-center gap-2" : "flex items-center justify-end gap-2"}>
        {canWrite ? (
          <Button
            size="sm"
            variant="primary"
            className="min-h-11 min-w-11 flex-1"
            onClick={actions.onAssign}
            data-help="candidate.profile.assign"
          >
            <UserPlus className="h-4 w-4" />
            Przypisz do rekrutacji
          </Button>
        ) : null}
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
                    <MenuItem
                      icon={<CalendarPlus className="h-4 w-4" />}
                      onSelect={actions.onFollowup}
                    >
                      {actions.followupLabel ?? "Spotkania i follow-up"}
                    </MenuItem>
                  ) : null}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <MenuGroupLabel>Dokumenty</MenuGroupLabel>
                <MenuItem icon={<FileText className="h-4 w-4" />} onSelect={actions.onGenerateCv}>
                  Generuj CV
                </MenuItem>
                <DropdownMenuSeparator />
              </>
            ) : null}
            <MenuGroupLabel>Dane</MenuGroupLabel>
            <DropdownMenuGroup>
              {canWrite ? (
                <MenuItem icon={<PencilLine className="h-4 w-4" />} onSelect={actions.onEdit}>
                  Edytuj dane
                </MenuItem>
              ) : null}
              {canWrite && actions.onEditIdentity ? (
                <MenuItem
                  icon={<UserRoundPen className="h-4 w-4" />}
                  title="Imię, nazwisko i kontakt z informacją o synchronizacji z Traffita"
                  onSelect={actions.onEditIdentity}
                >
                  Korekta imienia i nazwiska
                </MenuItem>
              ) : null}
              <MenuItem icon={<Tags className="h-4 w-4" />} onSelect={actions.onTagsPools}>
                Tagi i pule
              </MenuItem>
              {canWrite && actions.onMerge ? (
                <MenuItem icon={<Combine className="h-4 w-4" />} onSelect={actions.onMerge}>
                  Scal z…
                </MenuItem>
              ) : null}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <MenuGroupLabel>Inne</MenuGroupLabel>
            <DropdownMenuGroup>
              <MenuItem
                icon={watch.watching ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
                disabled={watch.disabled}
                title="Twoja lista obserwowanych kandydatów nad listą „Kandydaci”"
                onSelect={watch.toggle}
              >
                {watch.watching ? "Przestań obserwować" : "Obserwuj"}
              </MenuItem>
              {canWrite ? (
                <MenuItem icon={<Store className="h-4 w-4" />} onSelect={actions.onMarketplace}>
                  Wrzuć na targ
                </MenuItem>
              ) : null}
              <MenuItem icon={<ShieldAlert className="h-4 w-4" />} onSelect={actions.onConflicts}>
                Konflikty i weta
              </MenuItem>
            </DropdownMenuGroup>
            {/* Trwałe usunięcie — tylko admin. Brak pozycji zamiast `disabled`:
                wyszarzona opcja zapraszałaby do proszenia o nią. */}
            {canWrite && actions.onDelete ? (
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
      </div>
      {canWrite ? (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="min-h-11 min-w-11 flex-1"
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
              className="min-h-11 min-w-11 flex-1"
              onClick={actions.onNoAnswer}
              loading={actions.noAnswerSaving}
              title="Zapisuje próbę kontaktu jednym kliknięciem — trafia do „Prób kontaktu”"
            >
              <PhoneMissed className="h-4 w-4" />
              Nie odebrał
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
