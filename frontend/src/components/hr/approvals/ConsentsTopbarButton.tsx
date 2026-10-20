"use client";

// Ikona „Zgody” w górnym pasku (decyzja Artura 20.10.2026): jeden temat —
// zgody na wydatki i premie poza umową, które czekają na decyzję tej osoby.
// Licznik ze stanu (`GET /api/hr/approval-requests/count`), nie z dzwonków;
// przy zerze ikony nie ma (jak „Nieobecni dziś”), żeby nie rozpychać paska
// na laptopie 1280 px.

import Link from "next/link";
import { ShieldCheck } from "lucide-react";

import { useHrConfig } from "@/lib/api/hr";
import { useApprovalCount } from "@/lib/api/hr-approvals";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

export function ConsentsTopbarButton({ className }: { className?: string }) {
  const user = useAuthStore((state) => state.user);
  const roles = new Set([user?.role, ...(user?.roles ?? [])].filter(Boolean));
  const traineeOnly = roles.size === 1 && roles.has("trainee");
  const config = useHrConfig(Boolean(user) && !traineeOnly);
  const open = Boolean(config.data?.open_modules.approvals);
  const count = useApprovalCount(Boolean(user) && open);
  const total = count.isSuccess ? count.data : 0;
  if (!open || total === 0) return null;

  return (
    <Link
      href="/people/approvals?tab=consents"
      aria-label={`Zgody do decyzji: ${countPl(total, "zgoda", "zgody", "zgód")}`}
      className={cn(
        "relative rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
        className,
      )}
    >
      <ShieldCheck className="h-5 w-5" aria-hidden />
      <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-xs font-bold tabular-nums text-primary-foreground">
        {total > 99 ? "99+" : total}
      </span>
    </Link>
  );
}
