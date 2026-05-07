"use client";

import * as React from"react";
import { useMemo } from"react";

import { useAuthStore, ROLE_LABELS, type UserRole } from"@/store/auth";
import {
 usePresence,
 type PresenceResourceType,
 type PresenceViewer,
} from"@/hooks/usePresence";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from"@/components/ui/tooltip";
import { cn } from"@/lib/utils";

interface ActiveViewersProps {
 resourceType: PresenceResourceType;
 resourceId: number | null | undefined;
 /** Pre-loaded viewer list (to avoid mounting a second `usePresence`
 * subscription when a parent hook already owns it). If omitted, the
 * component mounts its own. */
 viewers?: PresenceViewer[];
 max?: number;
 className?: string;
}

const MAX_DEFAULT = 3;

// Small palette of stable colors derived from email hash. Keeps the same
// person colored consistently across pages without persisting per-user state.
const AVATAR_COLORS = ["bg-[#3B82F6]", // blue"bg-[#8B5CF6]", // violet"bg-[#EC4899]", // pink"bg-[#F59E0B]", // amber"bg-[#10B981]", // emerald"bg-[#14B8A6]", // teal"bg-[#EF4444]", // red"bg-[#6366F1]", // indigo
];

function hashString(s: string): number {
 let h = 0;
 for (let i = 0; i < s.length; i += 1) {
 h = (h * 31 + s.charCodeAt(i)) | 0;
 }
 return Math.abs(h);
}

function colorFor(viewer: PresenceViewer): string {
 const idx = hashString(viewer.email || viewer.name) % AVATAR_COLORS.length;
 return AVATAR_COLORS[idx];
}

function initialsOf(name: string): string {
 const parts = name.trim().split(/\s+/).filter(Boolean);
 if (parts.length === 0) return"?";
 if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
 return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function roleLabel(role: string): string {
 return ROLE_LABELS[role as UserRole] ?? role;
}

function ViewerAvatar({
 viewer,
 small = false,
}: {
 viewer: PresenceViewer;
 small?: boolean;
}): React.ReactElement {
 const ring = viewer.editing.length > 0 ?"ring-2 ring-[#F59E0B]" :"";
 return (
 <Tooltip>
 <TooltipTrigger asChild>
 <Avatar
 size={small ?"xs" :"sm"}
 className={cn("border-2 border-[hsl(var(--bg-default))]",
 ring, "cursor-default",
 )}
 >
 <AvatarFallback
 className={cn(colorFor(viewer),"text-white font-semibold")}
 >
 {initialsOf(viewer.name)}
 </AvatarFallback>
 </Avatar>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <div className="flex flex-col gap-0.5">
 <span className="text-xs font-semibold">{viewer.name}</span>
 <span className="text-[10px] opacity-80">{roleLabel(viewer.role)}</span>
 {viewer.editing.length > 0 ? (
 <span className="text-[10px] text-[#F59E0B]">
 edytuje: {viewer.editing.join(",")}
 </span>
 ) : null}
 </div>
 </TooltipContent>
 </Tooltip>
 );
}

export function ActiveViewers({
 resourceType,
 resourceId,
 viewers: viewersProp,
 max = MAX_DEFAULT,
 className,
}: ActiveViewersProps): React.ReactElement | null {
 // Only subscribe internally if caller didn't already supply a list.
 const internal = usePresence(
 resourceType,
 viewersProp === undefined ? resourceId ?? null : null,
 );
 const raw = viewersProp ?? internal.viewers;

 const { user } = useAuthStore();
 const others = useMemo<PresenceViewer[]>(
 () => raw.filter((v) => !user || v.user_id !== user.id),
 [raw, user],
 );

 if (others.length === 0) return null;

 const visible = others.slice(0, max);
 const overflow = others.slice(max);
 const overflowCount = overflow.length;

 return (
 <TooltipProvider delayDuration={200}>
 <div
 className={cn("flex items-center gap-0", className)}
 aria-label={`Obecnie ogląda: ${others.map((v) => v.name).join(",")}`}
 >
 {visible.map((v, idx) => (
 <div
 key={v.user_id}
 className={idx === 0 ?"" :"-ml-2"}
 style={{ zIndex: visible.length - idx }}
 >
 <ViewerAvatar viewer={v} />
 </div>
 ))}
 {overflowCount > 0 ? (
 <Tooltip>
 <TooltipTrigger asChild>
 <div
 className={cn("-ml-2 flex h-8 w-8 items-center justify-center rounded-full","border-2 border-[hsl(var(--bg-default))]","bg-card text-foreground","text-[10px] font-semibold cursor-default",
 )}
 >
 +{overflowCount}
 </div>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <div className="flex flex-col gap-0.5">
 {overflow.map((v) => (
 <span key={v.user_id} className="text-xs">
 {v.name} · {roleLabel(v.role)}
 </span>
 ))}
 </div>
 </TooltipContent>
 </Tooltip>
 ) : null}
 </div>
 </TooltipProvider>
 );
}

export default ActiveViewers;
