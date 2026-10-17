// Kafelek pulpitu „W zastępstwie” (17.10.2026).
//
// Lustro `backend/app/api/hr_dashboard.py` i `services/hr/substitution_summary.py`.
// Kto kogo zastępuje, liczy silnik zastępstw; tu nie ma rodzaju nieobecności (D6).

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface SubstitutionPreviewJob {
  job_id: number;
  title: string;
  client_name: string | null;
}

export interface SubstitutionPreviewMeeting {
  event_id: number;
  /** Chwila z serwera (UTC). */
  starts_at: string;
  client_name: string | null;
}

export interface SubstitutionItem {
  owner_user_id: number;
  owner_name: string | null;
  start_date: string;
  end_date: string;
  recruitments: { count: number; items: SubstitutionPreviewJob[] };
  client_meetings: { count: number; items: SubstitutionPreviewMeeting[] };
  pipeline_cards: number;
}

export interface SubstitutionWarning {
  owner_user_id: number;
  owner_name: string | null;
  substitute_user_id: number;
  substitute_name: string | null;
  /** Ostrzeżenie dla samego zastępcy (a nie dla przełożonego nieobecnego). */
  you_are_substitute: boolean;
}

export interface SubstitutionSummary {
  /** Działa jakiekolwiek źródło urlopów (Compass albo NEXUS). */
  enabled: boolean;
  fresh: boolean;
  items: SubstitutionItem[];
  warnings: SubstitutionWarning[];
}

export const SUBSTITUTION_QUERY_KEY = ["hr", "dashboard", "substitution"] as const;

export function useMySubstitution(enabled = true) {
  return useQuery({
    queryKey: SUBSTITUTION_QUERY_KEY,
    queryFn: async () =>
      (await api.get<SubstitutionSummary>("/api/hr/dashboard/substitution")).data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}
