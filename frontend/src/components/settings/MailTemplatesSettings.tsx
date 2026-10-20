"use client";

import { useState } from "react";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { CandidateEmailTemplates } from "@/components/settings/CandidateEmailTemplates";
import EmailTemplatesCard from "@/components/settings/EmailTemplatesCard";

type MailTab = "candidates" | "outlook";

const TABS = [
  { value: "candidates", label: "Do kandydatów" },
  { value: "outlook", label: "Moje w Outlooku" },
];

/**
 * Ustawienia → Rekrutacja → Szablony maili (20.10.2026): oba rodzaje szablonów
 * w jednej pozycji. Do 20.10 pozycja z menu pokazywała tylko podpowiedzi do
 * Outlooka, a szablony okna „Wyślij e-mail” leżały pod `/settings/templates`,
 * do którego prowadził jedynie link „otwórz szablony odrzuceń”.
 */
export function MailTemplatesSettings() {
  const [tab, setTab] = useState<MailTab>("candidates");
  return (
    <div className="space-y-4">
      <TabbedNav
        tabs={TABS}
        value={tab}
        onValueChange={(value) => setTab(value as MailTab)}
        ariaLabel="Szablony maili"
      />
      {tab === "candidates" ? (
        <CandidateEmailTemplates />
      ) : (
        <EmailTemplatesCard />
      )}
    </div>
  );
}

export default MailTemplatesSettings;
