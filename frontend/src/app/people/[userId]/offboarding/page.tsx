"use client";

import { useParams } from "next/navigation";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { OffboardingScreen } from "@/components/hr/lifecycle/OffboardingScreen";

// Odejście osoby: przekazanie pracy, zadania, wyłączenie konta, „Cofnij odejście”.
export default function OffboardingPage() {
  const params = useParams<{ userId: string }>();
  const userId = Number(params.userId);
  return (
    <HrConfigGate>{(config) => <OffboardingScreen userId={userId} config={config} />}</HrConfigGate>
  );
}
