"use client";

import { useParams } from "next/navigation";

import { OpportunityCard } from "@/components/sales/OpportunityCard";

// Sprzedaż → karta szansy (makieta M1).
export default function SalesOpportunityPage() {
  const params = useParams<{ id: string }>();
  return <OpportunityCard opportunityId={Number(params?.id)} />;
}
