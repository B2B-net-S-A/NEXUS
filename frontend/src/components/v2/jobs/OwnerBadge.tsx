"use client";

import * as React from"react";
import { cn } from"@/lib/utils";
import { ROLE_LABELS } from"@/store/auth";
import type { UserBrief } from"./ownership-types";

interface OwnerBadgeProps {
 user?: UserBrief | null;
 size?:"sm" |"md";
 showRole?: boolean;
 className?: string;
 /** Tekst przy braku osoby (domyślnie „Bez rekrutera”). */
 unassignedLabel?: string;
}

function initialsFor(name: string): string {
 const parts = name.trim().split(/\s+/);
 if (parts.length === 0) return"?";
 if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
 return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Plakietka pierwszego rekrutera rekrutacji (kafelki listy, okno zmiany
 * rekrutera). Brak osoby to „Bez rekrutera” w tonie ostrzeżenia — tak samo jak
 * na liście i w panelu rekrutacji: nikt nad rekrutacją nie pracuje.
 */
export function OwnerBadge({
 user,
 size ="sm",
 showRole = false,
 className,
 unassignedLabel ="Bez rekrutera",
}: OwnerBadgeProps) {
 const dims =
 size === "md"
 ?"h-7 text-xs gap-2 pr-2.5"
 :"h-6 text-[11px] gap-1.5 pr-2";
 const avatarSize = size === "md" ?"h-6 w-6 text-[10px]" :"h-5 w-5 text-[10px]";

 if (!user) {
 return (
 <span
 className={cn("inline-flex items-center rounded-full bg-warning-muted font-medium text-warning-muted-foreground",
 dims,
 size === "md" ?"pl-2.5" :"pl-2",
 className
 )}
 title={unassignedLabel}
 >
 <span className="truncate max-w-40">{unassignedLabel}</span>
 </span>
 );
 }

 return (
 <span
 className={cn("inline-flex items-center rounded-full bg-primary/10 font-medium text-primary",
 dims,
 size === "md" ?"pl-1" :"pl-0.5",
 className
 )}
 title={`${user.name} (${ROLE_LABELS[user.role]})`}
 >
 <span
 className={cn("inline-flex items-center justify-center rounded-full bg-primary font-semibold text-primary-foreground",
 avatarSize
 )}
 aria-hidden
 >
 {initialsFor(user.name)}
 </span>
 <span className="truncate max-w-40">{user.name}</span>
 {showRole ? (
 <span className="text-muted-foreground font-normal">
 · {ROLE_LABELS[user.role]}
 </span>
 ) : null}
 </span>
 );
}
