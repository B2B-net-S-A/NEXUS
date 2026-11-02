// Ustawienia → „Jakość generatora CV”: odczyt powodów z pobrań oryginału po złym
// wyniku generatora. Trasa: `backend/app/api/cv_generator_feedback.py`.

import { useQuery } from "@tanstack/react-query";

import apiClient from "@/lib/api";

export interface GeneratorFeedbackEntry {
  id: number;
  created_at: string;
  author_name: string | null;
  candidate_id: number;
  candidate_name: string;
  job_id: number | null;
  job_title: string | null;
  client_name: string | null;
  generation_status: string;
  reasons: string[];
  detail: string | null;
}

export interface GeneratorFeedbackSummary {
  days: number;
  total: number;
  people: number;
  generations_ready: number;
  reasons: { code: string; count: number }[];
  clients: { client_id: number | null; client_name: string | null; count: number }[];
  entries: GeneratorFeedbackEntry[];
}

export function useGeneratorFeedbackSummary(days: number) {
  return useQuery({
    queryKey: ["cv-generator-feedback", days],
    queryFn: async () => {
      const { data } = await apiClient.get<GeneratorFeedbackSummary>(
        "/api/cv-generator/feedback/summary",
        { params: { days } },
      );
      return data;
    },
  });
}
