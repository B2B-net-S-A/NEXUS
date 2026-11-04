"use client";

import { useId, useMemo, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type {
  Audience,
  AudienceGroup,
  AudienceOptions,
  AnnouncementForm,
} from "@/lib/api/care-announcements";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { cn } from "@/lib/utils";

import { GROUP_LABELS } from "./announcement-format";

const GROUPS: AudienceGroup[] = ["all", "client", "owner", "form", "ending", "selected"];
const FORMS: AnnouncementForm[] = ["b2b", "uop", "zlecenie"];
export const ENDING_DAYS_DEFAULT = 30;

interface PickItem {
  id: number;
  label: string;
  hint?: string;
}

interface PickListProps {
  label: string;
  items: PickItem[];
  selected: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
}

/** Lista z szukaniem i polami wyboru (klienci, opiekunowie, osoby). */
function PickList({ label, items, selected, onChange, disabled }: PickListProps) {
  const [query, setQuery] = useState("");
  const inputId = useId();
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? items.filter((item) => item.label.toLowerCase().includes(needle)) : items;
  }, [items, query]);
  const toggle = (id: number, on: boolean) =>
    onChange(on ? [...selected, id] : selected.filter((value) => value !== id));
  return (
    <div className="space-y-1.5 rounded-md border border-border p-2">
      <Input
        id={inputId}
        aria-label={`Szukaj: ${label}`}
        placeholder="Szukaj…"
        value={query}
        disabled={disabled}
        onChange={(event) => setQuery(event.target.value)}
        className="h-8"
      />
      <ul aria-label={label} className="max-h-44 space-y-0.5 overflow-y-auto">
        {visible.map((item) => {
          const checked = selected.includes(item.id);
          return (
            <li key={item.id}>
              <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted">
                <Checkbox
                  checked={checked}
                  disabled={disabled}
                  onCheckedChange={(value) => toggle(item.id, value === true)}
                />
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
                {item.hint ? (
                  <span className="shrink-0 text-xs text-muted-foreground">{item.hint}</span>
                ) : null}
              </label>
            </li>
          );
        })}
        {visible.length === 0 ? (
          <li className="px-1.5 py-1 text-sm text-muted-foreground">Nic nie pasuje.</li>
        ) : null}
      </ul>
      {selected.length ? (
        <p className="text-xs text-muted-foreground">Wybrano: {selected.length}</p>
      ) : null}
    </div>
  );
}

interface AudiencePickerProps {
  value: Audience;
  onChange: (next: Audience) => void;
  options: AudienceOptions | undefined;
  optionsError?: boolean;
  disabled?: boolean;
}

function switchGroup(group: AudienceGroup, current: Audience): Audience {
  if (group === current.group) return current;
  if (group === "ending") return { group, ending_days: ENDING_DAYS_DEFAULT };
  return { group };
}

/** „Do kogo” (M7): jedna grupa z parametrami, liczba osób przy pozycjach. */
export function AudiencePicker({
  value,
  onChange,
  options,
  optionsError,
  disabled,
}: AudiencePickerProps) {
  const groupLabelId = useId();
  const daysId = useId();
  const formCount = (form: AnnouncementForm) =>
    options?.forms.find((entry) => entry.value === form)?.consultants;

  return (
    <div className="space-y-2">
      <div role="group" aria-labelledby={groupLabelId} className="flex flex-wrap gap-1.5">
        <span id={groupLabelId} className="sr-only">
          Grupa odbiorców
        </span>
        {GROUPS.map((group) => {
          const on = value.group === group;
          return (
            <button
              key={group}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              onClick={() => onChange(switchGroup(group, value))}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                on
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-foreground hover:bg-muted",
                disabled && "opacity-60",
              )}
            >
              {group === "all" && options ? `${GROUP_LABELS.all} · ${options.total}` : GROUP_LABELS[group]}
            </button>
          );
        })}
      </div>

      {optionsError && value.group !== "all" ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się wczytać list do wyboru. Odśwież stronę.
        </p>
      ) : null}

      {value.group === "client" && options ? (
        <PickList
          label="Klienci"
          disabled={disabled}
          items={options.clients.map((client) => ({
            id: client.id,
            label: client.name,
            hint: String(client.consultants),
          }))}
          selected={value.client_ids ?? []}
          onChange={(ids) => onChange({ group: "client", client_ids: ids })}
        />
      ) : null}

      {value.group === "owner" && options ? (
        <PickList
          label="Opiekunowie"
          disabled={disabled}
          items={options.owners.map((owner) => ({
            id: owner.id,
            label: owner.name,
            hint: String(owner.consultants),
          }))}
          selected={value.owner_user_ids ?? []}
          onChange={(ids) => onChange({ group: "owner", owner_user_ids: ids })}
        />
      ) : null}

      {value.group === "selected" && options ? (
        <PickList
          label="Konsultanci"
          disabled={disabled}
          items={options.consultants.map((person) => ({
            id: person.candidate_id,
            label: person.name,
            hint: person.client_name,
          }))}
          selected={value.candidate_ids ?? []}
          onChange={(ids) => onChange({ group: "selected", candidate_ids: ids })}
        />
      ) : null}

      {value.group === "form" ? (
        <div role="group" aria-label="Forma współpracy" className="flex flex-wrap gap-3">
          {FORMS.map((form) => {
            const checked = value.forms?.includes(form) ?? false;
            const count = formCount(form);
            return (
              <label key={form} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={checked}
                  disabled={disabled}
                  onCheckedChange={(next) => {
                    const forms = value.forms ?? [];
                    onChange({
                      group: "form",
                      forms: next === true ? [...forms, form] : forms.filter((f) => f !== form),
                    });
                  }}
                />
                {employmentTerms(form).form_short}
                {count !== undefined ? (
                  <span className="text-xs text-muted-foreground">{count}</span>
                ) : null}
              </label>
            );
          })}
        </div>
      ) : null}

      {value.group === "ending" ? (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor={daysId}>Koniec zamówienia w ciągu</label>
          <Input
            id={daysId}
            type="number"
            inputMode="numeric"
            min={1}
            max={180}
            disabled={disabled}
            value={value.ending_days ?? ""}
            onChange={(event) => {
              const days = Number.parseInt(event.target.value, 10);
              onChange({ group: "ending", ending_days: Number.isNaN(days) ? undefined : days });
            }}
            className="h-8 w-20"
          />
          <span>dni</span>
        </div>
      ) : null}
    </div>
  );
}
