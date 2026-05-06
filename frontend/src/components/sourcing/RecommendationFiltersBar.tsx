"use client";

import { useState } from "react";
import { Filter, X } from "lucide-react";
import type { SeekingContractorsParams } from "@/lib/api";

interface Props {
  initial?: SeekingContractorsParams;
  onApply: (filters: SeekingContractorsParams) => void;
}

const COMPETENCE_CATEGORIES = [
  "Backend",
  "Frontend",
  "DevOps",
  "QA",
  "Mobile",
  "Data",
  "AI/ML",
  "Security",
  "Management",
];

export function RecommendationFiltersBar({ initial, onApply }: Props) {
  const [horizonDays, setHorizonDays] = useState(initial?.horizon_days ?? 30);
  const [location, setLocation] = useState(initial?.location ?? "");
  const [salaryMin, setSalaryMin] = useState<string>(
    initial?.salary_min !== undefined && initial.salary_min !== null
      ? String(initial.salary_min)
      : "",
  );
  const [salaryMax, setSalaryMax] = useState<string>(
    initial?.salary_max !== undefined && initial.salary_max !== null
      ? String(initial.salary_max)
      : "",
  );
  const [competenceCategories, setCompetenceCategories] = useState<string[]>(
    initial?.competence_category ?? [],
  );
  const [industryBlocklist, setIndustryBlocklist] = useState(
    initial?.industry_blocklist ?? true,
  );

  const toggleCategory = (cat: string) => {
    setCompetenceCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat],
    );
  };

  const handleApply = () => {
    onApply({
      horizon_days: horizonDays,
      location: location.trim() || undefined,
      salary_min: salaryMin ? Number(salaryMin) : undefined,
      salary_max: salaryMax ? Number(salaryMax) : undefined,
      competence_category:
        competenceCategories.length > 0 ? competenceCategories : undefined,
      industry_blocklist: industryBlocklist,
    });
  };

  const handleReset = () => {
    setHorizonDays(30);
    setLocation("");
    setSalaryMin("");
    setSalaryMax("");
    setCompetenceCategories([]);
    setIndustryBlocklist(true);
    onApply({ horizon_days: 30, industry_blocklist: true });
  };

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Filter className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-semibold text-sm text-foreground dark:text-foreground">
          Filtry
        </h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <label className="flex flex-col">
          <span className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">
            Kontrakt kończy się w ciągu (dni)
          </span>
          <input
            type="number"
            min={1}
            max={180}
            value={horizonDays}
            onChange={(e) => setHorizonDays(Number(e.target.value) || 30)}
            className="border rounded px-2 py-1 text-sm"
          />
        </label>

        <label className="flex flex-col">
          <span className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">
            Lokalizacja
          </span>
          <input
            type="text"
            placeholder="np. Warszawa"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
        </label>

        <div className="flex flex-col md:col-span-1">
          <span className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">
            Kategorie kompetencji{" "}
            <span className="text-muted-foreground">(wiele · OR)</span>
          </span>
          <div className="flex flex-wrap gap-1.5">
            {COMPETENCE_CATEGORIES.map((cc) => {
              const active = competenceCategories.includes(cc);
              return (
                <button
                  key={cc}
                  type="button"
                  onClick={() => toggleCategory(cc)}
                  className={`text-xs px-2 py-1 rounded-full border transition-colors ${
                    active
                      ? "bg-purple-600 text-white border-purple-600"
                      : "bg-card dark:bg-muted text-foreground dark:text-muted-foreground border-border hover:border-purple-400"
                  }`}
                  data-testid={`cc-chip-${cc}`}
                  aria-pressed={active}
                >
                  {cc}
                </button>
              );
            })}
          </div>
        </div>

        <label className="flex flex-col">
          <span className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">
            Stawka min (PLN/mies)
          </span>
          <input
            type="number"
            min={0}
            step={1000}
            placeholder="np. 15000"
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
        </label>

        <label className="flex flex-col">
          <span className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">
            Stawka max (PLN/mies)
          </span>
          <input
            type="number"
            min={0}
            step={1000}
            placeholder="np. 25000"
            value={salaryMax}
            onChange={(e) => setSalaryMax(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
        </label>

        <label className="flex items-center gap-2 mt-5">
          <input
            type="checkbox"
            checked={industryBlocklist}
            onChange={(e) => setIndustryBlocklist(e.target.checked)}
          />
          <span className="text-sm text-foreground dark:text-muted-foreground">
            Respektuj NDA / blacklist klientów
          </span>
        </label>
      </div>

      <div className="flex gap-2 mt-3">
        <button
          onClick={handleApply}
          className="bg-primary hover:bg-primary/90 text-white text-sm font-medium px-4 py-1.5 rounded-md"
        >
          Zastosuj
        </button>
        <button
          onClick={handleReset}
          className="text-muted-foreground hover:text-foreground text-sm font-medium px-3 py-1.5 rounded-md flex items-center gap-1"
        >
          <X className="w-3.5 h-3.5" /> Wyczyść
        </button>
      </div>
    </div>
  );
}
