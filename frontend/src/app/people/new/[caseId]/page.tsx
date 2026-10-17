"use client";

import { notFound, useParams } from "next/navigation";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { OnboardingCaseView } from "@/components/hr/lifecycle/OnboardingCaseView";
import { positiveIntParam } from "@/lib/client-tab";

// Sprawa wejścia: szkic do rozpoczęcia albo zadania w toku.
export default function OnboardingCasePage() {
  const params = useParams<{ caseId: string }>();
  const caseId = positiveIntParam(params.caseId);
  // „/people/abc” to brak celu, nie wieczne „Wczytywanie”.
  if (caseId === null) notFound();
  return <HrConfigGate>{() => <OnboardingCaseView caseId={caseId} />}</HrConfigGate>;
}
