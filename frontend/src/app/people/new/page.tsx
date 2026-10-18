"use client";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { OnboardingWizard } from "@/components/hr/lifecycle/OnboardingWizard";

// „Ludzie w NEXUSIE” (16.10.2026): kreator wejścia nowej osoby (Kadry).
export default function NewPersonPage() {
  return <HrConfigGate>{(config) => <OnboardingWizard config={config} />}</HrConfigGate>;
}
