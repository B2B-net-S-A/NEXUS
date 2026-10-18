"use client";

import { notFound, useParams } from "next/navigation";

import { CaseDetailView } from "@/components/admin-cases/CaseDetailView";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { positiveIntParam } from "@/lib/client-tab";

export default function PeopleCasePage() {
  const params = useParams<{ id: string }>();
  const caseId = positiveIntParam(params.id);
  // „/people/abc” to brak celu, nie wieczne „Wczytywanie”.
  if (caseId === null) notFound();
  return <HrConfigGate>{() => <CaseDetailView caseId={caseId} />}</HrConfigGate>;
}
