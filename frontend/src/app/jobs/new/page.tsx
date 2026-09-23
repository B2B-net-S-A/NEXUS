"use client";

import { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";

import { NewJobPage } from "@/components/v2/jobs/new/NewJobPage";
import { NewJobPageSkeleton } from "@/components/v2/jobs/new/NewJobPageSkeleton";
import { hasCapability } from "@/lib/capabilities";
import { useAuthStore } from "@/store/auth";

/**
 * `/jobs/new` — nowa rekrutacja z requestu klienta.
 *
 * Bramka to capability `job.create` — ta sama, która pokazuje przycisk „Nowa
 * rekrutacja" i skróty `j` / ⌘⇧J. Liczona z najwęższego ogniwa zapisu: odczyt
 * requestu, zapis Championa i „Przekaż do searchu" to `DeliveryLeadPlus`
 * (admin + Delivery Lead). Jedna reguła w obu miejscach = przycisk nigdy nie
 * prowadzi na stronę, która odsyła na listę (audyt ról 22.09, U4).
 *
 * „Nie wiem jeszcze” ≠ „nie wolno” (jak `RequireRole`): przed `hydrate()`
 * store ma `user === null`, a HTML z serwera i czas ładowania kodu strony to
 * właśnie ten stan. Do 23.09.2026 strona zwracała wtedy `null` (także jako
 * fallback `Suspense`), więc na produkcji przez ~4 s pod shellem był pusty
 * obszar. Teraz w tym oknie stoi szkielet formularza; `null` zostaje tylko dla
 * kogoś, o kim WIEMY, że nie ma `job.create` (za chwilę przekierowanie).
 */
export default function NewJobRoute() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const allowed = !!user && hasCapability(user, "job.create");

  useEffect(() => {
    if (user && !allowed) router.replace("/jobs");
  }, [user, allowed, router]);

  if (!user) return <NewJobPageSkeleton />;
  if (!allowed) return null;
  return (
    <Suspense fallback={<NewJobPageSkeleton />}>
      <NewJobPage />
    </Suspense>
  );
}
