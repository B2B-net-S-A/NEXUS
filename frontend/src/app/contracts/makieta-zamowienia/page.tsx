"use client";
// MAKIETA (gałąź claude/contract-module-redesign-f8f030, nie do scalenia): `?w=a|b`.
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { OrderMailA } from "@/components/makiety-kontrakty/pages/OrderMailA";
import { OrderMailB } from "@/components/makiety-kontrakty/pages/OrderMailB";

function Inner() {
  const w = useSearchParams().get("w") === "b" ? "b" : "a";
  return w === "a" ? <OrderMailA /> : <OrderMailB />;
}

export default function MockupPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
