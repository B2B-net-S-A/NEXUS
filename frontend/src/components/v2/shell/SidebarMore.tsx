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
import type { KeyboardEvent, ReactNode } from "react";

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

/**
 * Pionowe wymiary szyny są takie same w stanie zwiniętym i rozwiniętym (UAT B57).
 *
 * Rozwinięcie pod kursorem zamieniało kreskę sekcji (17 px) na nagłówek (29 px)
 * i `space-y-1` na `space-y-0.5`, więc ikony przesuwały się w dół w trakcie
 * kliknięcia i klik trafiał w sąsiedni link. Nagłówek grupy ma stały slot
 * (`sectionSlot`) w OBU stanach — rozwinięty: tekst, zwinięty: kreska tej samej
 * wysokości — a odstępy nie zależą od stanu. Zmienia się tylko szerokość.
 * Stałe żyją tu (nie w SidebarV2), bo czyta je też szuflada mobilna, a
 * SidebarV2 importuje ten moduł — odwrotny import byłby cyklem.
 */
export const SIDEBAR_VERTICAL_LAYOUT = {
  navSpacing: "space-y-0.5",
  itemSpacing: "space-y-0.5",
  sectionSlot: "h-7 flex items-end",
  groupSpacing: "mb-3",
} as const;

/**
 * Nagłówek grupy szyny. Slot ma tę samą wysokość w obu stanach; na zwiniętej
 * szynie tekst zostaje w drzewie jako `sr-only` (grupa nie traci nazwy
 * dostępnej), a widać tylko kreskę ukrytą przed czytnikami ekranu.
 */
export function SidebarGroupHeading({
  id,
  title,
  collapsed,
}: {
  id: string;
  title: string;
  collapsed: boolean;
}) {
  return (
    <div className={SIDEBAR_VERTICAL_LAYOUT.sectionSlot} data-nav-group-slot="">
      <span
        id={id}
        className={
          collapsed
            ? "sr-only"
            : "w-full truncate px-3 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-sidebar-muted select-none"
        }
      >
        {title}
      </span>
      {collapsed ? (
        <div aria-hidden="true" className="mx-2 mb-3 flex-1 border-t border-sidebar-border" />
      ) : null}
    </div>
  );
}

/** Grupa szyny: nagłówek w stałym slocie + pozycje. `role="group"` z nazwą. */
export function SidebarNavGroup({
  id,
  title,
  collapsed,
  children,
}: {
  id: string;
  title: string;
  collapsed: boolean;
  children: ReactNode;
}) {
  const headingId = `nav-group-${id}`;
  return (
    <div
      role="group"
      aria-labelledby={headingId}
      className={SIDEBAR_VERTICAL_LAYOUT.groupSpacing}
    >
      <SidebarGroupHeading id={headingId} title={title} collapsed={collapsed} />
      <div className={SIDEBAR_VERTICAL_LAYOUT.itemSpacing}>{children}</div>
    </div>
  );
}

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
}: {
  groups: readonly NavMoreGroup[];
  user: ResolveUser;
  badgeCounts: BadgeCounts;
  isActive: (entry: NavEntry) => boolean;
  onNavigate?: () => void;
}) {
  return (
    <>
      {groups.map((group) => (
        <SidebarNavGroup
          key={group.key}
          id={`more-${group.key}`}
          title={group.title}
          collapsed={false}
        >
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
        </SidebarNavGroup>
      ))}
    </>
  );
}
