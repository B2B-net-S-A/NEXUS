"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto shrink-0 rounded-md bg-primary text-primary-foreground text-[10px] font-semibold tabular-nums min-w-[18px] h-[18px] px-1.5 flex items-center justify-center leading-none">
      {count > 99 ? "99+" : count}
    </span>
  );
}

/**
 * Klasy pozycji szyny — wspólne dla linków i przycisku „Więcej", żeby oba
 * miały TĘ SAMĄ wysokość w obu stanach (UAT B57: pionowe wymiary nie zależą
 * od zwinięcia; zmienia się tylko szerokość).
 */
export function navItemClassName(active: boolean, collapsed: boolean): string {
  return cn(
    "relative flex items-center text-sm transition-colors duration-150",
    "rounded-md focus:outline-hidden focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-1 focus-visible:ring-offset-sidebar",
    collapsed ? "justify-center h-9 w-9 mx-auto" : "gap-3 px-3 h-9",
    active
      ? collapsed
        ? "bg-primary/10 text-primary font-medium"
        : "bg-primary/10 text-primary font-medium before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:h-5 before:w-[3px] before:rounded-r-full before:bg-primary"
      : "text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-foreground",
  );
}

export function NavItemInner({
  label,
  icon: Icon,
  collapsed,
  badgeCount,
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  collapsed: boolean;
  badgeCount?: number;
}) {
  return (
    <>
      <Icon className="shrink-0 h-4 w-4" />
      {!collapsed && (
        <>
          <span className="truncate flex-1 text-left">{label}</span>
          {badgeCount !== undefined && <CountBadge count={badgeCount} />}
        </>
      )}
      {collapsed && badgeCount !== undefined && badgeCount > 0 && (
        <span
          className="absolute top-1 right-1 w-1.5 h-1.5 bg-primary rounded-full"
          aria-label={`${badgeCount} nowych`}
        />
      )}
    </>
  );
}

export function NavLink({
  href,
  label,
  icon,
  active,
  collapsed,
  badgeCount,
  onClick,
  external,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  collapsed: boolean;
  badgeCount?: number;
  onClick?: () => void;
  external?: boolean;
}) {
  const sharedClassName = navItemClassName(active, collapsed);
  const inner = (
    <NavItemInner
      label={label}
      icon={icon}
      collapsed={collapsed}
      badgeCount={badgeCount}
    />
  );
  const link = external ? (
    <a
      href={href}
      onClick={onClick}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${label} (otwiera się w nowej karcie)`}
      className={sharedClassName}
    >
      {inner}
    </a>
  ) : (
    <Link
      href={href}
      onClick={onClick}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={sharedClassName}
    >
      {inner}
    </Link>
  );

  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">
        {label}
        {badgeCount !== undefined && badgeCount > 0 ? ` (${badgeCount})` : ""}
      </TooltipContent>
    </Tooltip>
  );
}
