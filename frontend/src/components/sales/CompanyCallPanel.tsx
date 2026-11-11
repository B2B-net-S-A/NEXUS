"use client";

import { useState } from "react";

import { useOpportunities, useSalesContacts, type Ref, type SalesContact } from "@/lib/api/sales";

import { CallPanel } from "./MyDayRowPanels";
import { SalesSelect } from "./SalesSelect";

const phoneOf = (contact: SalesContact): string | null => contact.mobile_phone || contact.phone || null;

/**
 * „Zaloguj rozmowę” na karcie firmy (decyzja Artura 11.11.2026): te same wyniki i krok
 * z podpowiedzi co w „Moim dniu”. Firma z jedną otwartą szansą zapisuje rozmowę przy niej,
 * w innym przypadku przy samej firmie (`POST /companies/{id}/calls`).
 */
export function CompanyCallPanel({ company, onDone }: { company: Ref; onDone: () => void }) {
  const contacts = useSalesContacts(company.id);
  const opportunities = useOpportunities({ company_id: company.id });
  const reachable = (contacts.data?.items ?? []).filter((contact) => !contact.do_not_contact_at && phoneOf(contact));
  const [chosen, setChosen] = useState<string>("");
  const person = reachable.find((contact) => String(contact.id) === chosen) ?? reachable[0] ?? null;
  const open = (opportunities.data?.items ?? []).filter((item) => item.status === "open");
  const only = open.length === 1 ? open[0] : null;

  if (!contacts.isSuccess || !opportunities.isSuccess) {
    return <p className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground">Wczytywanie osób…</p>;
  }
  if (!person) {
    return (
      <p className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
        Nikt w kontaktach tej firmy nie ma numeru telefonu. Dodaj go w zakładce Kontakty.
      </p>
    );
  }
  return (
    <section aria-label="Zapis rozmowy" className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-2 px-3 pt-2 text-sm">
        <span className="font-medium text-foreground">Rozmowa z</span>
        {reachable.length > 1 ? (
          <SalesSelect
            ariaLabel="Z kim rozmowa"
            className="w-64"
            value={String(person.id)}
            onValueChange={setChosen}
            options={reachable.map((contact) => ({
              value: String(contact.id),
              label: `${contact.full_name} · ${phoneOf(contact)}`,
            }))}
          />
        ) : (
          <span className="text-foreground">
            {person.full_name} · {phoneOf(person)}
          </span>
        )}
        <span className="text-xs text-muted-foreground">
          {only ? `zapisze się przy szansie „${only.title}”` : "zapisze się przy firmie"}
        </span>
      </div>
      <CallPanel
        key={person.id}
        row={{
          company,
          opportunity: only ? { id: only.id, title: only.title } : null,
          person: { id: person.id, name: person.full_name, title: person.title, phone: phoneOf(person), email: person.email },
          closesActivityId: null,
        }}
        onDone={onDone}
      />
    </section>
  );
}
