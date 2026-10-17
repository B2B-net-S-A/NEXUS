// Etykiety i czyste funkcje zakładki „Intune” (testowane bez renderowania).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  IntuneDiscrepancy,
  IntuneDiscrepancyKind,
  IntuneMode,
  IntuneResolution,
  IntuneStatus,
} from "@/lib/api/equipment-intune";

export const INTUNE_KINDS: IntuneDiscrepancyKind[] = [
  "zniknal_z_intune",
  "brak_w_ewidencji",
  "inny_posiadacz",
  "brak_w_intune",
];

export const INTUNE_KIND_LABELS: Record<IntuneDiscrepancyKind, string> = {
  zniknal_z_intune: "Zniknęło z Intune",
  brak_w_ewidencji: "Brak w ewidencji",
  inny_posiadacz: "Inny posiadacz",
  brak_w_intune: "Brak w Intune",
};

/** Widok „Wyjaśnione i pominięte” w tym samym filtrze co rodzaje rozjazdów. */
export const RESOLVED_VIEW = "wyjasnione" as const;
export type IntuneFilter = IntuneDiscrepancyKind | typeof RESOLVED_VIEW;

export const RESOLUTION_LABELS: Record<IntuneResolution, string> = {
  wyjasnione: "Wyjaśnione",
  pominiete: "Pominięte",
};

export const KIND_TONE: Record<IntuneDiscrepancyKind, StatusDotTone> = {
  zniknal_z_intune: "warning",
  brak_w_ewidencji: "warning",
  inny_posiadacz: "danger",
  brak_w_intune: "warning",
};

export const KIND_HINTS: Record<IntuneDiscrepancyKind, string> = {
  zniknal_z_intune: "Urządzenie było w Intune, a w ostatnim odczycie go zabrakło.",
  brak_w_ewidencji: "Urządzenie jest w Intune, a w rejestrze nie ma egzemplarza z tym S/N.",
  inny_posiadacz: "W rejestrze laptop jest wydany komuś innemu niż użytkownik w Intune.",
  brak_w_intune: "Laptop jest wydany w rejestrze, a Intune go nie widzi.",
};

export const INTUNE_MODE_LABELS: Record<IntuneMode, string> = {
  off: "wyłączony",
  simulate: "tryb próbny",
  live: "włączony",
};

export const MODE_NOTE: Record<IntuneMode, string> = {
  off:
    "NEXUS nie czyta jeszcze urządzeń z Intune — odczyt czeka na zgodę administratora " +
    "Microsoft 365. Potem lista będzie się odświeżać co noc, wyłącznie do odczytu, bez kluczy i haseł.",
  simulate:
    "Fikcyjne urządzenia do sprawdzenia ekranu. Nic nie łączy się z Microsoftem.",
  live: "NEXUS czyta urządzenia z Intune co noc, wyłącznie do odczytu. Rejestru sam nie zmienia.",
};

/** Ton kropki stanu: wyłączony szary, próbny niebieski, potem zdrowie odczytu. */
export function intuneStatusTone(status: Pick<IntuneStatus, "mode" | "health">): StatusDotTone {
  if (status.mode === "off") return "neutral";
  if (status.mode === "simulate") return "info";
  return status.health === "healthy" ? "success" : "warning";
}

/** Urządzenie w nagłówku okna: nazwa i S/N; pusto, gdy wiersz nie ma urządzenia. */
export function deviceLabel(row: IntuneDiscrepancy): string {
  const device = row.device;
  if (!device) return "";
  const name = device.device_name ?? "Urządzenie bez nazwy";
  return device.serial_number ? `${name} · S/N ${device.serial_number}` : name;
}
