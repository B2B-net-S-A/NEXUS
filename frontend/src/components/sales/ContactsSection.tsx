"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useCreateSalesContact, useSalesContacts } from "@/lib/api/sales";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

interface ContactsSectionProps {
  companyId: number;
}

const EMPTY = { full_name: "", title: "", email: "", phone: "" };

/** Osoby po stronie firmy (decydenci, kupcy) i szybkie dodanie kontaktu. */
export function ContactsSection({ companyId }: ContactsSectionProps) {
  const contacts = useSalesContacts(companyId);
  const create = useCreateSalesContact();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { showError, showSuccess } = useToast();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const items = contacts.data?.items ?? [];
  const state = resolveViewState({
    isLoading: contacts.isLoading,
    error: contacts.error,
    isSuccess: contacts.isSuccess,
    isEmpty: items.length === 0,
  });

  const save = () => {
    if (!form.full_name.trim()) {
      showError("Podaj imię i nazwisko.");
      return;
    }
    create.mutate(
      {
        company_id: companyId,
        full_name: form.full_name.trim(),
        title: form.title.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
      },
      {
        onSuccess: () => {
          setForm(EMPTY);
          setAdding(false);
          showSuccess("Dodano kontakt.");
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać kontaktu.")),
      },
    );
  };

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Kontakty w firmie</h2>
        {canEdit && !adding && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            Dodaj kontakt
          </Button>
        )}
      </div>
      {adding && (
        <div className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-2">
          <Input
            aria-label="Imię i nazwisko"
            placeholder="Imię i nazwisko"
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
          />
          <Input
            aria-label="Stanowisko"
            placeholder="Stanowisko"
            value={form.title}
            onChange={(event) => setForm({ ...form, title: event.target.value })}
          />
          <Input
            aria-label="E-mail"
            placeholder="E-mail"
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
          />
          <Input
            aria-label="Telefon"
            placeholder="Telefon"
            value={form.phone}
            onChange={(event) => setForm({ ...form, phone: event.target.value })}
          />
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button size="sm" variant="outline" onClick={() => setAdding(false)}>
              Anuluj
            </Button>
            <Button size="sm" onClick={save} loading={create.isPending}>
              Zapisz kontakt
            </Button>
          </div>
        </div>
      )}
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie kontaktów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void contacts.refetch()} />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze kontaktów w tej firmie.</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((contact) => (
            <li key={contact.id} className="flex flex-wrap items-start justify-between gap-x-4 py-2 text-sm">
              <div>
                <p className="font-medium text-foreground">{contact.full_name}</p>
                {contact.title && <p className="text-xs text-muted-foreground">{contact.title}</p>}
              </div>
              <div className="flex flex-wrap gap-x-3 text-xs">
                {contact.email && (
                  <a className="text-primary hover:underline" href={`mailto:${contact.email}`}>
                    {contact.email}
                  </a>
                )}
                {(contact.phone || contact.mobile_phone) && (
                  <a
                    className="text-primary hover:underline"
                    href={`tel:${contact.phone ?? contact.mobile_phone}`}
                  >
                    {contact.phone ?? contact.mobile_phone}
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
