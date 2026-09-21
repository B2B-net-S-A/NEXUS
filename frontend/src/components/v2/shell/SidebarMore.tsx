"use client";

/**
 * „Więcej" — rzadziej używane moduły zwinięte pod jedną pozycją szyny.
 *
 * Pozycje i grupy pochodzą z rejestru (`visibleMoreGroups`), z TĄ SAMĄ bramką
 * widoczności co szyna — panel niczego nie odsłania ani nie chowa, zmienia
 * tylko miejsce. Desktop: panel obok szyny (Radix Popover w trybie modalnym =
 * pułapka fokusu, Esc i klik poza panelem zamykają, fokus wraca na przycisk).
 * Szuflada mobilna renderuje te same grupy w linii (`SidebarMoreInline`) —
 * nakładka w nakładce na telefonie jest nie do obsłużenia.
 */
import Link from "next/link";
import { MoreHorizontal } from "lucide-react";
import type { KeyboardEvent } from "react";

import { cn } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  resolveNavHref,
  type NavBadgeKey,
  type NavEntry,
  type NavMoreGroup,
} from "@/lib/nav-registry";
import { CountBadge, NavItemInner, NavLink, navItemClassName } from "./SidebarNavLink";

export type BadgeCounts = Partial<Record<NavBadgeKey, number>>;

type ResolveUser = Parameters<typeof resolveNavHref>[1];

/** Suma liczników pozycji schowanych pod „Więcej" — trafia na sam przycisk. */
export function moreBadgeTotal(
  groups: readonly NavMoreGroup[],
  counts: BadgeCounts,
): number {
  return groups
    .flatMap((group) => group.items)
    .reduce(
      (sum, item) => sum + (item.badgeKey ? (counts[item.badgeKey] ?? 0) : 0),
      0,
    );
}

/** Czy bieżąca strona leży pod „Więcej" — wtedy świeci się sam przycisk. */
export function isMoreActive(
  groups: readonly NavMoreGroup[],
  isActive: (entry: NavEntry) => boolean,
): boolean {
  return groups.some((group) => group.items.some(isActive));
}

function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const links = Array.from(
    event.currentTarget.querySelectorAll<HTMLAnchorElement>("a[href]"),
  );
  if (links.length === 0) return;
  event.preventDefault();
  const current = links.indexOf(document.activeElement as HTMLAnchorElement);
  const delta = event.key === "ArrowDown" ? 1 : -1;
  const next = current < 0 ? 0 : (current + delta + links.length) % links.length;
  links[next]?.focus();
}

export function SidebarMoreFlyout({
  groups,
  user,
  collapsed,
  open,
  onOpenChange,
  badgeCounts,
  isActive,
}: {
  groups: readonly NavMoreGroup[];
  user: ResolveUser;
  collapsed: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  badgeCounts: BadgeCounts;
  isActive: (entry: NavEntry) => boolean;
}) {
  if (groups.length === 0) return null;
  const total = moreBadgeTotal(groups, badgeCounts);
  const active = isMoreActive(groups, isActive);
  const trigger = (
    <PopoverTrigger asChild>
      <button
        type="button"
        aria-label={total > 0 ? `Więcej (${total} nowych)` : "Więcej"}
        aria-haspopup="dialog"
        className={cn(navItemClassName(active || open, collapsed), !collapsed && "w-full")}
      >
        <NavItemInner
          label="Więcej"
          icon={MoreHorizontal}
          collapsed={collapsed}
          badgeCount={total}
        />
      </button>
    </PopoverTrigger>
  );
  return (
    <Popover open={open} onOpenChange={onOpenChange} modal>
      {/* Tooltip tylko na zwiniętej szynie (tam etykiety nie widać). */}
      {collapsed ? (
        <Tooltip>
          <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          <TooltipContent side="right">
            Więcej{total > 0 ? ` (${total})` : ""}
          </TooltipContent>
        </Tooltip>
      ) : (
        trigger
      )}
      <PopoverContent
        side="right"
        align="end"
        sideOffset={12}
        collisionPadding={12}
        aria-label="Więcej — pozostałe moduły"
        onKeyDown={moveFocus}
        className="w-72 max-h-[min(80vh,640px)] overflow-y-auto p-2"
      >
        <nav aria-label="Więcej" className="space-y-2">
          {groups.map((group) => (
            <section key={group.key} aria-labelledby={`nav-more-${group.key}`}>
              <h2
                id={`nav-more-${group.key}`}
                className="px-2 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground select-none"
              >
                {group.title}
              </h2>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const itemActive = isActive(item);
                  const count = item.badgeKey
                    ? badgeCounts[item.badgeKey]
                    : undefined;
                  return (
                    <li key={item.id}>
                      <Link
                        href={resolveNavHref(item, user)}
                        onClick={() => onOpenChange(false)}
                        aria-current={itemActive ? "page" : undefined}
                        aria-label={item.moreHint ? item.label : undefined}
                        aria-describedby={item.moreHint ? `nav-more-hint-${item.id}` : undefined}
                        className={cn(
                          "flex min-h-9 items-center gap-3 rounded-md px-2 py-1.5 text-sm transition-colors",
                          "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                          itemActive
                            ? "bg-primary/10 font-medium text-primary"
                            : "text-foreground hover:bg-accent",
                        )}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate">{item.label}</span>
                          {item.moreHint ? (
                            <span
                              id={`nav-more-hint-${item.id}`}
                              className="block truncate text-xs font-normal text-muted-foreground"
                            >
                              {item.moreHint}
                            </span>
                          ) : null}
                        </span>
                        {count !== undefined && <CountBadge count={count} />}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </nav>
        <p className="border-t border-border px-2 pb-1 pt-2 text-[11px] text-muted-foreground">
          Wszystko jest też pod ⌘K.
        </p>
      </PopoverContent>
    </Popover>
  );
}

/** Szuflada mobilna: te same grupy w linii, bez zagnieżdżonej nakładki. */
export function SidebarMoreInline({
  groups,
  user,
  badgeCounts,
  isActive,
  onNavigate,
  sectionSlotClassName,
  itemSpacingClassName,
}: {
  groups: readonly NavMoreGroup[];
  user: ResolveUser;
  badgeCounts: BadgeCounts;
  isActive: (entry: NavEntry) => boolean;
  onNavigate?: () => void;
  sectionSlotClassName: string;
  itemSpacingClassName: string;
}) {
  return (
    <>
      {groups.map((group) => (
        <div key={group.key} className="mb-3">
          <div className={sectionSlotClassName}>
            <p className="w-full truncate px-3 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-sidebar-muted select-none">
              {group.title}
            </p>
          </div>
          <div className={itemSpacingClassName}>
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                href={resolveNavHref(item, user)}
                label={item.label}
                icon={item.icon}
                active={isActive(item)}
                collapsed={false}
                badgeCount={item.badgeKey ? badgeCounts[item.badgeKey] : undefined}
                onClick={onNavigate}
                external={item.external}
              />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
