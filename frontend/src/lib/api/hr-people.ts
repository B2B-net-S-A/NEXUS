// Zapisy Kadr w katalogu „Ludzie” wykonywane hurtem (18.10.2026).
//
// Lustro `POST /api/hr/admin/profiles/timesheet-required`
// (`backend/app/api/hr_admin.py`): flaga „Składa raport godzin” dla wielu
// kartotek naraz — ślad w audycie per osoba liczy serwer.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { hrKeys } from "./hr";

export interface BulkProfileResult {
  changed: number[];
  unchanged: number[];
}

export function useSetTimesheetRequired() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { user_ids: number[]; required: boolean }) =>
      (
        await api.post<BulkProfileResult>(
          "/api/hr/admin/profiles/timesheet-required",
          payload,
        )
      ).data,
    // Flaga zmienia katalog, kartotekę, kolejkę akceptacji i raport płac.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: hrKeys.all }),
  });
}
