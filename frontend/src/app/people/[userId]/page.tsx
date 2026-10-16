"use client";

import { useParams } from "next/navigation";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PersonProfile } from "@/components/hr/people/PersonProfile";

export default function PersonPage() {
  const params = useParams<{ userId: string }>();
  const userId = Number(params.userId);
  return (
    <HrConfigGate>
      {(config) => <PersonProfile userId={userId} config={config} />}
    </HrConfigGate>
  );
}
