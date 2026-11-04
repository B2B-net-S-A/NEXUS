"use client";

import { notFound, useParams } from "next/navigation";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { OffboardingScreen } from "@/components/hr/lifecycle/OffboardingScreen";
import { positiveIntParam } from "@/lib/client-tab";

// Odejście osoby: przekazanie pracy, zadania, wyłączenie konta, „Cofnij odejście”.
export default function OffboardingPage() {
  const params = useParams<{ userId: string }>();
  const userId = positiveIntParam(params.userId);
  // „/people/abc” to brak celu, nie wieczne „Wczytywanie”.
  if (userId === null) notFound();
  return (
    <HrConfigGate>{(config) => <OffboardingScreen userId={userId} config={config} />}</HrConfigGate>
  );
}
