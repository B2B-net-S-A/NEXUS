"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CONTACT_ROLE_LABELS,
  useLinkOpportunityContact,
  useSalesContacts,
  type ContactRole,
  type OpportunityDetail,
} from "@/lib/api/sales";

import { SalesSelect } from "./SalesSelect";

const ROLE_OPTIONS = Object.entries(CONTACT_ROLE_LABELS).map(([value, label]) => ({ value, label }));

interface OpportunityContactsProps {
  opportunity: OpportunityDetail;
  canEdit: boolean;
}

/** Kto po stronie klienta i w jakiej roli — kontakty z karty firmy dopięte do szansy. */
export function OpportunityContacts({ opportunity, canEdit }: OpportunityContactsProps) {
  const companyContacts = useSalesContacts(opportunity.company.id, "", canEdit);
  const link = useLinkOpportunityContact(opportunity.id);
  const { showError } = useToast();
  const [contactId, setContactId] = useState("");
  const [role, setRole] = useState("");
  const linked = new Set(opportunity.contacts.map((contact) => contact.id));
  const available = (companyContacts.data?.items ?? []).filter((contact) => !linked.has(contact.id));

  const onError = (error: unknown) =>
    showError(apiErrorMessage(error, "Nie udało się zmienić kontaktów szansy."));

  return (
    <Card className="space-y-2 p-4">
      <h2 className="text-base font-semibold text-foreground">Kontakty szansy</h2>
      {opportunity.contacts.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze kontaktów.</p>
      ) : (
        <ul className="divide-y divide-border">
          {opportunity.contacts.map((contact) => (
            <li key={contact.id} className="group flex items-start justify-between gap-2 py-2 text-sm">
              <div className="min-w-0">
                <p className="font-medium text-foreground">{contact.full_name}</p>
                <p className="text-xs text-muted-foreground">
                  {[contact.title, contact.role ? CONTACT_ROLE_LABELS[contact.role] : null]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {(contact.email || contact.phone) && (
                  <p className="text-xs">
                    {contact.email && (
                      <a className="text-primary hover:underline" href={`mailto:${contact.email}`}>
                        {contact.email}
                      </a>
                    )}
                    {contact.email && contact.phone ? " · " : ""}
                    {contact.phone}
                  </p>
                )}
              </div>
              {canEdit && (
                <Button
                  size="sm"
                  variant="quiet"
                  className="pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100"
                  onClick={() =>
                    link.mutate({ contact_id: contact.id, role: null, remove: true }, { onError })
                  }
                >
                  Odepnij
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && companyContacts.isSuccess && (
        available.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Nowe osoby dodasz na karcie firmy w zakładce Kontakty.
          </p>
        ) : (
          <div className="flex flex-wrap items-end gap-2 border-t border-border pt-2">
            <SalesSelect
              ariaLabel="Kontakt z firmy"
              className="w-44"
              value={contactId}
              onValueChange={setContactId}
              options={available.map((contact) => ({ value: String(contact.id), label: contact.full_name }))}
              anyLabel="Wybierz osobę"
            />
            <SalesSelect
              ariaLabel="Rola w decyzji"
              className="w-40"
              value={role}
              onValueChange={setRole}
              options={ROLE_OPTIONS}
              anyLabel="Bez roli"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={!contactId}
              loading={link.isPending}
              onClick={() =>
                link.mutate(
                  { contact_id: Number(contactId), role: (role || null) as ContactRole | null },
                  {
                    onSuccess: () => {
                      setContactId("");
                      setRole("");
                    },
                    onError,
                  },
                )
              }
            >
              Dopnij
            </Button>
          </div>
        )
      )}
    </Card>
  );
}
