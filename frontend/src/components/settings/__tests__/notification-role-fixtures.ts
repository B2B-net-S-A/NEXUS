import type {
  NotificationRoleGroup,
  NotificationRolesView,
} from "@/lib/notification-role-matrix";

const ROLE_KEYS = ["admin", "recruiter"] as const;

function group(
  key: string,
  label: string,
  received: [number, number],
  mutedFor: string[] = [],
): NotificationRoleGroup {
  return {
    key,
    label,
    muted: Object.fromEntries(ROLE_KEYS.map((role) => [role, mutedFor.includes(role)])),
    muted_at: Object.fromEntries(
      ROLE_KEYS.map((role) => [role, mutedFor.includes(role) ? "2026-10-01T08:00:00+00:00" : null]),
    ),
    received_30d: { admin: received[0], recruiter: received[1] },
  };
}

/**
 * Dwie role (Admin: 2 konta, Rekruter: 4), kategoria obowiązkowa, kategoria
 * z jedną grupą i kategoria podzielona na dwie grupy.
 * Średnie na osobę: Admin (4 + 10 + 20 + 6) / 2 = 20, Rekruter (8 + 40) / 4 = 12.
 */
export function roleView(
  overrides: Partial<NotificationRolesView> = {},
  mutedFor: Record<string, string[]> = {},
): NotificationRolesView {
  return {
    revision: 7,
    updated_at: "2026-10-06T09:15:00+00:00",
    updated_by_name: "Aniela Administrująca",
    window_days: 30,
    roles: [
      { key: "admin", label: "Admin", accounts: 2 },
      { key: "recruiter", label: "Rekruter", accounts: 4 },
    ],
    categories: [
      {
        key: "mentions",
        label: "Wzmianki (@)",
        description: "Ktoś oznaczył Cię w notatce.",
        mandatory: true,
        groups: [group("mentions", "Wzmianki (@)", [4, 8])],
      },
      {
        key: "pipeline",
        label: "Ruchy w rekrutacjach",
        description: "Kandydat zmienił etap.",
        mandatory: false,
        groups: [group("pipeline", "Ruchy w rekrutacjach", [10, 40], mutedFor.pipeline)],
      },
      {
        key: "contracts",
        label: "Kontrakty i zamówienia",
        description: "Koniec zamówienia i umowy.",
        mandatory: false,
        groups: [
          group("order_ending", "Koniec zamówienia", [20, 0], mutedFor.order_ending),
          group("contract_ending", "Koniec umowy", [6, 0], mutedFor.contract_ending),
        ],
      },
    ],
    ...overrides,
  };
}
