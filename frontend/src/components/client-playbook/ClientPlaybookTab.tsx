"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useCapability } from "@/hooks/useCapability";

import { ClientPlaybookCard } from "./ClientPlaybookCard";
import { ClientPlaybookForm } from "./ClientPlaybookForm";

/**
 * Zakładka „Zasady współpracy" w profilu klienta: karta do odczytu, a dla
 * DL/admina edycja W MIEJSCU (D4) — ten sam `ClientPlaybookForm`, który stoi
 * w edytorze reguł CV. Formularz sam invaliduje `["client-playbook", id]`,
 * więc po zapisie karta pokazuje nową wersję bez ręcznego refetchu.
 *
 * `onEdit` zamiast `editHref`: przycisk w nagłówku karty i CTA pustego stanu
 * otwierają formularz TU, nie odsyłają do ustawień.
 */
export function ClientPlaybookTab({ clientId }: { clientId: number }) {
  const canManage = useCapability("client_playbook.manage");
  const [editing, setEditing] = useState(false);

  if (editing && canManage) {
    return (
      <div className="space-y-3" data-testid="client-playbook-editing">
        <div className="flex justify-end">
          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
            <X className="h-4 w-4" aria-hidden /> Zamknij edycję
          </Button>
        </div>
        <ClientPlaybookForm clientId={clientId} onSaved={() => setEditing(false)} />
      </div>
    );
  }

  return (
    <ClientPlaybookCard
      clientId={clientId}
      variant="full"
      onEdit={canManage ? () => setEditing(true) : undefined}
    />
  );
}
