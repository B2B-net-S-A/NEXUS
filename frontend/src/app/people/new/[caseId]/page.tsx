"use client";

import { useParams } from "next/navigation";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { OnboardingCaseView } from "@/components/hr/lifecycle/OnboardingCaseView";

// Sprawa wejścia: szkic do rozpoczęcia albo zadania w toku.
export default function OnboardingCasePage() {
  const params = useParams<{ caseId: string }>();
  const caseId = Number(params.caseId);
  return <HrConfigGate>{() => <OnboardingCaseView caseId={caseId} />}</HrConfigGate>;
}
