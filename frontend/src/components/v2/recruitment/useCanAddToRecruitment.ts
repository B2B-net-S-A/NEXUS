"use client";

import { useCapability } from "@/hooks/useCapability";
import type { Capability } from "@/lib/capabilities";

/**
 * Capability, która bramkuje „Dodaj do rekrutacji”.
 *
 * `POST /api/jobs/{id}/proposals/bulk` stoi za `RecruiterPlus` i bramką ZAPISU
 * sekcji Pipeline. `capabilities.ts` nie ma (jeszcze) osobnej capability dla
 * dodawania do pipeline'u; `hm_feedback.record` ma dokładnie tę definicję
 * (`RECRUITER_PLUS` + zapis Pipeline, zablokowana w podglądzie jako inna osoba).
 * Test `useCanAddToRecruitment.test.ts` pilnuje, że definicje się nie rozjadą.
 */
export const ADD_TO_RECRUITMENT_CAPABILITY: Capability = "hm_feedback.record";

export function useCanAddToRecruitment(): boolean {
  return useCapability(ADD_TO_RECRUITMENT_CAPABILITY);
}
