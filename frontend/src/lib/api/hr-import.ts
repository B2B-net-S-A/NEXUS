// Import z Compassa z ekranu Ustawienia → „Import z Compassa” (17.10.2026).
//
// Lustro `backend/app/api/hr_import.py` (`/api/hr/admin/import`): paczka →
// sprawdzenie na sucho (liczby per moduł) → zapis wybranych modułów (tylko
// admin) → historia. Raport niesie liczby i identyfikatory Compassa; e-mail
// przy pozycji do wyjaśnienia przychodzi wyłącznie administratorowi.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { hrKeys } from "@/lib/api/hr";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

const BASE = "/api/hr/admin/import";

export type HrImportModule =
  | "profiles"
  | "leave"
  | "time"
  | "payroll"
  | "lifecycle"
  | "cases"
  | "care";

export type HrImportAction = "create" | "update" | "unchanged" | "conflict" | "skip";

export type HrImportStatus = "dry_run" | "applied" | "expired" | "superseded";

export interface HrImportAttention {
  source_id: string;
  action: "skip" | "conflict";
  reason: string;
  /** Tylko w odpowiedzi dla administratora. */
  email?: string | null;
}

export interface HrImportModuleReport {
  module: HrImportModule;
  label: string;
  total: number;
  counts: Record<HrImportAction, number>;
  reasons: Record<string, number>;
  extra: Record<string, unknown>;
  attention_total: number;
  /** Próbny zapis modułu przerwał błąd — moduł nie nadaje się do zapisu. */
  error: string | null;
  applied: {
    total: number;
    counts: Record<HrImportAction, number>;
    written: Record<string, number>;
  } | null;
  /** Tylko w odpowiedzi na sucho (do 200 pozycji na moduł). */
  attention?: HrImportAttention[];
}

/** Paczka wgrana w Ustawieniach albo partia z `scripts/hr_compass_import.py`. */
export type HrImportSource = "screen" | "script";

export interface HrImportUpload {
  /** Id paczki z ekranu albo id partii skryptu — unikalne dopiero z `source`. */
  id: number;
  source: HrImportSource;
  status: HrImportStatus;
  bundle_sha256: string;
  /** Partia ze skryptu nie zostawia paczki w bazie, więc rozmiaru nie ma. */
  size_bytes: number | null;
  exported_at: string | null;
  created_at: string | null;
  created_by_name: string | null;
  expires_at: string | null;
  applied_at: string | null;
  applied_by_name: string | null;
  applied_modules: HrImportModule[];
  modules: HrImportModuleReport[];
}

export const HR_IMPORT_STATUS_LABELS: Record<HrImportStatus, string> = {
  dry_run: "Sprawdzona, czeka na zapis",
  applied: "Zapisana",
  expired: "Wygasła",
  superseded: "Nieaktualna",
};

export const HR_IMPORT_SOURCE_LABELS: Record<HrImportSource, string> = {
  screen: "z ekranu",
  script: "ze skryptu",
};

export const HR_IMPORT_ACTION_LABELS: Record<HrImportAction, string> = {
  create: "Nowe",
  update: "Zmienione",
  unchanged: "Bez zmian",
  conflict: "Konflikty",
  skip: "Do wyjaśnienia",
};

export const hrImportKeys = {
  batches: ["hr", "import", "batches"] as const,
};

export function useHrImportBatches(enabled = true) {
  return useQuery({
    queryKey: hrImportKeys.batches,
    queryFn: async () => (await api.get<HrImportUpload[]>(`${BASE}/batches`)).data,
    enabled,
  });
}

function useInvalidateBatches() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: hrImportKeys.batches });
}

// Sprawdzenie i zapis liczą cały łańcuch modułów, a osoba czeka przy ekranie
// na raport — sufit jak dla wolnych wywołań, nie 30 s CRUD-ów.
export function useHrImportDryRun() {
  const invalidate = useInvalidateBatches();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return (
        await api.post<HrImportUpload>(`${BASE}/dry-run`, body, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: SLOW_ENDPOINT_TIMEOUT_MS,
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useHrImportApply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      bundle_sha256,
      modules,
    }: {
      id: number;
      bundle_sha256: string;
      modules: HrImportModule[];
    }) =>
      (
        await api.post<HrImportUpload>(
          `${BASE}/${id}/apply`,
          { bundle_sha256, modules },
          { timeout: SLOW_ENDPOINT_TIMEOUT_MS },
        )
      ).data,
    // Zapis zmienia kartoteki, urlopy, godziny, Płace i resztę ekranów „Ludzi”
    // (razem z listą paczek — wszystko pod korzeniem `["hr"]`).
    onSuccess: () => queryClient.invalidateQueries({ queryKey: hrKeys.all }),
  });
}
