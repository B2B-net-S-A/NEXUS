import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  stageLabel,
  stageTone,
} from "@/components/v2/pages/candidate-list-helpers";

interface StagePillProps {
  /** Pipeline stage key, e.g. "cv_sent". */
  stage: string;
  /** Override the derived Polish label. */
  label?: string;
  size?: "sm" | "md";
  className?: string;
}

/** Coloured pipeline-stage pill with a leading status dot.
 *
 *  Reuses the DS {@link Badge} for the token-based background/text/border and
 *  adds the dot the Badge itself doesn't carry. Colour comes from
 *  {@link stageTone}, so every stage stays token-first and theme/dark aware. */
export function StagePill({ stage, label, size = "md", className }: StagePillProps) {
  const tone = stageTone(stage);
  return (
    <Badge
      variant={tone.variant}
      size={size}
      className={cn("gap-1.5 font-semibold", className)}
    >
      <span
        aria-hidden
        className={cn("size-1.5 shrink-0 rounded-full", tone.dot)}
      />
      {label ?? stageLabel(stage)}
    </Badge>
  );
}
