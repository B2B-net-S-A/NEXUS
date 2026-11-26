import type { BadgeProps } from "@/components/ui/badge";
import type { ChipTone, DeadlineTone } from "@/lib/competence-reports/logic";

/** Ton chipu stanu → wariant `Badge` (same tokeny). */
export const CHIP_VARIANT: Record<ChipTone, NonNullable<BadgeProps["variant"]>> = {
  neutral: "neutral",
  info: "info",
  success: "success",
  warning: "warning",
  danger: "danger",
};

export const DEADLINE_CLASS: Record<DeadlineTone, string> = {
  late: "text-destructive",
  soon: "text-warning-muted-foreground",
  ok: "text-foreground",
  done: "text-muted-foreground",
};
