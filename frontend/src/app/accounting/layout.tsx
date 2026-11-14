"use client";

import type { ReactNode } from "react";

import { AccountingShell } from "@/components/accounting/AccountingShell";

/** /accounting — Księgowość (księga NEXUSA, K1). Zakładki i miesiąc w `AccountingShell`. */
export default function AccountingLayout({ children }: { children: ReactNode }) {
  return <AccountingShell>{children}</AccountingShell>;
}
