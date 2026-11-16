"use client";

import { ComplianceBanner } from "@/components/compliance/ComplianceBanner";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PayrollMonthsScreen } from "@/components/hr/payroll/PayrollMonthsScreen";

// „Ludzie → Płace” (16.10.2026): miesiące płac — stan, osoby, sumy per waluta.
// O dostępie decyduje serwer (uprawnienie „Płace”; admin zawsze).
// Pasek „Przepisy” (15.11.2026) stoi na stronie, nie w ekranie: harness
// `/preview/hr-payroll` renderuje sam ekran i nie może wysyłać zapytań.
export default function PeoplePayrollPage() {
  return (
    <HrConfigGate>
      {(config) => (
        <div className="space-y-4">
          <ComplianceBanner role="payroll" />
          <PayrollMonthsScreen config={config} />
        </div>
      )}
    </HrConfigGate>
  );
}
