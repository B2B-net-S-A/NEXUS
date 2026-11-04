"use client";

import { useParams } from "next/navigation";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { PayrollMonthScreen } from "@/components/hr/payroll/PayrollMonthScreen";
import { parseYm } from "@/components/hr/payroll/payroll-format";

// „Ludzie → Płace → miesiąc” (`/people/payroll/2026-09`). Płace widzą wszystkich
// z kwotami; przełożony — godziny i premie swojego zespołu, bez stawek (D2).
export default function PeoplePayrollMonthPage() {
  const params = useParams<{ ym: string }>();
  const period = parseYm(params.ym);
  if (!period) {
    return (
      <QueryStateNotice state="not_found" description="Niepoprawny miesiąc w adresie." />
    );
  }
  return (
    <HrConfigGate>
      {(config) => (
        <PayrollMonthScreen config={config} year={period.year} month={period.month} />
      )}
    </HrConfigGate>
  );
}
