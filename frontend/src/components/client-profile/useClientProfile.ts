"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { ClientProfileResponse } from "@/types/client-profile";

/**
 * Profil klienta (`GET /api/clients/{id}/profile`) — jedno zapytanie pod jednym
 * kluczem. Czyta je zakładka „Profil” (konsultanci) i nagłówek strony klienta
 * (liczby widoczne na każdej zakładce), więc react-query robi jedno żądanie.
 */
export function useClientProfile(clientId: number) {
  return useQuery<ClientProfileResponse>({
    queryKey: ["client-profile", clientId],
    queryFn: () =>
      api.get(`/api/clients/${clientId}/profile`).then((r) => r.data),
  });
}
