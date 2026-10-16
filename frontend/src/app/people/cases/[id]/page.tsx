"use client";

import { useParams } from "next/navigation";

import { CaseDetailView } from "@/components/admin-cases/CaseDetailView";
import { HrConfigGate } from "@/components/hr/HrConfigGate";

export default function PeopleCasePage() {
  const params = useParams<{ id: string }>();
  const caseId = Number(params.id);
  return <HrConfigGate>{() => <CaseDetailView caseId={caseId} />}</HrConfigGate>;
}
