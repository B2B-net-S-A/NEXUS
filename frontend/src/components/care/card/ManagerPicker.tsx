"use client";

import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { careKeys } from "@/lib/api/care";
import { useApplyManagers, useClientStructureProposals } from "@/lib/api/structure-proposals";

const NONE = "none";
const NEW = "new";

interface ManagerPickerProps {
  contractId: number;
  clientId: number;
}

/**
 * „Wskaż menedżera” w karcie konsultanta (makieta R2, „Kontrakt →
 * Szczegóły”): osoba klienta albo nowa osoba, zapis prosto na kontrakt —
 * bez przejścia do edycji. Ta sama trasa co „Przypnij” w drzewie klienta
 * (`POST …/structure-proposals/managers`, zatwierdza DL klienta albo admin);
 * pierwsza pozycja to propozycja automatu struktury. Bez prawa zatwierdzania
 * (albo bez dostępu do struktury) — podpowiedź, gdzie menedżera wskazać.
 */
export function ManagerPicker({ contractId, clientId }: ManagerPickerProps) {
  const ids = { pick: useId(), name: useId(), position: useId() };
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const proposals = useClientStructureProposals(clientId);
  const apply = useApplyManagers(clientId);
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<string>(NONE);
  const [newName, setNewName] = useState("");
  const [newPosition, setNewPosition] = useState("");
  const [error, setError] = useState<string | null>(null);

  const data = proposals.data;
  if (!data?.can_apply_managers) {
    return (
      <span className="text-muted-foreground">
        nie wskazano{proposals.isLoading ? "" : " — wskażesz w oknie rozmowy („Menedżer u klienta”)"}
      </span>
    );
  }
  const proposal = data.managers.find((row) => row.contract_id === contractId)?.proposal?.contact ?? null;
  const people = data.people.filter((person) => person.id !== proposal?.id);

  const save = () => {
    setError(null);
    const item =
      choice === NEW
        ? { contract_id: contractId, new_person_name: newName.trim(), new_person_position: newPosition.trim() || null }
        : { contract_id: contractId, contact_id: Number(choice) };
    apply.mutate([item], {
      onSuccess: (result) => {
        if (result.conflicts.some((row) => row.contract_id === contractId)) {
          showToast("Ktoś w międzyczasie wpisał menedżera — karta pokazuje go teraz.", "info");
        } else {
          showToast("Menedżer zapisany na kontrakcie.", "success");
        }
        setOpen(false);
        void queryClient.invalidateQueries({ queryKey: careKeys.card(contractId) });
        void queryClient.invalidateQueries({ queryKey: careKeys.clientState(contractId) });
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać menedżera.")),
    });
  };
  const ready = choice === NEW ? newName.trim().length >= 2 : choice !== NONE;

  if (!open) {
    return (
      <span>
        <span className="text-muted-foreground">nie wskazano</span>{" "}
        <Button size="sm" variant="ghost" className="h-6 px-1.5 text-xs" onClick={() => setOpen(true)}>
          Wskaż menedżera
        </Button>
      </span>
    );
  }
  return (
    <div className="mt-1 space-y-1.5" role="group" aria-label="Wskaż menedżera">
      <Select value={choice} onValueChange={setChoice}>
        <SelectTrigger id={ids.pick} aria-label="Menedżer u klienta" className="h-8">
          <SelectValue placeholder="Wybierz osobę klienta…" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Wybierz osobę klienta…</SelectItem>
          {proposal ? (
            <SelectItem value={String(proposal.id)}>
              Propozycja: {proposal.name}
              {proposal.position ? ` · ${proposal.position}` : ""}
            </SelectItem>
          ) : null}
          {people.map((person) => (
            <SelectItem key={person.id} value={String(person.id)}>
              {person.name}
              {person.position ? ` · ${person.position}` : ""}
            </SelectItem>
          ))}
          <SelectItem value={NEW}>Nowa osoba…</SelectItem>
        </SelectContent>
      </Select>
      {choice === NEW ? (
        <div className="grid gap-1.5 sm:grid-cols-2">
          <Input
            id={ids.name}
            aria-label="Imię i nazwisko menedżera"
            value={newName}
            maxLength={255}
            placeholder="Imię i nazwisko"
            onChange={(event) => setNewName(event.target.value)}
          />
          <Input
            id={ids.position}
            aria-label="Stanowisko menedżera"
            value={newPosition}
            maxLength={255}
            placeholder="Stanowisko (opcjonalnie)"
            onChange={(event) => setNewPosition(event.target.value)}
          />
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex gap-1.5">
        <Button size="sm" onClick={save} loading={apply.isPending} disabled={!ready}>
          Zapisz na kontrakcie
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}
