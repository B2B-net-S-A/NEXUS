import { Badge, type BadgeProps } from "@/components/ui/badge";
import type {
  CandidateContactCaseStatus,
  CandidateContactSummary,
} from "@/lib/candidate-contact";
import { cn } from "@/lib/utils";

const STATUS_PRESENTATION: Record<
  CandidateContactCaseStatus,
  { label: string; variant: NonNullable<BadgeProps["variant"]> }
> = {
  unassigned: { label: "Nieprzydzielony", variant: "danger" },
  awaiting_capacity: { label: "Czeka na miejsce", variant: "warning" },
  queued: { label: "Do przedzwonienia", variant: "info" },
  callback_due: { label: "Callback", variant: "warning" },
  cooldown: { label: "Cooldown", variant: "neutral" },
  handoff_pending: { label: "Po rozmowie", variant: "soft" },
  blocked_no_phone: { label: "Brak numeru", variant: "danger" },
  suppressed: { label: "Nie kontaktować", variant: "danger" },
  completed: { label: "Kontakt zakończony", variant: "success" },
  cancelled: { label: "Anulowany", variant: "neutral" },
};

export interface ContactStatusBadgeProps {
  contactCase: Pick<CandidateContactSummary, "status"> | null | undefined;
  size?: BadgeProps["size"];
  className?: string;
  showHistorical?: boolean;
}

export function ContactStatusBadge({
  contactCase,
  size = "sm",
  className,
  showHistorical = true,
}: ContactStatusBadgeProps) {
  if (contactCase === undefined) return null;
  if (contactCase === null) {
    if (!showHistorical) return null;
    return (
      <Badge
        variant="outline"
        size={size}
        className={cn("text-muted-foreground", className)}
      >
        Brak danych sprzed uruchomienia
      </Badge>
    );
  }

  const presentation = STATUS_PRESENTATION[contactCase.status];
  return (
    <Badge variant={presentation.variant} size={size} className={className}>
      {presentation.label}
    </Badge>
  );
}
