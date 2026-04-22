"use client";

import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  candidateProfileApi,
  type CandidateEngagementPayload,
} from "@/lib/api";
import { Award, Save } from "lucide-react";

interface Props {
  candidateId: number;
  initial: {
    is_ambassador?: boolean;
    wants_to_verify_candidates?: boolean;
    open_to_side_projects?: boolean;
    open_to_sales_support?: boolean;
    open_to_expert_consult?: boolean;
    engagement_notes?: string | null;
  };
}

const FLAG_LABELS: {
  key: keyof CandidateEngagementPayload;
  label: string;
  description: string;
}[] = [
  {
    key: "is_ambassador",
    label: "Ambasador firmy",
    description: "Promuje nas w swoim networku, poleca rekruterów/klientów.",
  },
  {
    key: "wants_to_verify_candidates",
    label: "Pomaga weryfikować kandydatów",
    description: "Chętnie przeprowadza screeningi techniczne.",
  },
  {
    key: "open_to_side_projects",
    label: "Otwarty na dodatkowe projekty",
    description: "Mógłby wziąć side-project poza głównym angażem.",
  },
  {
    key: "open_to_sales_support",
    label: "Wsparcie sprzedaży",
    description: "Może uczestniczyć w rozmowach przedsprzedażowych.",
  },
  {
    key: "open_to_expert_consult",
    label: "Konsultacje eksperckie",
    description: "Dostępny do godzinowych konsultacji eksperckich.",
  },
];

export function CandidateEngagementPanel({ candidateId, initial }: Props) {
  const qc = useQueryClient();
  const [flags, setFlags] = useState<CandidateEngagementPayload>({
    is_ambassador: !!initial.is_ambassador,
    wants_to_verify_candidates: !!initial.wants_to_verify_candidates,
    open_to_side_projects: !!initial.open_to_side_projects,
    open_to_sales_support: !!initial.open_to_sales_support,
    open_to_expert_consult: !!initial.open_to_expert_consult,
    engagement_notes: initial.engagement_notes ?? "",
  });
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    setFlags({
      is_ambassador: !!initial.is_ambassador,
      wants_to_verify_candidates: !!initial.wants_to_verify_candidates,
      open_to_side_projects: !!initial.open_to_side_projects,
      open_to_sales_support: !!initial.open_to_sales_support,
      open_to_expert_consult: !!initial.open_to_expert_consult,
      engagement_notes: initial.engagement_notes ?? "",
    });
  }, [initial]);

  const mut = useMutation({
    mutationFn: (payload: CandidateEngagementPayload) =>
      candidateProfileApi.updateEngagement(candidateId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidate", candidateId] });
      setSavedAt(new Date().toLocaleTimeString());
    },
  });

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-900">
      <div className="flex items-center gap-2 mb-3">
        <Award className="w-4 h-4 text-amber-500" />
        <h3 className="text-sm font-semibold">Zaangażowanie</h3>
        {savedAt && (
          <span className="ml-auto text-xs text-green-600">
            Zapisano {savedAt}
          </span>
        )}
      </div>
      <div className="space-y-2">
        {FLAG_LABELS.map((f) => (
          <label
            key={f.key}
            className="flex items-start gap-3 cursor-pointer group"
          >
            <input
              type="checkbox"
              checked={Boolean(flags[f.key])}
              onChange={(e) =>
                setFlags((prev) => ({
                  ...prev,
                  [f.key]: e.target.checked,
                }))
              }
              className="mt-0.5"
            />
            <div className="flex-1">
              <div className="text-sm font-medium text-gray-900 dark:text-gray-100 group-hover:underline">
                {f.label}
              </div>
              <div className="text-xs text-gray-500">{f.description}</div>
            </div>
          </label>
        ))}
      </div>
      <label className="block mt-3">
        <span className="text-xs text-gray-500">Notatka do zaangażowania</span>
        <textarea
          value={flags.engagement_notes ?? ""}
          onChange={(e) =>
            setFlags((prev) => ({ ...prev, engagement_notes: e.target.value }))
          }
          className="mt-1 w-full border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1.5 text-sm bg-white dark:bg-gray-950"
          rows={2}
          placeholder="Jaką rolę chciałby pełnić? Jakie projekty by go interesowały?"
        />
      </label>
      <div className="flex justify-end mt-3">
        <button
          type="button"
          onClick={() => mut.mutate(flags)}
          disabled={mut.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-3 py-1.5"
        >
          <Save className="w-3.5 h-3.5" />
          {mut.isPending ? "Zapisywanie…" : "Zapisz"}
        </button>
      </div>
    </div>
  );
}
