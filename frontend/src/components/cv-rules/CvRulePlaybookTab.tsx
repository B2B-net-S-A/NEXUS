"use client";

import { ClientPlaybookForm } from "@/components/client-playbook/ClientPlaybookForm";

/**
 * Zakładka „Karta klienta" edytora reguł CV — sam formularz karty; cała
 * logika (odczyt, zapis, historia) żyje w `ClientPlaybookForm`, który jest
 * osadzany także w profilu klienta. Tu NIC nie dublujemy.
 */
export function CvRulePlaybookTab({ clientId }: { clientId: number }) {
  return <ClientPlaybookForm clientId={clientId} />;
}
