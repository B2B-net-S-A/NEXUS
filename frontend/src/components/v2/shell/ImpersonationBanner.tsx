"use client";

import { Eye, X } from "lucide-react";
import { useAuthStore, ROLE_LABELS } from "@/store/auth";

/**
 * ImpersonationBanner — pasek widoczny gdy admin ogląda aplikację jako inny
 * użytkownik („podgląd jako użytkownik"). Pokazuje kogo podglądamy i pozwala
 * jednym kliknięciem wrócić do własnego konta admina.
 *
 * Renderowany w AppShellV2 nad Topbarem. Gdy nie impersonujemy — null.
 */
export function ImpersonationBanner() {
  const user = useAuthStore((s) => s.user);
  const realUser = useAuthStore((s) => s.realUser);
  const stopImpersonating = useAuthStore((s) => s.stopImpersonating);

  if (!realUser || !user) return null;

  const roleLabel = ROLE_LABELS[user.role] ?? user.role;

  return (
    <div className="flex items-center justify-center gap-3 bg-amber-500 px-4 py-2 text-sm font-medium text-amber-950 shadow-xs">
      <Eye className="h-4 w-4 shrink-0" />
      <span className="truncate">
        Podgląd jako <strong>{user.name}</strong> ({roleLabel}) — widzisz
        aplikację oczami tego użytkownika (tylko do odczytu).
      </span>
      <button
        onClick={stopImpersonating}
        className="ml-2 flex shrink-0 items-center gap-1 rounded-md bg-amber-950/15 px-3 py-1 font-semibold text-amber-950 transition-colors hover:bg-amber-950/25"
      >
        <X className="h-3.5 w-3.5" />
        Wróć do swojego konta
      </button>
    </div>
  );
}

export default ImpersonationBanner;
