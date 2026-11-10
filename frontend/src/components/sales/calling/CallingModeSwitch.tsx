"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { hasPermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

const MODES = [
  { href: "/sales/calling", label: "Kolejka" },
  { href: "/sales/calling/effectiveness", label: "Skuteczność" },
];

/**
 * Dzwonienie: kolejka (praca) i skuteczność (analiza kampanii) pod jedną zakładką,
 * bo jedenasta zakładka Sprzedaży zawinęłaby rząd przy 1280 px. „Skuteczność”
 * widzi tylko „Sprzedaż: edycja” (tak samo pilnuje trasa API).
 */
export function CallingModeSwitch() {
  const pathname = usePathname() ?? "";
  const user = useAuthStore((s) => s.user);
  if (!hasPermission(user, "sales_edit")) return null;
  return (
    <nav aria-label="Dzwonienie" className="inline-flex rounded-md border border-border p-0.5 text-xs">
      {MODES.map((mode) => {
        const active = mode.href === "/sales/calling" ? pathname === mode.href : pathname.startsWith(mode.href);
        return (
          <Link
            key={mode.href}
            href={mode.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded px-2.5 py-1 font-medium",
              active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
            )}
          >
            {mode.label}
          </Link>
        );
      })}
    </nav>
  );
}
