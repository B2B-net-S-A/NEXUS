"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { playbookCheatLines } from "@/components/client-profile/ClientRecruitingSheet";
import { useCapability } from "@/hooks/useCapability";
import { useClientPlaybook } from "@/lib/client-playbooks";

import { ClientPlaybookCard } from "./ClientPlaybookCard";
import { ClientPlaybookForm } from "./ClientPlaybookForm";

/**
 * Zakładka „Zasady rekrutacji” (do 19.11.2026 „Zasady współpracy”) w profilu klienta: karta do odczytu, a dla
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
    <div className="space-y-3">
      <PlaybookHighlights clientId={clientId} />
      <ClientPlaybookCard
        clientId={clientId}
        variant="full"
        onEdit={canManage ? () => setEditing(true) : undefined}
      />
    </div>
  );
}

/**
 * „Najważniejsze zasady” nad pełną kartą (makieta 19.11.2026, wariant A ekranu
 * „Współpraca” → Rekrutacje › Zasady rekrutacji): ustawione liczby i pierwsze
 * linie zasad procesu jako krótka lista — to, co rekruter ma mieć w głowie,
 * zanim przeczyta całą kartę. Ten sam skrót co ściąga przy Projektach.
 */
function PlaybookHighlights({ clientId }: { clientId: number }) {
  const playbook = useClientPlaybook(clientId);
  const lines = playbookCheatLines(playbook.data);
  if (lines.length === 0) return null;
  return (
    <section
      className="rounded-xl border border-border bg-card px-4 py-3 shadow-xs"
      aria-labelledby="playbook-highlights"
    >
      <h2 id="playbook-highlights" className="text-sm font-semibold text-foreground">
        Najważniejsze zasady
      </h2>
      <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[13px] text-foreground">
        {lines.map((line, index) => (
          <li key={`${index}-${line}`} className="break-words">
            {line}
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-xs text-muted-foreground">Pełna karta klienta poniżej.</p>
    </section>
  );
}
