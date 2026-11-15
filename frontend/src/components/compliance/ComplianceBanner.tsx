"use client";

import Link from "next/link";

import { useComplianceSummary, type ComplianceRole } from "@/lib/api/compliance";
import { canOpenCompliance } from "@/lib/compliance-access";
import { useAuthStore } from "@/store/auth";

import { formatDay } from "./compliance-model";

/** „dla Księgowości”, „dla Kadr i płac” — dopełniacz do zdania paska. */
const ROLE_FOR: Record<ComplianceRole, string> = {
  board: "Zarządu i CFO",
  accounting: "Księgowości",
  payroll: "Kadr i płac",
  contracts: "Umów",
  recruitment: "Rekrutacji",
};

function changesWord(count: number): string {
  if (count === 1) return "zmiana";
  const tens = count % 100;
  const ones = count % 10;
  return ones >= 2 && ones <= 4 && (tens < 12 || tens > 14) ? "zmiany" : "zmian";
}

/**
 * Pasek „Przepisy” w module (Księgowość, Płace): zmiany dla roli do decyzji.
 * Nic nie pokazuje, gdy radar jest wyłączony, nie ma nic do decyzji, zapytanie
 * się wczytuje albo padło — pasek jest podpowiedzią, nie warunkiem ekranu.
 */
export function ComplianceBanner({ role }: { role: ComplianceRole }) {
  const user = useAuthStore((s) => s.user);
  const allowed = canOpenCompliance(user);
  const summary = useComplianceSummary(role, allowed);
  const data = summary.data;
  if (!allowed || !summary.isSuccess || !data?.enabled || data.to_decide === 0) return null;
  return (
    <Link
      href={`/compliance?lens=${role}`}
      className="flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md border border-warning/40 bg-warning/10 px-3 py-1.5 text-[13px] hover:bg-warning/15"
    >
      <span className="font-semibold">
        Przepisy: {data.to_decide} {changesWord(data.to_decide)} dla {ROLE_FOR[role]} do decyzji
      </span>
      {data.top.length ? (
        <span className="min-w-0 text-muted-foreground">
          {data.top.map((top) => `· ${top.title}${top.deadline ? ` (do ${formatDay(top.deadline)})` : ""}`).join(" ")}
        </span>
      ) : null}
      <span className="ml-auto font-medium text-primary">Otwórz →</span>
    </Link>
  );
}
