"use client";

import { usePathname } from "next/navigation";
import { SettingsBreadcrumb } from "@/components/settings/SettingsBreadcrumb";
import { SettingsSideNav } from "@/components/settings/SettingsSideNav";
import { useHrProgram } from "@/lib/api/hr";
import { findSettingsArea, findSettingsItemByRoute } from "@/lib/settings-registry";
import { useAuthStore } from "@/store/auth";

// Podstrony Ustawień z własną trasą (np. `/settings/cv-rules`) dostają tę samą
// ścieżkę i lewą kolumnę co ekrany w `/settings?item=` — z każdego miejsca jest
// jedno kliknięcie do sąsiedniej pozycji, obszaru i strony startowej. Strona
// `/settings` rysuje je sama; trasy spoza mapy (ukryte z menu) zostają bez zmian.
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const user = useAuthStore((state) => state.user);
  const item = findSettingsItemByRoute(pathname);
  // Pozycja programu „Ludzie w NEXUSIE” przy wyłączonym programie: strona sama
  // mówi „Nie znaleziono”, więc ścieżka nie zdradza jej nazwy. Lewa kolumna
  // pyta o program dla każdej podstrony, bo pokazuje pozycje Kadr i Płac.
  const hrProgram = useHrProgram(Boolean(item && user));
  if (!item || (item.gate.hrProgram && !hrProgram)) return <>{children}</>;
  return (
    <div className="mx-auto max-w-[1600px] lg:flex lg:gap-8">
      <SettingsSideNav user={user} areaId={item.area} itemId={item.id} context={{ hrProgram }} />
      <div className="min-w-0 flex-1 space-y-4">
        <div className="mx-auto max-w-7xl">
          <SettingsBreadcrumb area={findSettingsArea(item.area)} item={item} />
        </div>
        {children}
      </div>
    </div>
  );
}
