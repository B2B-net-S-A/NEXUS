"use client";

import { notFound, useParams } from "next/navigation";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PersonProfile } from "@/components/hr/people/PersonProfile";
import { positiveIntParam } from "@/lib/client-tab";

export default function PersonPage() {
  const params = useParams<{ userId: string }>();
  const userId = positiveIntParam(params.userId);
  // „/people/abc” to brak celu, nie wieczne „Wczytywanie”.
  if (userId === null) notFound();
  return (
    <HrConfigGate>
      {(config) => <PersonProfile userId={userId} config={config} />}
    </HrConfigGate>
  );
}
