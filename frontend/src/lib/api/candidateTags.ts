// Tagi kandydata — dodanie / usunięcie JEDNEGO tagu i podpowiedzi.
//
// Lustro `backend/app/api/candidate_tags.py`. Serwer zmienia jeden wpis pod
// blokadą wiersza i zostawia obiekty importu Traffita nietknięte, więc front
// nigdy nie wysyła całej listy (PATCH kandydata ZASTĘPUJE listę — edycja
// z nieaktualnego widoku kasowałaby tag dodany w międzyczasie).

import { api } from "@/lib/api";

export const TAG_MAX_LEN = 64;

export interface CandidateTagsResponse {
  tags: unknown[];
  changed: boolean;
}

/** Kształt jak `/companies/suggest` — ten sam `CompanyAutocomplete` w filtrze listy. */
export interface TagSuggestion {
  name: string;
  count: number;
}

export const TAG_SUGGEST_ENDPOINT = "/api/candidates/tags/suggest";

export const candidateTagKeys = {
  suggest: (q: string) => ["candidate-tags", "suggest", q.trim().toLowerCase()] as const,
};

export async function addCandidateTag(candidateId: number, tag: string): Promise<CandidateTagsResponse> {
  const { data } = await api.post<CandidateTagsResponse>(`/api/candidates/${candidateId}/tags`, { tag });
  return data;
}

export async function removeCandidateTag(candidateId: number, tag: string): Promise<CandidateTagsResponse> {
  const { data } = await api.delete<CandidateTagsResponse>(`/api/candidates/${candidateId}/tags`, {
    params: { tag },
  });
  return data;
}

export async function suggestCandidateTags(q: string, limit = 10): Promise<TagSuggestion[]> {
  const { data } = await api.get<TagSuggestion[]>(TAG_SUGGEST_ENDPOINT, {
    params: { q: q.trim(), limit },
  });
  return data;
}

/**
 * Normalizacja wpisanego tagu — lustro walidatora backendu. Zwraca `null`
 * z komunikatem, gdy tag nie przejdzie, żeby nie wysyłać żądania na pewne 422.
 */
export function normalizeTagInput(raw: string): { tag: string | null; error: string | null } {
  const tag = raw.split(/\s+/).filter(Boolean).join(" ");
  if (!tag) return { tag: null, error: null };
  if (tag.includes(",")) return { tag: null, error: "Tag nie może zawierać przecinka — dodaj tagi osobno." };
  if (tag.length > TAG_MAX_LEN) return { tag: null, error: `Tag może mieć najwyżej ${TAG_MAX_LEN} znaków.` };
  return { tag, error: null };
}

/** Czy kandydat ma już ten tag (bez wielkości liter, jak backend). */
export function hasStringTag(tags: unknown, tag: string): boolean {
  if (!Array.isArray(tags)) return false;
  const folded = tag.toLocaleLowerCase("pl");
  return tags.some((t) => typeof t === "string" && t.trim().toLocaleLowerCase("pl") === folded);
}
