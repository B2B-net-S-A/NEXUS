"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { CompanyCard } from "@/components/sales/CompanyCard";

// Sprzedaż → karta firmy (makieta M3).
export default function SalesCompanyPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<p className="py-6 text-sm text-muted-foreground">Wczytywanie firmy…</p>}>
      <CompanyCard companyId={Number(params?.id)} />
    </Suspense>
  );
}
