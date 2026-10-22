"use client";

import { useToast } from "@/components/Toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { useSetClientDefaultOwner, type CareAssignment } from "@/lib/api/care";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { peopleText } from "./cadence-format";

const NONE = "none";

type ClientEntry = CareAssignment["clients"][number];

function ClientRow({
  client,
  choices,
  canEdit,
}: {
  client: ClientEntry;
  choices: CareAssignment["owner_choices"];
  canEdit: boolean;
}) {
  const { showToast } = useToast();
  const save = useSetClientDefaultOwner(client.id);
  const current = client.default_owner ? String(client.default_owner.id) : NONE;
  const known = choices.some((choice) => String(choice.id) === current);
  return (
    <tr className={CALM_ROW}>
      <td className="px-3 py-1.5 align-middle">
        <span className="font-medium">{client.name}</span>
        <span className="ml-1.5 text-xs text-muted-foreground">{peopleText(client.consultants)}</span>
      </td>
      <td className="px-3 py-1.5 align-middle">
        {canEdit ? (
          <Select
            value={current}
            disabled={save.isPending}
            onValueChange={(next) =>
              save.mutate(next === NONE ? null : Number(next), {
                onSuccess: () => showToast("Domyślny opiekun zapisany", "success"),
                onError: (err) =>
                  showToast(apiErrorMessage(err, "Nie udało się zapisać opiekuna klienta."), "error"),
              })
            }
          >
            <SelectTrigger aria-label={`Domyślny opiekun: ${client.name}`} className="h-8 w-60">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Brak (Delivery Lead kontraktu)</SelectItem>
              {!known && client.default_owner ? (
                <SelectItem value={current}>{client.default_owner.name} (nieaktywne konto)</SelectItem>
              ) : null}
              {choices.map((choice) => (
                <SelectItem key={choice.id} value={String(choice.id)}>
                  {choice.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className={cn(!client.default_owner && "text-muted-foreground")}>
            {client.default_owner?.name ?? "brak"}
            {client.default_owner && !client.default_owner_active ? " (nieaktywne konto)" : ""}
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * „Domyślni opiekunowie klientów” — nowe kontrakty klienta dostają go same.
 * Jedyne miejsce zapisu: okno „Ustawienia przydziału” w „Zespole opiekunów”
 * (makieta P6, 22.10.2026).
 */
export function ClientDefaultOwnersTable({ data }: { data: CareAssignment }) {
  return (
    <div className="space-y-2">
      <div className="max-h-72 overflow-y-auto rounded-lg border border-border">
        <table className="w-full text-sm" aria-label="Domyślni opiekunowie klientów">
          <thead>
            <tr className={CALM_ROW}>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Domyślny opiekun</th>
            </tr>
          </thead>
          <tbody>
            {data.clients.map((client) => (
              <ClientRow
                key={client.id}
                client={client}
                choices={data.owner_choices}
                canEdit={data.can_edit_defaults}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Kontrakt bez wskazanego opiekuna dostaje domyślnego opiekuna klienta, a bez niego Delivery Leada.
        {data.can_edit_defaults
          ? ""
          : " Domyślnego opiekuna zmieniają Delivery Lead klienta, Talent Community Manager i administrator."}
      </p>
    </div>
  );
}
