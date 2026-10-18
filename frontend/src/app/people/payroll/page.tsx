"use client";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PayrollMonthsScreen } from "@/components/hr/payroll/PayrollMonthsScreen";

// „Ludzie → Płace” (16.10.2026): miesiące płac — stan, osoby, sumy per waluta.
// O dostępie decyduje serwer (uprawnienie „Płace”; admin zawsze).
export default function PeoplePayrollPage() {
  return <HrConfigGate>{(config) => <PayrollMonthsScreen config={config} />}</HrConfigGate>;
}
