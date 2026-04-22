import { Badge } from "@/components/ui/badge";
import { Sparkles } from "lucide-react";

export type ConfidenceBand = "high" | "medium" | "low";

interface ConfidenceBadgeProps {
  /** Either a precomputed band or a 0..1 score. */
  band?: ConfidenceBand;
  score?: number;
  withIcon?: boolean;
  label?: string;
  className?: string;
}

function scoreToBand(score: number): ConfidenceBand {
  if (score >= 0.65) return "high";
  if (score >= 0.4) return "medium";
  return "low";
}

const BAND_LABEL: Record<ConfidenceBand, string> = {
  high: "Wysoka",
  medium: "Średnia",
  low: "Niska",
};

const BAND_VARIANT: Record<ConfidenceBand, "success" | "info" | "warning"> = {
  high: "success",
  medium: "info",
  low: "warning",
};

/**
 * Three-step confidence pill used across AI-suggestion UI. Shows a numeric
 * score in the tooltip for power users but never in the visible chip itself
 * ("Wysoka/Średnia/Niska" is what recruiters read).
 */
export function ConfidenceBadge({
  band,
  score,
  withIcon = true,
  label,
  className,
}: ConfidenceBadgeProps) {
  const resolvedBand: ConfidenceBand =
    band ?? (typeof score === "number" ? scoreToBand(score) : "medium");
  const variant = BAND_VARIANT[resolvedBand];
  const text = label ?? BAND_LABEL[resolvedBand];
  const tooltip =
    typeof score === "number" ? `${Math.round(score * 100)}% dopasowania` : text;
  return (
    <Badge variant={variant} size="sm" className={className} title={tooltip}>
      {withIcon ? <Sparkles className="w-3 h-3" /> : null}
      {text}
    </Badge>
  );
}
