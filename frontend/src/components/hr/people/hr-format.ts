import type { StatusDotTone } from "@/components/ds/StatusDot";
import type { EmploymentStatus } from "@/lib/api/hr";

/** Inicjały do kółka przy osobie („Anna Przykładowa” → „AP”). */
export function personInitials(name: string): string {
  const parts = name
    .replace(/[^\p{L}\s-]/gu, " ")
    .split(/[\s-]+/)
    .filter(Boolean);
  if (parts.length === 0) return "—";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "";
  return (first + last).toUpperCase();
}

export const STATUS_TONE: Record<EmploymentStatus, StatusDotTone> = {
  pending: "info",
  onboarding: "info",
  active: "success",
  offboarding: "warning",
  exited: "neutral",
};

/** „12,5” — dni z połówkami, polski przecinek. */
export function formatDays(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("pl-PL", { maximumFractionDigits: 1 });
}
