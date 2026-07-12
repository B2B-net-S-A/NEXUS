"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, Loader2, Percent, Users } from "lucide-react";
import { cortexApi, type CortexTechMap } from "@/lib/api";
import { StatCard, StatCardGrid } from "@/components/ds/StatCard";
import { EmptyState } from "@/components/ds/EmptyState";
import { TechMapHeatmap } from "@/components/cortex/TechMapHeatmap";

const SOURCE_OPTIONS = [
  { value: "", label: "Wszystkie źródła" },
  { value: "traffit", label: "Traffit (technologie)" },
  { value: "cv_llm", label: "CV (ekstrakcja AI)" },
  { value: "screening", label: "Screening" },
];

export function TechMapPanel() {
  const [source, setSource] = useState("");
  const [atClientOnly, setAtClientOnly] = useState(false);
  const [minCount, setMinCount] = useState(2);

  const { data, isLoading } = useQuery<CortexTechMap>({
    queryKey: ["cortex-tech-map", source, atClientOnly, minCount],
    queryFn: async () =>
      (
        await cortexApi.techMap({
          source: source || undefined,
          employment: atClientOnly ? "at_client" : undefined,
          min_count: minCount,
        })
      ).data,
  });

  if (isLoading || !data) {
    return (
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
        Ładowanie mapy technologicznej…
      </div>
    );
  }

  const totalFacts = Object.values(data.sources).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      <StatCardGrid>
        <StatCard
          label="Kandydaci z faktami"
          value={data.candidates_covered.toLocaleString("pl-PL")}
          sub={`z ${data.candidates_total.toLocaleString("pl-PL")} rekordów w bazie`}
          icon={Users}
        />
        <StatCard
          label="Pokrycie bazy"
          value={`${data.fill_rate_pct}%`}
          sub="rekordy, nie osoby — duplikaty niescalone"
          icon={Percent}
        />
        <StatCard
          label="Kandydaci wg źródła"
          value={totalFacts.toLocaleString("pl-PL")}
          sub={Object.entries(data.sources)
            .map(([src, cnt]) => `${src}: ${cnt.toLocaleString("pl-PL")}`)
            .join(" · ")}
          icon={Database}
        />
      </StatCardGrid>

      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <h3 className="font-semibold text-sm">
            Skill × Seniority (derived)
          </h3>
          <div className="flex flex-wrap items-center gap-3 text-xs ml-auto">
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="border border-border rounded-md bg-background px-2 py-1.5"
            >
              {SOURCE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <label className="inline-flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={atClientOnly}
                onChange={(e) => setAtClientOnly(e.target.checked)}
                className="rounded border-border"
              />
              Tylko u klientów
            </label>
            <label className="inline-flex items-center gap-1.5">
              Min. kandydatów
              <select
                value={minCount}
                onChange={(e) => setMinCount(Number(e.target.value))}
                className="border border-border rounded-md bg-background px-2 py-1.5"
              >
                {[1, 2, 3, 5, 10].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {data.cells.length === 0 ? (
          <EmptyState
            icon={Database}
            title="Brak faktów kompetencyjnych"
            description={
              data.candidates_covered === 0
                ? "Fact store jest pusty — admin może uruchomić backfill z Traffita w zakładce „Jakość danych”."
                : "Żadna komórka nie przekracza progu min. kandydatów — obniż próg lub zmień filtry."
            }
          />
        ) : (
          <TechMapHeatmap data={data} />
        )}

        <p className="text-xs text-muted-foreground">
          Seniority wyprowadzane: lata IT (≥7 senior, ≥3 mid) → bucket Traffita
          → nieznane. Ta mapa stoi na {data.fill_rate_pct}% bazy — traktuj
          braki jako „nie wiemy”, nie „nie zna”.
        </p>
      </div>
    </div>
  );
}
