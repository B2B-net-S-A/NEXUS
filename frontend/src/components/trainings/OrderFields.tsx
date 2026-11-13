"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { OrderInput } from "@/lib/api/trainings";

import { DELIVERABLE_LABELS, mandatoryRoleLabel, type DeliverableDraft } from "./training-model";

function numberOrNull(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

interface DeliverablesFieldsProps {
  value: DeliverableDraft[];
  onChange: (next: DeliverableDraft[]) => void;
  disabled?: boolean;
}

/** Zał. 1 pkt 4: co trener przekaże, w jakim formacie i ile dni po szkoleniu. */
export function DeliverablesFields({ value, onChange, disabled }: DeliverablesFieldsProps) {
  const patch = (index: number, change: Partial<DeliverableDraft>) =>
    onChange(value.map((item, i) => (i === index ? { ...item, ...change } : item)));
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="mb-1 text-sm font-medium text-foreground">
        Pliki do przekazania (Zał. 1 pkt 4)
      </legend>
      {value.map((item, index) => {
        const id = `deliverable-${item.key}`;
        return (
          <div
            key={item.key}
            data-testid={id}
            className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_7rem_auto] md:items-center"
          >
            <label htmlFor={`${id}-check`} className="flex items-center gap-2 text-sm">
              <Checkbox
                id={`${id}-check`}
                checked={item.checked}
                onCheckedChange={(checked) => patch(index, { checked: checked === true })}
              />
              {item.key === "other" ? "Inne pliki" : DELIVERABLE_LABELS[item.key]}
            </label>
            {item.key === "other" && item.checked ? (
              <div className="grid gap-2 md:grid-cols-2">
                <Input
                  aria-label="Nazwa innych plików"
                  placeholder="Nazwa, np. ćwiczenia z kluczem"
                  value={item.label}
                  maxLength={200}
                  onChange={(event) => patch(index, { label: event.target.value })}
                />
                <Input
                  aria-label="Format innych plików"
                  placeholder="Format"
                  value={item.format}
                  maxLength={200}
                  onChange={(event) => patch(index, { format: event.target.value })}
                />
              </div>
            ) : (
              <Input
                aria-label={`Format: ${DELIVERABLE_LABELS[item.key]}`}
                value={item.format}
                maxLength={200}
                disabled={!item.checked}
                onChange={(event) => patch(index, { format: event.target.value })}
              />
            )}
            <div className="flex items-center gap-1.5">
              <Input
                aria-label={`Termin w dniach po szkoleniu: ${DELIVERABLE_LABELS[item.key]}`}
                type="number"
                min={0}
                max={60}
                className="w-16"
                value={item.due_days ?? ""}
                disabled={!item.checked}
                onChange={(event) => patch(index, { due_days: numberOrNull(event.target.value) })}
              />
              <span className="text-xs text-muted-foreground">dni po</span>
            </div>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Checkbox
                aria-label={`Wymagane: ${DELIVERABLE_LABELS[item.key]}`}
                checked={item.required}
                disabled={!item.checked}
                onCheckedChange={(checked) => patch(index, { required: checked === true })}
              />
              wymagane do faktury
            </label>
          </div>
        );
      })}
    </fieldset>
  );
}

interface OrderFieldsProps {
  value: OrderInput;
  onChange: (next: OrderInput) => void;
  deliverables: DeliverableDraft[];
  onDeliverablesChange: (next: DeliverableDraft[]) => void;
  disabled?: boolean;
  /** Szkolenie pracownika nie ma umowy, więc nie ma też Zał. 1 ani wyceny. */
  employee?: boolean;
  /** 0697: spotkanie Teams zakłada NEXUS, więc pola z linkiem nie ma. */
  teamsReady?: boolean;
  /** 0698: role do „Obowiązkowe dla roli” (z `/api/trainings/me`). */
  roles?: readonly string[];
}

interface MeetingOptionsProps {
  value: OrderInput;
  set: <K extends keyof OrderInput>(key: K, next: OrderInput[K]) => void;
  roles: readonly string[];
  disabled?: boolean;
}

/** 0698: próba techniczna z prowadzącym i role, dla których szkolenie jest obowiązkowe. */
function MeetingOptions({ value, set, roles, disabled }: MeetingOptionsProps) {
  const chosen = value.mandatory_roles ?? [];
  const toggle = (role: string, on: boolean) =>
    set("mandatory_roles", on ? [...chosen, role] : chosen.filter((item) => item !== role));
  return (
    <div className="grid items-start gap-3 md:grid-cols-2">
      <label
        htmlFor="order-rehearsal"
        className="flex items-start gap-2 rounded-md border border-border p-3 text-sm"
      >
        <Checkbox
          id="order-rehearsal"
          checked={value.rehearsal === true}
          disabled={disabled}
          onCheckedChange={(checked) => set("rehearsal", checked === true)}
        />
        <span>
          <span className="font-medium text-foreground">Próba techniczna 2 dni robocze wcześniej</span>
          <span className="block text-xs text-muted-foreground">
            15 minut z prowadzącym o godzinie szkolenia: dźwięk, kamera, udostępnianie ekranu. Bez
            nagrywania, link w panelu trenera.
          </span>
        </span>
      </label>
      {roles.length > 0 ? (
        <fieldset className="rounded-md border border-border p-3" disabled={disabled}>
          <legend className="px-1 text-sm font-medium text-foreground">Obowiązkowe dla roli</legend>
          <p className="mb-2 text-xs text-muted-foreground">
            Każda aktywna osoba w roli zostanie zapisana i dostanie zaproszenie, bez klikania „Zapisz
            się”. Wypisać się sama nie może.
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {roles.map((role) => (
              <label key={role} className="flex items-center gap-1.5 text-sm">
                <Checkbox
                  checked={chosen.includes(role)}
                  onCheckedChange={(checked) => toggle(role, checked === true)}
                />
                {mandatoryRoleLabel(role)}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
    </div>
  );
}

/** Pola zamówienia (szkic Zał. 1) — te same przy zakładaniu i przy edycji. */
export function OrderFields({
  value,
  onChange,
  deliverables,
  onDeliverablesChange,
  disabled,
  employee = false,
  teamsReady = false,
  roles = [],
}: OrderFieldsProps) {
  const set = <K extends keyof OrderInput>(key: K, next: OrderInput[K]) =>
    onChange({ ...value, [key]: next });
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2">
        <FormField label="Nazwa szkolenia" htmlFor="order-title" required>
          <Input
            id="order-title"
            value={value.title}
            maxLength={200}
            disabled={disabled}
            onChange={(event) => set("title", event.target.value)}
          />
        </FormField>
        <FormField label="Temat" htmlFor="order-topic">
          <Input
            id="order-topic"
            value={value.topic}
            maxLength={200}
            disabled={disabled}
            onChange={(event) => set("topic", event.target.value)}
          />
        </FormField>
      </div>
      <FormField label="Opis dla uczestników" htmlFor="order-description">
        <Textarea
          id="order-description"
          rows={3}
          value={value.description}
          maxLength={5000}
          disabled={disabled}
          onChange={(event) => set("description", event.target.value)}
        />
      </FormField>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormField label="Data szkolenia" htmlFor="order-date">
          <Input
            id="order-date"
            type="date"
            value={value.session_date ?? ""}
            disabled={disabled}
            onChange={(event) => set("session_date", event.target.value || null)}
          />
        </FormField>
        <FormField label="Od (GG:MM)" htmlFor="order-from">
          <Input
            id="order-from"
            type="time"
            value={value.time_from}
            disabled={disabled}
            onChange={(event) => set("time_from", event.target.value)}
          />
        </FormField>
        <FormField label="Do (GG:MM)" htmlFor="order-to">
          <Input
            id="order-to"
            type="time"
            value={value.time_to}
            disabled={disabled}
            onChange={(event) => set("time_to", event.target.value)}
          />
        </FormField>
        <FormField label="Czas (minuty)" htmlFor="order-duration">
          <Input
            id="order-duration"
            type="number"
            min={15}
            max={2400}
            value={value.duration_minutes ?? ""}
            disabled={disabled}
            onChange={(event) => set("duration_minutes", numberOrNull(event.target.value))}
          />
        </FormField>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormField label="Platforma" htmlFor="order-platform">
          <Input
            id="order-platform"
            value={value.platform}
            maxLength={200}
            disabled={disabled}
            onChange={(event) => set("platform", event.target.value)}
          />
        </FormField>
        {teamsReady ? (
          <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground lg:col-span-2">
            Spotkanie Teams z nagrywaniem założy NEXUS, gdy szkolenie będzie gotowe (po wysłaniu albo po
            podpisie umowy). Zapisani dostaną zaproszenie do kalendarza.
          </div>
        ) : (
          <FormField
            label="Link do spotkania"
            htmlFor="order-join"
            description="Widzą go tylko zapisani."
            className="lg:col-span-2"
          >
            <Input
              id="order-join"
              type="url"
              placeholder="https://teams.microsoft.com/…"
              value={value.join_url}
              maxLength={1000}
              disabled={disabled}
              onChange={(event) => set("join_url", event.target.value)}
            />
          </FormField>
        )}
        <FormField label="Liczba uczestników" htmlFor="order-participants">
          <Input
            id="order-participants"
            type="number"
            min={1}
            value={value.expected_participants ?? ""}
            disabled={disabled}
            onChange={(event) => set("expected_participants", numberOrNull(event.target.value))}
          />
        </FormField>
        <FormField
          label="Limit miejsc"
          htmlFor="order-seats"
          description="Puste = bez limitu. Po zapełnieniu zapis się zamyka."
        >
          <Input
            id="order-seats"
            type="number"
            min={1}
            value={value.seat_limit ?? ""}
            disabled={disabled}
            onChange={(event) => set("seat_limit", numberOrNull(event.target.value))}
          />
        </FormField>
      </div>
      <MeetingOptions value={value} set={set} roles={roles} disabled={disabled} />
      {employee ? null : (
        <>
          <div className="grid gap-3 md:grid-cols-[12rem_minmax(0,1fr)]">
            <FormField label="Wycena do" htmlFor="order-quote-due">
              <Input
                id="order-quote-due"
                type="date"
                value={value.quote_due_on ?? ""}
                disabled={disabled}
                onChange={(event) => set("quote_due_on", event.target.value || null)}
              />
            </FormField>
            <FormField
              label="Materiały dla uczestników (Zał. 1)"
              htmlFor="order-materials"
              description="Co uczestnicy dostaną po szkoleniu."
            >
              <Textarea
                id="order-materials"
                rows={2}
                value={value.participant_materials}
                maxLength={3000}
                disabled={disabled}
                onChange={(event) => set("participant_materials", event.target.value)}
              />
            </FormField>
          </div>
          <DeliverablesFields
            value={deliverables}
            onChange={onDeliverablesChange}
            disabled={disabled}
          />
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={value.knowledge_test}
              disabled={disabled}
              onCheckedChange={(checked) => set("knowledge_test", checked === true)}
            />
            Szkolenie kończy się testem wiedzy (bez egzaminu i certyfikatu)
          </label>
          <FormField label="Dodatkowe ustalenia (Zał. 1)" htmlFor="order-extra">
            <Textarea
              id="order-extra"
              rows={2}
              value={value.extra_terms}
              maxLength={3000}
              disabled={disabled}
              onChange={(event) => set("extra_terms", event.target.value)}
            />
          </FormField>
        </>
      )}
    </div>
  );
}
