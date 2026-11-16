"use client";

// Poligon dla obecnych (Artur, 16.11.2026): do terminu przypomina nad treścią
// ekranu, ile ćwiczeń z luk zostało. Po terminie prowadzi już blokada
// (`useStartGate` → `/poligon`), więc pasek znika.

import { Target } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useStartStatus } from "@/lib/novelties/api";
import { pluralPl } from "@/lib/plural-pl";
import { formatLukiDue, lukiLeft } from "@/lib/novelties/logic";
import { useAuthStore } from "@/store/auth";

export function PoligonLukiNotice() {
  const user = useAuthStore((s) => s.user);
  const pathname = usePathname() ?? "";
  const status = useStartStatus(Boolean(user) && user?.role !== "trainee");
  const poligon = status?.poligon;
  const left = lukiLeft(poligon);
  if (!poligon?.luki || left === 0 || status?.enforced || pathname.startsWith("/poligon")) return null;
  return (
    <p
      role="status"
      className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2 text-sm"
    >
      <Target className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <b>Poligon: {left} {pluralPl(left, "ćwiczenie", "ćwiczenia", "ćwiczeń")}</b> z funkcji, których jeszcze nie używasz — do {formatLukiDue(poligon.luki.due)}.
      </span>
      <Link href="/poligon" className="font-medium text-primary underline-offset-2 hover:underline">
        Przejdź na poligon
      </Link>
    </p>
  );
}
