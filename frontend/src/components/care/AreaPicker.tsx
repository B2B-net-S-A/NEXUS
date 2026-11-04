"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ClientOrg, ContactOrgPayload, OrgPerson } from "@/lib/api/client-people";

export const NONE = "none";
const NEW_AREA = "__new__";

export function AreaPicker({
  org,
  person,
  saving,
  onSave,
}: {
  org: ClientOrg;
  person: OrgPerson;
  saving: boolean;
  onSave: (payload: ContactOrgPayload) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const value = person.area_id != null ? String(person.area_id) : NONE;
  return (
    <div className="grid gap-1.5">
      <Select
        value={adding ? NEW_AREA : value}
        disabled={saving}
        onValueChange={(next) => {
          if (next === NEW_AREA) {
            setAdding(true);
            return;
          }
          setAdding(false);
          onSave({ client_area_id: next === NONE ? null : Number(next) });
        }}
      >
        <SelectTrigger aria-label="Dział" className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Bez działu</SelectItem>
          {org.areas.map((area) => (
            <SelectItem key={area.id} value={String(area.id)}>
              {area.name}
            </SelectItem>
          ))}
          <SelectItem value={NEW_AREA}>Nowy dział…</SelectItem>
        </SelectContent>
      </Select>
      {adding ? (
        <div className="flex gap-1.5">
          <Input
            aria-label="Nazwa nowego działu"
            value={name}
            maxLength={120}
            autoFocus
            placeholder="np. Płatności"
            onChange={(event) => setName(event.target.value)}
            className="h-8"
          />
          <Button
            size="sm"
            disabled={!name.trim() || saving}
            onClick={() => {
              onSave({ new_area_name: name.trim() });
              setAdding(false);
              setName("");
            }}
          >
            Dodaj
          </Button>
        </div>
      ) : null}
      {person.department_hint ? (
        <p className="text-xs text-muted-foreground">
          W kontakcie: „{person.department_text}”.{" "}
          <button
            type="button"
            disabled={saving}
            className="text-primary hover:underline disabled:opacity-50"
            onClick={() =>
              onSave(
                person.department_hint?.area_id != null
                  ? { client_area_id: person.department_hint.area_id }
                  : { new_area_name: person.department_hint?.name ?? "" },
              )
            }
          >
            {person.department_hint.area_id != null
              ? `Przypisz: ${person.department_hint.name}`
              : `Dodaj dział „${person.department_hint.name}”`}
          </button>
        </p>
      ) : null}
    </div>
  );
}
