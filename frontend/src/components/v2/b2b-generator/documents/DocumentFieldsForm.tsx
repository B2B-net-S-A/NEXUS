"use client";

// Jeden formularz dla każdego typu dokumentu — budowany z definicji pól
// z serwera (`GET /document-types`). Nowy typ w rejestrze backendu nie wymaga
// nowego komponentu, o ile używa znanych rodzajów pól.

import { Lock } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type {
  DocumentFieldDef,
  DocumentTypeDef,
  DocumentValue,
  DocumentValues,
} from "@/lib/api/b2bDocuments";
import {
  SENSITIVE_NOTE,
  groupedFields,
  parseMoney,
} from "@/lib/b2b-documents";
import { cn } from "@/lib/utils";

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-border bg-card px-3 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring disabled:opacity-50";

export function isFemaleGender(value: DocumentValue | undefined): boolean {
  return typeof value === "string" && /^[fk]/i.test(value.trim());
}

function GenderToggle({
  id,
  label,
  value,
  onChange,
  disabled,
  invalid,
}: {
  id: string;
  label: string;
  value: DocumentValue | undefined;
  onChange: (value: string) => void;
  disabled?: boolean;
  invalid?: boolean;
}) {
  const female = isFemaleGender(value);
  const male = typeof value === "string" && value !== "" && !female;
  const option = (label: string, code: "m" | "f", pressed: boolean) => (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={() => onChange(code)}
      className={cn(
        "h-9 flex-1 px-3 text-sm transition-colors disabled:opacity-50",
        pressed
          ? "bg-primary text-primary-foreground"
          : "bg-card text-foreground hover:bg-muted",
      )}
    >
      {label}
    </button>
  );
  return (
    <div
      id={id}
      role="group"
      aria-label={label}
      className={cn(
        "flex overflow-hidden rounded-md border",
        invalid ? "border-destructive" : "border-border",
      )}
    >
      {option("Mężczyzna", "m", male)}
      {option("Kobieta", "f", female)}
    </div>
  );
}

function FieldControl({
  field,
  id,
  value,
  onChange,
  disabled,
  invalid,
  describedBy,
}: {
  field: DocumentFieldDef;
  id: string;
  value: DocumentValue | undefined;
  onChange: (value: DocumentValue) => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
}) {
  const text = typeof value === "string" || typeof value === "number" ? String(value) : "";
  const common = {
    id,
    disabled,
    "aria-invalid": invalid || undefined,
    "aria-describedby": describedBy,
    "aria-required": field.required || undefined,
    // Dane wrażliwe nie mogą trafić do autouzupełniania przeglądarki.
    autoComplete: field.sensitive ? "off" : undefined,
  };
  switch (field.kind) {
    case "textarea":
      return (
        <Textarea
          {...common}
          rows={4}
          value={text}
          onChange={(e) => onChange(e.target.value)}
          className={cn(invalid && "border-destructive")}
        />
      );
    case "date":
      return (
        <Input
          {...common}
          type="date"
          value={text.slice(0, 10)}
          onChange={(e) => onChange(e.target.value)}
          className={cn(invalid && "border-destructive")}
        />
      );
    case "money":
      return (
        <Input
          {...common}
          type="text"
          inputMode="decimal"
          placeholder="np. 150,00"
          value={text}
          onChange={(e) => onChange(e.target.value)}
          className={cn(invalid && "border-destructive")}
        />
      );
    case "email":
      return (
        <Input
          {...common}
          type="email"
          value={text}
          onChange={(e) => onChange(e.target.value)}
          className={cn(invalid && "border-destructive")}
        />
      );
    case "select":
      return (
        <select
          {...common}
          value={text}
          onChange={(e) => onChange(e.target.value)}
          className={cn(SELECT_CLASS, invalid && "border-destructive")}
        >
          <option value="">— wybierz —</option>
          {field.options.map(([optionValue, optionLabel]) => (
            <option key={optionValue} value={optionValue}>
              {optionLabel}
            </option>
          ))}
        </select>
      );
    case "gender":
      return (
        <GenderToggle
          id={id}
          label={field.label}
          value={value}
          onChange={onChange}
          disabled={disabled}
          invalid={invalid}
        />
      );
    default:
      return (
        <Input
          {...common}
          type="text"
          value={text}
          onChange={(e) => onChange(e.target.value)}
          className={cn(invalid && "border-destructive")}
        />
      );
  }
}

export interface DocumentFieldsFormProps {
  type: DocumentTypeDef;
  values: DocumentValues;
  onChange: (key: string, value: DocumentValue) => void;
  /** Klucze pól z błędem (brak wymaganego, nieczytelna kwota, 422 serwera). */
  errorKeys?: ReadonlySet<string>;
  disabled?: boolean;
  idPrefix?: string;
}

export function DocumentFieldsForm({
  type,
  values,
  onChange,
  errorKeys,
  disabled,
  idPrefix = "b2b-doc",
}: DocumentFieldsFormProps) {
  const groups = groupedFields(type, values);
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <fieldset key={group.group} className="space-y-4">
          <legend className="mb-2 text-sm font-semibold text-foreground">
            {group.label}
          </legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {group.fields.map((field) => {
              const id = `${idPrefix}-${field.key}`;
              const helpId = `${id}-help`;
              const raw = values[field.key];
              const moneyInvalid =
                field.kind === "money" &&
                typeof raw === "string" &&
                raw.trim() !== "" &&
                parseMoney(raw) === null;
              const invalid = Boolean(errorKeys?.has(field.key)) || moneyInvalid;
              const describedBy =
                field.help || field.sensitive || moneyInvalid ? helpId : undefined;
              const wide = field.kind === "textarea" || field.kind === "bool";
              if (field.kind === "bool") {
                return (
                  <div key={field.key} className="sm:col-span-2">
                    <div className="flex items-start gap-2">
                      <Checkbox
                        id={id}
                        checked={raw === true}
                        disabled={disabled}
                        aria-describedby={describedBy}
                        onCheckedChange={(checked) => onChange(field.key, checked === true)}
                      />
                      <div className="space-y-0.5">
                        <Label htmlFor={id} className="text-sm font-medium">
                          {field.label}
                        </Label>
                        {field.help ? (
                          <p id={helpId} className="text-xs text-muted-foreground">
                            {field.help}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              }
              return (
                <div
                  key={field.key}
                  className={cn("space-y-1.5", wide && "sm:col-span-2")}
                >
                  <Label htmlFor={id} className="text-sm font-medium">
                    {field.label}
                    {field.required ? (
                      <span className="ml-0.5 text-destructive" aria-hidden="true">
                        *
                      </span>
                    ) : null}
                    {field.required ? <span className="sr-only"> (wymagane)</span> : null}
                  </Label>
                  <FieldControl
                    field={field}
                    id={id}
                    value={raw}
                    onChange={(value) => onChange(field.key, value)}
                    disabled={disabled}
                    invalid={invalid}
                    describedBy={describedBy}
                  />
                  {describedBy ? (
                    <div id={helpId} className="space-y-0.5 text-xs">
                      {moneyInvalid ? (
                        <p className="text-destructive">
                          Podaj kwotę liczbą, np. 150 albo 135,50.
                        </p>
                      ) : null}
                      {field.help ? (
                        <p className="text-muted-foreground">{field.help}</p>
                      ) : null}
                      {field.sensitive ? (
                        <p className="flex items-center gap-1 text-muted-foreground">
                          <Lock className="h-3 w-3" aria-hidden="true" />
                          {SENSITIVE_NOTE}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}

/** Numery paragrafów umowy bazowej — tylko gdy wersja wzoru jest nieznana. */
export function DocumentRefsFields({
  labels,
  refs,
  onChange,
  disabled,
  idPrefix = "b2b-doc-ref",
}: {
  labels: Record<string, string>;
  refs: Record<string, string>;
  onChange: (key: string, value: string) => void;
  disabled?: boolean;
  idPrefix?: string;
}) {
  return (
    <fieldset className="space-y-3 rounded-lg border border-border p-4">
      <legend className="px-1 text-sm font-semibold text-foreground">
        Numery paragrafów umowy bazowej
      </legend>
      <p className="text-xs text-muted-foreground">
        Nie znamy wersji wzoru tej umowy (np. umowa z importu). Sprawdź numery
        w podpisanej umowie — podpowiadamy te z aktualnego wzoru.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.entries(labels).map(([key, label]) => {
          const id = `${idPrefix}-${key}`;
          return (
            <div key={key} className="space-y-1">
              <Label htmlFor={id} className="text-xs font-medium">
                {label}
              </Label>
              <Input
                id={id}
                value={refs[key] ?? ""}
                disabled={disabled}
                onChange={(e) => onChange(key, e.target.value)}
              />
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}
