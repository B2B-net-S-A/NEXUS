"use client";

import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { RecruitmentOption } from "@/lib/cv-generator";

export interface CalendarRecruitment {
  job_id: number;
  job_title: string;
  /** Członkostwo w zespole — tylko do takiej rekrutacji zapis wydarzenia przejdzie. */
  can_schedule?: boolean;
}

/**
 * Rekrutacje kandydata — to samo źródło co picker generatora CV
 * (`GET /api/cv-generator/candidates/{id}/recruitments`), jedna pozycja na
 * rekrutację. Świadomie bez `RecruitmentCombobox` z generatora: ten pokazuje
 * gotowość do wygenerowania CV (ostrzeżenie przy braku Championa/notatek),
 * która w kalendarzu czytałaby się jak problem z rozmową.
 */
export function useCandidateRecruitments(candidateId: number | null) {
  return useQuery<CalendarRecruitment[]>({
    queryKey: ["calendar-candidate-recruitments", candidateId],
    enabled: candidateId != null,
    staleTime: 60_000,
    queryFn: async () => {
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidateId}/recruitments`,
      );
      const seen = new Set<number>();
      const out: CalendarRecruitment[] = [];
      for (const row of res.data ?? []) {
        if (seen.has(row.job_id)) continue;
        seen.add(row.job_id);
        out.push({
          job_id: row.job_id,
          job_title: row.job_title,
          can_schedule: row.can_schedule,
        });
      }
      return out;
    },
  });
}

/**
 * Wybór rekrutacji do wydarzenia z kandydatem.
 *
 * Do 09.2026 żaden formularz kalendarza nie wysyłał `job_id`: feedback po
 * rozmowie zapisywał się bez rekrutacji, eskalacja T+2h do Delivery Leada nie
 * wychodziła, a zakładka „Rozmowy" nie miała jak powiązać wydarzenia. Przy
 * dokładnie jednej rekrutacji wybieramy ją sami — raz na kandydata, żeby
 * świadome „Bez rekrutacji" nie było nadpisywane przy każdym renderze.
 */
export function RecruitmentSelect({
  id,
  candidateId,
  value,
  onChange,
  autoSelectSingle = true,
  currentLabel,
}: {
  id: string;
  candidateId: number | null;
  value: number | null;
  onChange: (jobId: number | null) => void;
  autoSelectSingle?: boolean;
  /** Tytuł już przypiętej rekrutacji, gdy nie ma jej na liście kandydata. */
  currentLabel?: string | null;
}) {
  const query = useCandidateRecruitments(candidateId);
  const options = useMemo(() => query.data ?? [], [query.data]);
  const autoSelectedFor = useRef<number | null>(null);

  useEffect(() => {
    if (!autoSelectSingle || candidateId == null || !query.isSuccess) return;
    if (autoSelectedFor.current === candidateId) return;
    autoSelectedFor.current = candidateId;
    // Auto-wybór tylko rekrutacji, do której wołający może przypiąć rozmowę —
    // cudza rekrutacja podstawiona sama kończyła zapis 403 (przegląd 17.09).
    if (value == null && options.length === 1 && options[0].can_schedule !== false) {
      onChange(options[0].job_id);
    }
  }, [autoSelectSingle, candidateId, query.isSuccess, options, value, onChange]);

  if (candidateId == null) {
    return (
      <p id={id} className="text-xs text-muted-foreground">
        Wybierz kandydata, żeby przypiąć rozmowę do rekrutacji.
      </p>
    );
  }
  if (query.isError) {
    return (
      <p id={id} role="alert" className="text-xs text-destructive">
        Nie udało się wczytać rekrutacji kandydata — wydarzenie zapisze się bez
        rekrutacji.
      </p>
    );
  }
  const current = value != null && !options.some((o) => o.job_id === value);
  return (
    <select
      id={id}
      value={value ?? ""}
      disabled={query.isPending}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
    >
      <option value="">
        {query.isPending
          ? "Ładowanie rekrutacji…"
          : options.length === 0
            ? "Kandydat nie jest w żadnej rekrutacji"
            : "Bez rekrutacji"}
      </option>
      {current ? (
        <option value={value}>{currentLabel || `Rekrutacja #${value}`}</option>
      ) : null}
      {options.map((o) => (
        <option key={o.job_id} value={o.job_id} disabled={o.can_schedule === false}>
          {o.can_schedule === false
            ? `${o.job_title} — nie jesteś w zespole tej rekrutacji`
            : o.job_title}
        </option>
      ))}
    </select>
  );
}
