import * as React from "react";

import { cn } from "@/lib/utils";
import {
  type CandidateDetailData,
  SkillChip,
} from "@/components/v2/candidates/CandidateDetailPanel";

interface CandidateRowDetailProps {
  candidate: CandidateDetailData;
  /** Left inset so the block aligns under the row's name column. */
  className?: string;
}

/** Inline detail revealed when a table row is expanded (design option 1a).
 *
 *  Shows the dense prose + facts that the compact row hides: headline, a facts
 *  grid, the full skill set, the last note, and a rejection reason. Pure
 *  presentation, token-first. */
export function CandidateRowDetail({ candidate: c, className }: CandidateRowDetailProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 border-t border-dashed border-border bg-muted/30 px-6 py-4 pl-[4.5rem]",
        className,
      )}
    >
      {c.headline ? (
        <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
          {c.headline}
        </p>
      ) : null}

      {c.detailPairs.length > 0 ? (
        <dl className="grid max-w-3xl grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
          {c.detailPairs.map((p) => (
            <div key={p.label}>
              <dt className="text-[10px] font-semibold uppercase tracking-[0.05em] text-muted-foreground/70">
                {p.label}
              </dt>
              <dd className="mt-0.5 text-sm text-foreground">{p.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {c.skills.length > 0 ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Umiejętności
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {c.skills.map((s) => (
              <SkillChip key={s}>{s}</SkillChip>
            ))}
          </div>
        </div>
      ) : null}

      {c.lastNote || c.rejectionReason ? (
        <div className="flex flex-wrap gap-3">
          {c.lastNote ? (
            <div className="min-w-[280px] flex-1 rounded-xl border border-border bg-card p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                Ostatnia notatka
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-foreground/80">
                {c.lastNote}
              </p>
            </div>
          ) : null}
          {c.rejectionReason ? (
            <div className="min-w-[260px] flex-1 rounded-xl border border-destructive/20 bg-destructive-muted p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-destructive-muted-foreground">
                Powód odrzucenia
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-destructive-muted-foreground">
                {c.rejectionReason}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
