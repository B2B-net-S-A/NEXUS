"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Briefcase, CalendarDays, Users } from "lucide-react";

import { PREVIEW_PATH, resultsKind, seesRecruitment, seesToday } from "@/components/phone-preview/access";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

/**
 * Podgląd na telefonie (decyzja Artura 05.11.2026): wyłącznie odczyt liczb, praca
 * zostaje na laptopie. Bez powłoki aplikacji, bo jej pasek górny i dymki zajmują
 * telefonowi pół ekranu. Zakaz zapisów pilnuje test `phone-preview-read-only`.
 */
export default function PhonePreviewLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? PREVIEW_PATH;
  const user = useAuthStore((s) => s.user);
  const tabs = [
    { href: PREVIEW_PATH, label: "Wyniki", icon: BarChart3, active: pathname === PREVIEW_PATH, show: resultsKind(user) !== null },
    { href: `${PREVIEW_PATH}/rekrutacje`, label: "Rekrutacje", icon: Briefcase, active: pathname.startsWith(`${PREVIEW_PATH}/rekrutacje`), show: seesRecruitment(user) },
    { href: `${PREVIEW_PATH}/zespol`, label: "Zespół", icon: Users, active: pathname.startsWith(`${PREVIEW_PATH}/zespol`), show: true },
    { href: `${PREVIEW_PATH}/dzis`, label: "Dziś", icon: CalendarDays, active: pathname.startsWith(`${PREVIEW_PATH}/dzis`), show: seesToday(user) },
  ].filter((t) => t.show);
  return (
    <div className="mx-auto flex h-dvh max-w-lg flex-col bg-background">
      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      <nav
        className="grid shrink-0 border-t bg-card pb-[env(safe-area-inset-bottom)]"
        style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
        aria-label="Główne"
      >
        {tabs.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            aria-current={t.active ? "page" : undefined}
            className={cn("flex h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium", t.active ? "text-primary" : "text-muted-foreground")}
          >
            <t.icon className="h-5 w-5" />
            {t.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
