import type { UserRole } from "@/store/auth";

/**
 * Minimal user DTO returned by the backend for primary_owner / collaborators /
 * directory listings. Mirrors `UserBrief` in backend/app/schemas/job.py.
 */
export interface UserBrief {
  id: number;
  name: string;
  email: string;
  role: UserRole;
}
