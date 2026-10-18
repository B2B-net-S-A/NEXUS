"use client";

import { usePathname } from "next/navigation";
import { SettingsBreadcrumb } from "@/components/settings/SettingsBreadcrumb";
import { useHrProgram } from "@/lib/api/hr";
import { findSettingsArea, findSettingsItemByRoute } from "@/lib/settings-registry";

// Podstrony Ustawień z własną trasą (np. `/settings/cv-rules`) dostają tę samą
// ścieżkę co ekrany w `/settings?item=` — z każdego miejsca jest jedno
// kliknięcie do obszaru i do strony startowej. Strona `/settings` rysuje
// ścieżkę sama; trasy spoza mapy (ukryte z menu) zostają bez zmian.
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const item = findSettingsItemByRoute(pathname);
  // Pozycja programu „Ludzie w NEXUSIE” przy wyłączonym programie: strona sama
  // mówi „Nie znaleziono”, więc ścieżka nie zdradza jej nazwy.
  const hrProgram = useHrProgram(Boolean(item?.gate.hrProgram));
  if (!item || (item.gate.hrProgram && !hrProgram)) return <>{children}</>;
  return (
    <div className="space-y-4">
      <div className="mx-auto max-w-7xl">
        <SettingsBreadcrumb area={findSettingsArea(item.area)} item={item} />
      </div>
      {children}
    </div>
  );
}
