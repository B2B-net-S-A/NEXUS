"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useCreateSalesContact, type Ref } from "@/lib/api/sales";

import { CompanyPicker } from "./CompanyPicker";

const EMPTY = {
  full_name: "",
  title: "",
  email: "",
  phone: "",
  mobile_phone: "",
  linkedin_url: "",
  notes: "",
};

const FIELDS: [keyof typeof EMPTY, string][] = [
  ["full_name", "Imię i nazwisko"],
  ["title", "Stanowisko"],
  ["email", "E-mail"],
  ["phone", "Telefon"],
  ["mobile_phone", "Komórka"],
  ["linkedin_url", "LinkedIn"],
];

interface ContactCreateDialogProps {
  onClose: () => void;
}

/** Nowy kontakt z zakładki Kontakty: firma obowiązkowa, jak w Atlasie. */
export function ContactCreateDialog({ onClose }: ContactCreateDialogProps) {
  const create = useCreateSalesContact();
  const { showError, showSuccess } = useToast();
  const [form, setForm] = useState(EMPTY);
  const [company, setCompany] = useState<Ref | null>(null);

  const save = () => {
    if (!form.full_name.trim()) {
      showError("Podaj imię i nazwisko.");
      return;
    }
    if (!company) {
      showError("Wybierz firmę z kartoteki sprzedaży.");
      return;
    }
    create.mutate(
      {
        company_id: company.id,
        full_name: form.full_name.trim(),
        title: form.title.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        mobile_phone: form.mobile_phone.trim() || null,
        linkedin_url: form.linkedin_url.trim() || null,
        notes: form.notes.trim() || null,
      },
      {
        onSuccess: () => {
          showSuccess("Dodano kontakt.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać kontaktu.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Nowy kontakt"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={save} loading={create.isPending}>
            Dodaj kontakt
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-new-contact-company">Firma</Label>
          <CompanyPicker id="sales-new-contact-company" value={company} onChange={setCompany} />
        </div>
        {FIELDS.map(([key, label]) => (
          <div key={key} className="space-y-1">
            <Label htmlFor={`sales-new-contact-${key}`}>{label}</Label>
            <Input
              id={`sales-new-contact-${key}`}
              value={form[key]}
              onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))}
            />
          </div>
        ))}
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-new-contact-notes">Notatka</Label>
          <Textarea
            id="sales-new-contact-notes"
            rows={2}
            value={form.notes}
            onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
          />
        </div>
      </div>
    </AppModal>
  );
}
