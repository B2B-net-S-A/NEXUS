"use client";

import * as React from "react";

import { CandidatesSplitView } from "@/components/v2/candidates/CandidatesSplitView";
import type { CandidateDetailData } from "@/components/v2/candidates/CandidateDetailPanel";
import { CANDIDATE_HYBRID_FIXTURES } from "./hybrid-fixtures";

/** Maps the shared design fixtures into the production CandidatesSplitView's
 *  row shape, so the real component is exercised (not a bespoke copy) in the
 *  auth-free harness. */
const ROWS: CandidateDetailData[] = CANDIDATE_HYBRID_FIXTURES.map((c, i) => ({
  id: i + 1,
  name: c.name,
  initials: c.initials,
  role: c.role,
  location: c.location,
  phone: c.phone,
  email: c.email,
  stage: c.stage,
  stageDate: c.stageDate,
  rateLabel: c.rate,
  owner: c.owner,
  recruitments: c.recruitments,
  headline: c.headline,
  skills: c.skills,
  lastNote: c.lastNote,
  rejectionReason: c.rejectionReason,
  detailPairs: [
    { label: "Stawka", value: c.rate },
    { label: "Dostępność", value: c.availability },
    { label: "Tryb pracy", value: c.workMode },
    { label: "Angielski", value: c.english },
    { label: "Narodowość", value: c.nationality },
    { label: "Dodano", value: c.added },
  ],
}));

export function CandidateSplitPreview() {
  const [selectedIds, setSelectedIds] = React.useState<Set<number>>(new Set());

  return (
    <CandidatesSplitView
      rows={ROWS}
      isLoading={false}
      isError={false}
      selectedIds={selectedIds}
      onToggleSelect={(id) =>
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        })
      }
      onOpenFullProfile={() => undefined}
      page={1}
      totalPages={15}
      onPrevPage={() => undefined}
      onNextPage={() => undefined}
    />
  );
}
