"use client";

import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  candidateProfileApi,
  type CandidateLocationPayload,
} from "@/lib/api";
import { MapPin, Save } from "lucide-react";

interface Props {
  candidateId: number;
  initial: {
    city?: string | null;
    country?: string | null;
    region?: string | null;
    hub_city?: string | null;
    latitude?: number | null;
    longitude?: number | null;
  };
}

const HUB_SUGGESTIONS = [
  "Warszawa",
  "Kraków",
  "Wrocław",
  "Trójmiasto",
  "Poznań",
  "Śląsk",
  "Łódź",
  "Lublin",
  "Rzeszów",
  "Remote",
];

export function CandidateLocationPanel({ candidateId, initial }: Props) {
  const qc = useQueryClient();
  const [form, setForm] = useState<CandidateLocationPayload>({
    city: initial.city ?? "",
    country: initial.country ?? "PL",
    region: initial.region ?? "",
    hub_city: initial.hub_city ?? "",
  });
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    setForm({
      city: initial.city ?? "",
      country: initial.country ?? "PL",
      region: initial.region ?? "",
      hub_city: initial.hub_city ?? "",
    });
  }, [initial]);

  const mut = useMutation({
    mutationFn: (payload: CandidateLocationPayload) =>
      candidateProfileApi.updateLocation(candidateId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidate", candidateId] });
      setSavedAt(new Date().toLocaleTimeString());
    },
  });

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-900">
      <div className="flex items-center gap-2 mb-3">
        <MapPin className="w-4 h-4 text-blue-500" />
        <h3 className="text-sm font-semibold">Lokalizacja</h3>
        {savedAt && (
          <span className="ml-auto text-xs text-green-600">
            Zapisano {savedAt}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs text-gray-500">Miasto</span>
          <input
            value={form.city ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))}
            className="mt-1 w-full border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1.5 text-sm bg-white dark:bg-gray-950"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">Kraj (ISO-2)</span>
          <input
            maxLength={2}
            value={form.country ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, country: e.target.value.toUpperCase() }))
            }
            className="mt-1 w-full border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1.5 text-sm bg-white dark:bg-gray-950 uppercase"
            placeholder="PL"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">Region / województwo</span>
          <input
            value={form.region ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, region: e.target.value }))
            }
            className="mt-1 w-full border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1.5 text-sm bg-white dark:bg-gray-950"
            placeholder="mazowieckie"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">Hub</span>
          <input
            value={form.hub_city ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, hub_city: e.target.value }))
            }
            list="hub-suggestions"
            className="mt-1 w-full border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1.5 text-sm bg-white dark:bg-gray-950"
            placeholder="Warszawa"
          />
          <datalist id="hub-suggestions">
            {HUB_SUGGESTIONS.map((h) => (
              <option key={h} value={h} />
            ))}
          </datalist>
        </label>
      </div>
      <div className="flex justify-end mt-3">
        <button
          type="button"
          onClick={() => {
            const payload: CandidateLocationPayload = {
              city: form.city?.trim() || null,
              country: form.country?.trim() || null,
              region: form.region?.trim() || null,
              hub_city: form.hub_city?.trim() || null,
            };
            mut.mutate(payload);
          }}
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
