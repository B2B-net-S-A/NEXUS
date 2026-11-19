"use client";
// MAKIETA (gałąź claude/contract-module-redesign-f8f030, nie do scalenia): `?w=a|b`.
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AnalyticsA } from "@/components/makiety-kontrakty/pages/AnalyticsA";
import { AnalyticsB } from "@/components/makiety-kontrakty/pages/AnalyticsB";

function Inner() {
  const w = useSearchParams().get("w") === "b" ? "b" : "a";
  return w === "a" ? <AnalyticsA /> : <AnalyticsB />;
}

export default function MockupPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
