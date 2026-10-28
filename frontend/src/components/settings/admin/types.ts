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
  /** 0609: konto po pierwszym logowaniu czeka na decyzję, kim jest
   *  (filtr „Do decyzji”, plakietka „Nowa · zdecyduj”). */
  setup_pending_since?: string | null;
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
  "recruiter",
  "trainee",
  "automation",
  "employee",
  "board",
  "user",
];

/**
 * Role WYŁĄCZNE — nie łączą się z żadną inną (lustro CHECK-ów w bazie).
 * Praktykant (0374) widzi tylko „Telefony na dziś”; dodatkowa rola
 * otworzyłaby mu resztę aplikacji. „Automatyzacje” (0446) i „Rada
 * nadzorcza” (0490) tylko czytają — druga rola dałaby im zapis.
 */
export const EXCLUSIVE_ROLES: readonly string[] = [
  "finance",
  "user",
  "trainee",
  "automation",
  "employee",
  "board",
];

/**
 * Rola i grupa uprawnień programu „Ludzie w NEXUSIE” — przy wyłączonym
 * programie (`useHrProgram`, Artur 18.10.2026) nie ma ich na ekranach
 * „Osoby i role”, chyba że ktoś już je ma.
 */
export const HR_PROGRAM_ROLE = "employee";
export const HR_PROGRAM_PERMISSION_GROUP = "people";

export function isExclusiveRole(role: string): boolean {
  return EXCLUSIVE_ROLES.includes(role);
}

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  finance: "Finanse",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  talent_community_manager: "Talent Community Manager",
  recruiter: "Rekruter",
  user: "Viewer (legacy)",
  trainee: "Praktykant",
  automation: "Automatyzacje",
  employee: "Konsultant/Kontraktor",
  board: "Rada nadzorcza",
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
