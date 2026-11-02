"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useRemoveDecisionPerson,
  useSaveDecisionPerson,
  type DecisionFromContactField,
  type DecisionMapEntry,
  type DecisionPersonInput,
} from "@/lib/api/sales";

import { CONTACT_STATUS, DECISION_LEVELS, OUR_ROLE_LABELS } from "./decision-map-labels";
import { SalesSelect } from "./SalesSelect";

const NOTES_LIMIT = 2000;
const LEVEL_OPTIONS = DECISION_LEVELS.map((label, index) => ({
  value: String(index + 1),
  label: `${index + 1} · ${label}`,
}));
const ROLE_OPTIONS = Object.entries(OUR_ROLE_LABELS).map(([value, label]) => ({ value, label }));
const STATUS_OPTIONS = Object.entries(CONTACT_STATUS).map(([value, { label }]) => ({ value, label }));

function formFrom(entry: DecisionMapEntry | null) {
  // Pole pokazane z kontaktu nie należy do wpisu: zostaje puste, z podpowiedzią.
  const own = (field: DecisionFromContactField) =>
    entry?.from_contact?.includes(field) ? "" : (entry?.[field] ?? "");
  return {
    name: entry?.name ?? "",
    role_in_company: entry?.role_in_company ?? "",
    decision_level: entry?.decision_level ? String(entry.decision_level) : "",
    our_role: entry?.our_role ?? "",
    contact_status: entry?.contact_status ?? "not_contacted",
    last_contact_at: entry?.last_contact_at ?? "",
    phone: own("phone"),
    email: own("email"),
    linkedin_url: own("linkedin_url"),
    notes: own("notes"),
  };
}

type PersonForm = ReturnType<typeof formFrom>;

function payloadFrom(form: PersonForm): Record<keyof PersonForm, string | number | null> {
  return {
    name: form.name.trim(),
    role_in_company: form.role_in_company.trim() || null,
    decision_level: form.decision_level ? Number(form.decision_level) : null,
    our_role: form.our_role || null,
    contact_status: form.contact_status,
    last_contact_at: form.last_contact_at || null,
    phone: form.phone.trim() || null,
    email: form.email.trim() || null,
    linkedin_url: form.linkedin_url.trim() || null,
    notes: form.notes.trim() || null,
  };
}

interface DecisionPersonDialogProps {
  opportunityId: number;
  /** ``null`` = nowa osoba. */
  entry: DecisionMapEntry | null;
  onClose: () => void;
}

/**
 * Dodanie, poprawka i usunięcie osoby na mapie decyzyjnej. Poprawka wysyła
 * tylko zmienione pola: zły adres z Atlasa nie blokuje dopisania notatki.
 */
export function DecisionPersonDialog({ opportunityId, entry, onClose }: DecisionPersonDialogProps) {
  const save = useSaveDecisionPerson(opportunityId);
  const remove = useRemoveDecisionPerson(opportunityId);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [initial] = useState(() => formFrom(entry));
  const [form, setForm] = useState(initial);
  const set = (key: keyof PersonForm) => (value: string) => setForm((current) => ({ ...current, [key]: value }));

  const onSave = () => {
    if (!form.name.trim()) {
      showError("Wpisz imię i nazwisko.");
      return;
    }
    const next = payloadFrom(form);
    const before = payloadFrom(initial);
    // Serwer też to sprawdza, ale jego odpowiedź 422 ma techniczną nazwę pola.
    const linkedinScheme = form.linkedin_url.trim().match(/^([a-z][a-z0-9+.-]*):/i)?.[1]?.toLowerCase();
    if (next.linkedin_url !== before.linkedin_url && linkedinScheme && !["http", "https"].includes(linkedinScheme)) {
      showError("Adres LinkedIn musi zaczynać się od http:// albo https://.");
      return;
    }
    const email = form.email.trim();
    if (next.email !== before.email && email && (!email.includes("@") || email.startsWith("@") || email.endsWith("@"))) {
      showError("Adres e-mail wygląda na niepełny.");
      return;
    }
    const changed = entry
      ? Object.fromEntries(
          (Object.keys(next) as (keyof PersonForm)[])
            .filter((key) => next[key] !== before[key])
            .map((key) => [key, next[key]]),
        )
      : next;
    if (Object.keys(changed).length === 0) {
      onClose();
      return;
    }
    save.mutate(
      { key: entry?.key ?? null, payload: changed as DecisionPersonInput },
      {
        onSuccess: () => {
          showSuccess(entry ? "Zapisano zmiany na mapie." : "Dodano osobę na mapę.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać osoby na mapie.")),
      },
    );
  };

  const onRemove = async () => {
    if (!entry) return;
    const ok = await askConfirm({
      title: "Usunąć osobę z mapy?",
      description: `${entry.name} zniknie z mapy tej szansy. Kontakt w Sprzedaży zostaje, a zmiana trafi do historii szansy.`,
      confirmLabel: "Usuń z mapy",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(entry.key, {
      onSuccess: () => {
        showSuccess("Usunięto osobę z mapy.");
        onClose();
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się usunąć osoby z mapy.")),
    });
  };

  const hint = (field: DecisionFromContactField) =>
    entry?.from_contact?.includes(field) && entry[field] ? `Z kontaktu: ${entry[field]}` : undefined;

  const text = (
    key: keyof PersonForm,
    label: string,
    options: { type?: string; maxLength?: number; wide?: boolean; placeholder?: string } = {},
  ) => (
    <div className={`space-y-1 ${options.wide ? "sm:col-span-2" : ""}`}>
      <Label htmlFor={`decision-person-${key}`}>{label}</Label>
      <Input
        id={`decision-person-${key}`}
        type={options.type}
        maxLength={options.maxLength}
        placeholder={options.placeholder}
        value={form[key]}
        onChange={(event) => set(key)(event.target.value)}
      />
    </div>
  );

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={entry ? "Popraw osobę na mapie" : "Dodaj osobę na mapę"}
      size="lg"
      footer={
        <>
          {entry && (
            <Button variant="quiet" className="mr-auto" loading={remove.isPending} onClick={() => void onRemove()}>
              Usuń z mapy
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={onSave} loading={save.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {text("name", "Imię i nazwisko", { maxLength: 255 })}
        {text("role_in_company", "Stanowisko", { maxLength: 255 })}
        <div className="space-y-1">
          <Label htmlFor="decision-person-level">Poziom decyzji</Label>
          <SalesSelect
            id="decision-person-level"
            value={form.decision_level}
            onValueChange={set("decision_level")}
            options={LEVEL_OPTIONS}
            anyLabel="Bez poziomu"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="decision-person-role">Nasza rola</Label>
          <SalesSelect
            id="decision-person-role"
            value={form.our_role}
            onValueChange={set("our_role")}
            options={ROLE_OPTIONS}
            anyLabel="Bez roli"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="decision-person-status">Status kontaktu</Label>
          <SalesSelect
            id="decision-person-status"
            value={form.contact_status}
            onValueChange={set("contact_status")}
            options={STATUS_OPTIONS}
          />
        </div>
        {text("last_contact_at", "Ostatni kontakt", { type: "date" })}
        {text("phone", "Telefon", { maxLength: 50, placeholder: hint("phone") })}
        {text("email", "E-mail", { type: "email", maxLength: 320, placeholder: hint("email") })}
        {text("linkedin_url", "LinkedIn", { maxLength: 512, wide: true, placeholder: hint("linkedin_url") })}
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="decision-person-notes">Notatka</Label>
          <Textarea
            id="decision-person-notes"
            rows={2}
            className="min-h-14"
            maxLength={NOTES_LIMIT}
            placeholder={hint("notes")}
            value={form.notes}
            onChange={(event) => set("notes")(event.target.value)}
          />
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Telefon, e-mail, LinkedIn i notatka uzupełnią też puste pola kontaktu, niczego w nim nie nadpiszą.
      </p>
      {confirmDialog}
    </AppModal>
  );
}
