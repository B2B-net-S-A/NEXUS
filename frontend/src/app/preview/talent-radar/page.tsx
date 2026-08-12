"use client";

/**
 * Harness designu dla Talent Radara — WYŁĄCZNIE zahardkodowane mocki.
 *
 * Renderuje ten sam `TalentRadarResults`, którego używa ekran produkcyjny, więc
 * to, co tu widać, jest tym, co zobaczy rekruter. Nie woła żadnego API i nie
 * dotyka `TalentRadarWorkspace` (tamten trzyma stan i mutację) — dzięki temu
 * spełnia warunek z `PUBLIC_PATHS` w middleware.ts.
 *
 * Trzy stany obok siebie, bo różnicę między nimi łatwo zepsuć niezauważenie:
 * degradacja retrievalu MUSI wyglądać jak awaria, a nie jak brak dopasowań.
 */

import { TalentRadarResults } from "@/components/talent-radar/TalentRadarResults";
import type {
  TalentRadarMeta,
  TalentRadarResult,
} from "@/lib/talent-radar-api";

const LAYER = { points: 10, max: 15, reason: "mock" };

function mockResult(
  id: number,
  name: string,
  lastname: string,
  total: number,
  extra: Partial<TalentRadarResult> = {},
): TalentRadarResult {
  return {
    candidate_id: id,
    total,
    semantic: LAYER,
    skills: LAYER,
    salary: { points: null, max: null, reason: null, status: "not_applicable" },
    location: LAYER,
    availability: LAYER,
    champion_fit: LAYER,
    matching_must: ["Python", "FastAPI"],
    gap_must: [],
    matching_nice: ["Kubernetes"],
    gap_nice: [],
    penalties: [],
    fit_confidence: 0.8,
    candidate: {
      id,
      name,
      lastname,
      location: "Kraków, PL",
      competence_category: "software_development",
      years_it_experience: 8,
      availability_status: null,
      champion: false,
      avatar_url: null,
    },
    ...extra,
  };
}

const RESULTS: TalentRadarResult[] = [
  mockResult(101, "Anna", "Kowalska", 87.4),
  mockResult(102, "Bartosz", "Nowak", 71.2, {
    gap_must: ["AWS"],
    matching_nice: ["Terraform", "Docker"],
  }),
  mockResult(103, "Celina", "Wiśniewska", 54.9, {
    matching_must: ["Python"],
    gap_must: ["FastAPI", "PostgreSQL"],
  }),
];

const META: TalentRadarMeta = {
  pool_size: 1000,
  eligible_size: 842,
  returned: 3,
  degraded: false,
  reason: null,
};

const DEGRADED: TalentRadarMeta = {
  pool_size: 0,
  eligible_size: 0,
  returned: 0,
  degraded: true,
  reason: "semantic_unavailable",
};

const NOBODY: TalentRadarMeta = {
  pool_size: 1000,
  eligible_size: 0,
  returned: 0,
  degraded: false,
  reason: null,
};

function Case({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </h2>
      {children}
    </section>
  );
}

export default function TalentRadarPreviewPage() {
  return (
    <div className="flex flex-col gap-10 p-6">
      <h1 className="text-2xl font-semibold">Talent Radar — stany wyników</h1>

      <Case label="Wyniki">
        <TalentRadarResults meta={META} results={RESULTS} pending={false} />
      </Case>

      <Case label="Degradacja retrievalu (NIE pusty stan)">
        <TalentRadarResults meta={DEGRADED} results={[]} pending={false} />
      </Case>

      <Case label="Nikt nie przeszedł filtra dopuszczalności">
        <TalentRadarResults meta={NOBODY} results={[]} pending={false} />
      </Case>

      <Case label="Przed pierwszym wyszukaniem">
        <TalentRadarResults meta={null} results={[]} pending={false} />
      </Case>
    </div>
  );
}
