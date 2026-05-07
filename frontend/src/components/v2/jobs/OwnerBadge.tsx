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
 /** Rendered text when `user` is null (otherwise defaults to"Nieprzypisany"). */
 unassignedLabel?: string;
}

function initialsFor(name: string): string {
 const parts = name.trim().split(/\s+/);
 if (parts.length === 0) return"?";
 if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
 return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Pill representing the primary owner (or a collaborator) of a job. Used in
 * JobsListV2 cards, job detail header, dashboard widget, collaborator chips.
 */
export function OwnerBadge({
 user,
 size ="sm",
 showRole = false,
 className,
 unassignedLabel ="Nieprzypisany",
}: OwnerBadgeProps) {
 const isAssigned = Boolean(user);
 const dims =
 size ==="md"
 ?"h-7 text-xs gap-2 pr-2.5 pl-1"
 :"h-6 text-[11px] gap-1.5 pr-2 pl-0.5";
 const avatarSize = size ==="md" ?"h-6 w-6 text-[10px]" :"h-5 w-5 text-[9px]";

 return (
 <span
 className={cn("inline-flex items-center rounded-full font-medium",
 isAssigned
 ?"bg-primary/10 text-primary"
 :"bg-[hsl(var(--border))] text-muted-foreground",
 dims,
 className
 )}
 title={user ? `${user.name} (${ROLE_LABELS[user.role]})` : unassignedLabel}
 >
 <span
 className={cn("inline-flex items-center justify-center rounded-full font-semibold",
 isAssigned
 ?"bg-primary text-white"
 :"bg-[hsl(var(--muted-foreground))] text-white/90",
 avatarSize
 )}
 aria-hidden
 >
 {user ? initialsFor(user.name) :"·"}
 </span>
 <span className="truncate max-w-[10rem]">{user?.name ?? unassignedLabel}</span>
 {showRole && user ? (
 <span className="text-muted-foreground font-normal">
 · {ROLE_LABELS[user.role]}
 </span>
 ) : null}
 </span>
 );
}
