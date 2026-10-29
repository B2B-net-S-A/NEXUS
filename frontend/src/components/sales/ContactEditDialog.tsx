"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useArchiveSalesContact,
  useLinkContactCompany,
  useUnlinkContactCompany,
  useUpdateSalesContact,
  type Ref,
  type SalesContact,
} from "@/lib/api/sales";

import { CompanyPicker } from "./CompanyPicker";

interface ContactEditDialogProps {
  contact: SalesContact;
  onClose: () => void;
}

/**
 * Edycja kontaktu sprzedaży: dane, firma główna, inne firmy (osoba bywa
 * w kilku — w Atlasie 224 takie powiązania) i archiwum, gdy odeszła.
 */
export function ContactEditDialog({ contact, onClose }: ContactEditDialogProps) {
  const update = useUpdateSalesContact(contact.id);
  const archive = useArchiveSalesContact();
  const link = useLinkContactCompany(contact.id);
  const unlink = useUnlinkContactCompany(contact.id);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [form, setForm] = useState({
    full_name: contact.full_name,
    title: contact.title ?? "",
    email: contact.email ?? "",
    phone: contact.phone ?? "",
    mobile_phone: contact.mobile_phone ?? "",
    linkedin_url: contact.linkedin_url ?? "",
    notes: contact.notes ?? "",
  });
  const [primary, setPrimary] = useState<Ref | null>(
    contact.company_id ? { id: contact.company_id, name: contact.company_name ?? "" } : null,
  );
  const [extra, setExtra] = useState<Ref | null>(null);
  const others = contact.companies.filter((link) => !link.is_primary);
  const set = (key: keyof typeof form) => (value: string) => setForm((current) => ({ ...current, [key]: value }));

  const save = () => {
    if (!form.full_name.trim()) {
      showError("Wpisz imię i nazwisko.");
      return;
    }
    update.mutate(
      {
        full_name: form.full_name.trim(),
        title: form.title.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        mobile_phone: form.mobile_phone.trim() || null,
        linkedin_url: form.linkedin_url.trim() || null,
        notes: form.notes.trim() || null,
        company_id: primary?.id ?? null,
      },
      {
        onSuccess: () => {
          showSuccess("Zapisano kontakt.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać kontaktu.")),
      },
    );
  };

  const onArchive = async () => {
    const ok = await askConfirm({
      title: "Zarchiwizować kontakt?",
      description: "Zniknie z list i wyboru przy szansach. Historia z nim zostaje.",
      confirmLabel: "Archiwizuj",
      variant: "destructive",
    });
    if (!ok) return;
    archive.mutate(contact.id, {
      onSuccess: () => {
        showSuccess("Kontakt jest w archiwum.");
        onClose();
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się zarchiwizować kontaktu.")),
    });
  };

  const fields: [keyof typeof form, string][] = [
    ["full_name", "Imię i nazwisko"],
    ["title", "Stanowisko"],
    ["email", "E-mail"],
    ["phone", "Telefon"],
    ["mobile_phone", "Komórka"],
    ["linkedin_url", "LinkedIn"],
  ];

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Edytuj kontakt"
      size="lg"
      footer={
        <>
          {!contact.archived_at && (
            <Button variant="quiet" className="mr-auto" onClick={() => void onArchive()}>
              Archiwizuj (odszedł z firmy)
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={save} loading={update.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map(([key, label]) => (
          <div key={key} className="space-y-1">
            <Label htmlFor={`sales-contact-${key}`}>{label}</Label>
            <Input id={`sales-contact-${key}`} value={form[key]} onChange={(event) => set(key)(event.target.value)} />
          </div>
        ))}
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-contact-primary">Firma główna</Label>
          <CompanyPicker id="sales-contact-primary" value={primary} onChange={setPrimary} />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="sales-contact-extra">Także w firmach</Label>
          {others.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {others.map((other) => (
                <li key={other.company_id}>
                  <Badge variant={other.is_current ? "outline" : "neutral"} size="md">
                    {other.company_name}
                    {other.title ? ` · ${other.title}` : ""}
                    {other.is_current ? "" : " · była"}
                    <button
                      type="button"
                      className="ml-1 text-muted-foreground hover:text-foreground"
                      aria-label={`Odepnij od ${other.company_name}`}
                      onClick={() =>
                        unlink.mutate(other.company_id, {
                          onError: (error) => showError(apiErrorMessage(error, "Nie udało się odpiąć firmy.")),
                        })
                      }
                    >
                      ×
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <CompanyPicker id="sales-contact-extra" value={extra} onChange={setExtra} />
            </div>
            <Button
              variant="outline"
              disabled={!extra}
              loading={link.isPending}
              onClick={() =>
                extra &&
                link.mutate(
                  { company_id: extra.id },
                  {
                    onSuccess: () => setExtra(null),
                    onError: (error) => showError(apiErrorMessage(error, "Nie udało się dopiąć firmy.")),
                  },
                )
              }
            >
              Dopnij
            </Button>
          </div>
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-contact-notes">Notatki</Label>
          <Textarea id="sales-contact-notes" rows={3} value={form.notes} onChange={(event) => set("notes")(event.target.value)} />
        </div>
      </div>
      {confirmDialog}
    </AppModal>
  );
}
