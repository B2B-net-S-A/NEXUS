"use client";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PayrollSettings } from "@/components/hr/settings/PayrollSettings";

// Ustawienia → Zespół i dostęp → Płace („Ludzie w NEXUSIE”): reguły premii.
// Zapis i odczyt reguł stoją za uprawnieniem „Płace” (serwer pilnuje i tak).
export default function PayrollSettingsPage() {
  return <HrConfigGate>{(config) => <PayrollSettings config={config} />}</HrConfigGate>;
}
