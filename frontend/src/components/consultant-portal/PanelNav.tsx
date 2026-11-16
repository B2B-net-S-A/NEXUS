"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { PortalMe } from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

/** Menu panelu. Sprzęt i Na start pojawiają się tylko wtedy, gdy mają treść. */
export function panelNavItems(me: Pick<PortalMe, "menu">): { href: string; label: string }[] {
  return [
    { href: "/konsultant", label: "Start" },
    ...(me.menu.start ? [{ href: "/konsultant/na-start", label: "Na start" }] : []),
    { href: "/konsultant/rozliczenia", label: "Rozliczenia" },
    { href: "/konsultant/faktury", label: "Faktury" },
    { href: "/konsultant/rozmowy", label: "Rozmowy" },
    ...(me.menu.equipment ? [{ href: "/konsultant/sprzet", label: "Sprzęt" }] : []),
    { href: "/konsultant/pomoc", label: "Pomoc" },
    { href: "/konsultant/szkolenia", label: "Szkolenia" },
  ];
}

/** „Szkolenia” świeci też na ekranie szkolenia i zgłoszenia trenera. */
export function isCurrent(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (pathname === href) return true;
  if (href === "/konsultant/szkolenia") {
    return pathname.startsWith("/konsultant/szkolenia/") || pathname === "/konsultant/trener";
  }
  return false;
}

export function PanelNav({ me }: { me: PortalMe }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Panel konsultanta" className="flex gap-1 overflow-x-auto">
      {panelNavItems(me).map((item) => {
        const current = isCurrent(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "shrink-0 border-b-2 px-3 py-2.5 text-sm",
              current
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
