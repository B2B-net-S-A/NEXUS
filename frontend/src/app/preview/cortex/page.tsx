"use client";

/**
 * Preview harness dla sekcji Cortex — mocki bez API/logowania.
 * Middleware przepuszcza /preview/*, AppShellV2 renderuje bare (bez shella).
 */

import type { CortexCoverage, CortexTechMap } from "@/lib/api";
import { CoverageView } from "@/components/cortex/CoverageView";
import { TechMapHeatmap } from "@/components/cortex/TechMapHeatmap";

const MOCK_TECH_MAP: CortexTechMap = {
  skills: ["java", "python", "react", "aws", "kubernetes", "sql"],
  seniorities: ["junior", "mid", "senior", "unknown"],
  cells: [
    { skill: "java", seniority: "junior", count: 120 },
    { skill: "java", seniority: "mid", count: 340 },
    { skill: "java", seniority: "senior", count: 210 },
    { skill: "java", seniority: "unknown", count: 900 },
    { skill: "python", seniority: "mid", count: 260 },
    { skill: "python", seniority: "senior", count: 150 },
    { skill: "python", seniority: "unknown", count: 700 },
    { skill: "react", seniority: "junior", count: 80 },
    { skill: "react", seniority: "mid", count: 190 },
    { skill: "react", seniority: "unknown", count: 420 },
    { skill: "aws", seniority: "senior", count: 95 },
    { skill: "aws", seniority: "unknown", count: 310 },
    { skill: "kubernetes", seniority: "senior", count: 60 },
    { skill: "sql", seniority: "unknown", count: 640 },
  ],
  candidates_covered: 29350,
  candidates_total: 53430,
  fill_rate_pct: 54.9,
  sources: { traffit: 29350 },
  skill_totals: {
    java: 1570,
    python: 1110,
    react: 690,
    aws: 405,
    kubernetes: 60,
    sql: 640,
  },
  employment: null,
  data_as_of: "2026-07-12T10:00:00Z",
  min_count: 2,
};

const MOCK_COVERAGE: CortexCoverage = {
  candidates: {
    total: 53430,
    with_cv_file: 49903,
    with_cv_file_pct: 93.4,
    with_raw_cv_text: 28104,
    with_raw_cv_text_pct: 52.6,
    with_traffit_tech: 29386,
    with_traffit_tech_pct: 55.0,
    with_any_fact: 29350,
    with_any_fact_pct: 54.9,
    availability_known: 0,
    availability_known_pct: 0,
  },
  facts: {
    by_source: { traffit: { facts: 264150, candidates: 29350 } },
    freshness: { lt_1y: 0, y1_3: 0, gt_3y: 0, unknown: 264150 },
  },
  processes: {
    jobs_closed: 3747,
    jobs_closed_with_reason: 0,
    jobs_close_reason_pct: 0,
    contracts_ended: 48,
    contracts_ended_with_reason: 0,
    contracts_natural_expiry: 41,
  },
  unmatched_terms: [
    {
      term: "sap ewm-mfs",
      occurrences: 214,
      status: "new",
      last_seen_at: "2026-07-12T10:00:00Z",
    },
    {
      term: "murex",
      occurrences: 96,
      status: "new",
      last_seen_at: "2026-07-12T10:00:00Z",
    },
  ],
  data_as_of: "2026-07-12T10:00:00Z",
};

export default function CortexPreviewPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-10 bg-background min-h-screen">
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Cortex — Mapa technologiczna (mock)</h2>
        <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6">
          <TechMapHeatmap data={MOCK_TECH_MAP} />
        </div>
      </section>
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Cortex — Jakość danych (mock)</h2>
        <CoverageView data={MOCK_COVERAGE} />
      </section>
    </div>
  );
}
