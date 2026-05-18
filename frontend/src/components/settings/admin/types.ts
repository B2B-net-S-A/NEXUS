export interface AdminUser {
  id: number;
  email: string;
  name: string;
  role: string;
  /** Multi-role (migracja 0110). Lista wszystkich ról użytkownika. */
  roles?: string[];
  recruiter_role: string | null;
  is_active: boolean;
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
  recruiter_role: string;
}

// Pełna lista ról systemu (sync z backend/app/models/user.py:UserRole).
export const ROLES = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
  "user",
];

export const RECRUITER_ROLES = [
  "",
  "recruiter",
  "sourcer",
  "tac",
  "delivery_lead",
  "quality_control",
  "admin",
];

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  tac: "TAC",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  user: "Viewer",
  manager: "Manager",
  client: "Klient",
};

export const RECRUITER_ROLE_LABELS: Record<string, string> = {
  "": "—",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  tac: "TAC",
  delivery_lead: "Delivery Lead",
  quality_control: "Quality Control",
  admin: "Admin",
};

export function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pl-PL", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
