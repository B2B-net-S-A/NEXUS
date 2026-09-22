"use client";

import { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";

import { NewJobPage } from "@/components/v2/jobs/new/NewJobPage";
import { hasCapability } from "@/lib/capabilities";
import { hasRole, useAuthStore } from "@/store/auth";

/**
 * `/jobs/new` — nowa rekrutacja z requestu klienta.
 *
 * Bramka to najwęższe ogniwo zapisu: `POST /api/jobs` wystarcza `job.create`
 * (TacPlus), ale odczyt requestu, zapis Championa i „Przekaż do searchu" to
 * `DeliveryLeadPlus` (admin + Delivery Lead). TAC bez roli DL wracałby z 403
 * w połowie zapisu, więc wraca na listę od razu (funkcja TAC i tak jest
 * wyłączona w UI od 22.09.2026).
 */
export default function NewJobRoute() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const allowed =
    !!user &&
    hasCapability(user, "job.create") &&
    (hasRole(user, "admin") || hasRole(user, "delivery_lead"));

  useEffect(() => {
    if (user && !allowed) router.replace("/jobs");
  }, [user, allowed, router]);

  if (!allowed) return null;
  return (
    <Suspense fallback={null}>
      <NewJobPage />
    </Suspense>
  );
}
