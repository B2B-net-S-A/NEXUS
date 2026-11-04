/**
 * Ostrzeżenie `POST /api/clients` o kliencie o tej samej nazwie (22.10.2026).
 *
 * Serwer odpowiada 409 `client_duplicate_warning` z listą widocznych klientów
 * (ta sama firma bez względu na wielkość liter i formę prawną) i zakładkami,
 * w których są. Okno „Dodaj firmę” pokazuje je i zapisuje dopiero po
 * „Dodaj mimo to” (`acknowledge_duplicate=true`).
 */
import type { ClientDirectoryCategory } from "@/lib/api";

export interface SameNameClient {
  id: number;
  name: string;
  categories: ClientDirectoryCategory[];
}

export const CLIENT_TAB_LABEL: Record<ClientDirectoryCategory, string> = {
  active: "Aktywni",
  relationship: "Relacyjni",
  inactive: "Nieaktywni",
};

export function clientDuplicateWarningFrom(error: unknown): SameNameClient[] | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data
    ?.detail;
  if (!detail || typeof detail !== "object") return null;
  const { code, clients } = detail as { code?: unknown; clients?: unknown };
  if (code !== "client_duplicate_warning" || !Array.isArray(clients)) return null;
  return clients
    .filter(
      (item): item is SameNameClient =>
        !!item && typeof item.id === "number" && typeof item.name === "string",
    )
    .map((item) => ({
      id: item.id,
      name: item.name,
      categories: (Array.isArray(item.categories) ? item.categories : []).filter(
        (c: unknown): c is ClientDirectoryCategory =>
          typeof c === "string" && c in CLIENT_TAB_LABEL,
      ),
    }));
}
