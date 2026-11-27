// Kolory tonów ekranu Bezpieczeństwo — wyłącznie tokeny design systemu.
import type { Tone } from "./security-model";

export const TONE_BADGE: Record<Tone, "success" | "warning" | "danger" | "info" | "outline"> = {
  success: "success",
  warning: "warning",
  danger: "danger",
  info: "info",
  neutral: "outline",
};

/** Lewy pasek kafelka. */
export const TONE_STRIPE: Record<Tone, string> = {
  success: "border-l-success",
  warning: "border-l-warning",
  danger: "border-l-destructive",
  info: "border-l-info",
  neutral: "border-l-border",
};

/** Plakietka w kalendarzu. */
export const TONE_CHIP: Record<Tone, string> = {
  success: "bg-success-muted text-success-muted-foreground",
  warning: "bg-warning-muted text-warning-muted-foreground",
  danger: "bg-destructive-muted text-destructive-muted-foreground",
  info: "bg-info-muted text-info-muted-foreground",
  neutral: "bg-muted text-muted-foreground",
};
