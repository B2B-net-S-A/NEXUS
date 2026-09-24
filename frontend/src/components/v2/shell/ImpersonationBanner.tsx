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
    // Stała wysokość `h-9` (jeden wiersz) — panel „Moi ludzie” liczy na nią
    // swoje `top`. Na telefonie krótszy tekst i przycisk „Wróć”, żeby
    // nazwisko podglądanej osoby się zmieściło.
    <div className="flex h-9 shrink-0 items-center justify-center gap-2 bg-amber-500 px-3 text-sm font-medium text-amber-950 shadow-xs sm:gap-3 sm:px-4">
      <Eye className="h-4 w-4 shrink-0" />
      <span className="min-w-0 truncate">
        Podgląd jako <strong>{user.name}</strong>
        <span className="hidden sm:inline">
          {" "}({roleLabel}) — widzisz aplikację oczami tego użytkownika (tylko
          do odczytu).
        </span>
      </span>
      <button
        onClick={stopImpersonating}
        aria-label="Wróć do swojego konta"
        className="flex shrink-0 items-center gap-1 rounded-md bg-amber-950/15 px-3 py-1 font-semibold text-amber-950 transition-colors hover:bg-amber-950/25 sm:ml-2"
      >
        <X className="h-3.5 w-3.5" />
        <span className="sm:hidden">Wróć</span>
        <span className="hidden sm:inline">Wróć do swojego konta</span>
      </button>
    </div>
  );
}

export default ImpersonationBanner;
