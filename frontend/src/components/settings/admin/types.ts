import type { UserPermissionsSave } from "@/lib/admin-permissions";

export interface AdminUser {
  id: number;
  email: string;
  name: string;
  role: string;
  /** Multi-role (migracja 0110). Lista wszystkich ról użytkownika. */
  roles?: string[];
  is_active: boolean;
  /** Imienne uprawnienie do usuwania klientów z profilu (0307). */
  can_delete_clients?: boolean;
  /** Uprawnienia nadane tej osobie, których nie dają jej role (plakietka „+N”). */
  extra_permissions?: string[];
  activity_count: number;
  last_activity: string | null;
  created_at: string;
}

export interface UserFormData {
  name: string;
  email: string;
  password: string;
  role: string;
  /** Multi-role (migracja 0110). Lista ról secondary + primary. */
  roles: string[];
  /** Imienne uprawnienie do usuwania klientów (tylko edycja istniejącego konta). */
  can_delete_clients: boolean;
  /** Odpina tożsamość Microsoft — następne logowanie SSO przypnie nowe konto. */
  clear_microsoft_identity: boolean;
  /**
   * Zmiana dodatkowych uprawnień osoby — osobne żądanie po zapisie konta
   * (tylko edycja; brak albo `null` = nie ma czego wysyłać).
   */
  permissions?: UserPermissionsSave | null;
}

// Pełna lista ról systemu (sync z backend/app/models/user.py:UserRole).
export const ROLES = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "trainee",
  "user",
];

/**
 * Role WYŁĄCZNE — nie łączą się z żadną inną (lustro CHECK-ów w bazie).
 * Praktykant (0374) widzi tylko „Telefony na dziś”; dodatkowa rola
 * otworzyłaby mu resztę aplikacji.
 */
export const EXCLUSIVE_ROLES: readonly string[] = ["finance", "user", "trainee"];

export function isExclusiveRole(role: string): boolean {
  return EXCLUSIVE_ROLES.includes(role);
}

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  finance: "Finanse",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  talent_community_manager: "Talent Community Manager",
  tac: "TAC",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  user: "Viewer (legacy)",
  trainee: "Praktykant",
  manager: "Manager",
  client: "Klient",
};

export function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pl-PL", {
    // DD.MM.RRRR, GG:MM — nie „13 wrz 2026" (UAT M11-B08).
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
