import { Award, GraduationCap, Gift, Plane, Receipt, RefreshCw } from "lucide-react";

import type { ApprovalKind } from "@/lib/api/hr-approvals";
import { cn } from "@/lib/utils";

const ICONS: Record<ApprovalKind, typeof Award> = {
  bonus: Award,
  subscription: RefreshCw,
  trip: Plane,
  gift: Gift,
  training: GraduationCap,
  other: Receipt,
};

/** Ikona rodzaju zgody (jeden neutralny kolor — rodzaj niesie też etykieta). */
export function KindIcon({ kind, className }: { kind: ApprovalKind; className?: string }) {
  const Icon = ICONS[kind];
  return (
    <span
      aria-hidden
      className={cn(
        "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary",
        className,
      )}
    >
      <Icon className="h-4 w-4" />
    </span>
  );
}
