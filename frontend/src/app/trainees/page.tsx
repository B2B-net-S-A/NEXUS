"use client";

import { TraineesPanel } from "@/components/trainee/TraineesPanel";
import { hasRole, useAuthStore } from "@/store/auth";

// Panel „Praktykanci” (0372) — lustro bramki `/api/trainee/overview`
// (admin + Head of Recruitment).
export default function TraineesPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  if (!hasRole(user, "admin", "head_of_recruitment")) {
    return (
      <div className="p-6 text-muted-foreground">
        Panel praktykantów prowadzi administrator albo Head of Recruitment.
      </div>
    );
  }
  return <TraineesPanel />;
}
