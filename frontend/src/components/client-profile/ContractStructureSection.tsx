"use client";

/**
 * „Struktura umów" — sekcja profilu Centrum e-Zdrowia nad „Obecnymi
 * konsultantami" (ticket 09.2026). Dwa poziomy: umowa ramowa = część
 * (cz. I/II/IV/V/VI) → 0..N umów wykonawczych. Tu Delivery Lead dodaje
 * i edytuje umowy wykonawcze (numer, notatka, status) i przypisuje
 * konsultantów sprzed wdrożenia struktury — bez opuszczania profilu, bo
 * select w formularzach zamówień oferuje wyłącznie umowy, które tu już
 * istnieją.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileStack, Pencil, Plus } from "lucide-react";

import { AddExecutiveContractModal } from "@/components/client-profile/AddExecutiveContractModal";
import {
  ExecutiveContractReviewPanel,
  clientProfileQueryKey,
} from "@/components/client-profile/ExecutiveContractReviewPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  contractStructureQueryKey,
  executiveContractReviewQueryKey,
  frameworkPartHeader,
  useContractStructure,
  type ExecutiveContractRead,
  type FrameworkPartRead,
} from "@/lib/api/executiveContracts";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

interface Props {
  clientId: number;
}

export function ContractStructureSection({ clientId }: Props) {
  const structure = useContractStructure(clientId);
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const [addFor, setAddFor] = useState<number | null>(null);
  const [editing, setEditing] = useState<ExecutiveContractRead | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const frameworks = structure.data?.framework_contracts ?? [];

  // Struktura (chipy + selecty), przegląd (grupy w selekcie) i profil
  // (badge w tabeli) czytają ten sam fakt — wszystkie trzy do odświeżenia,
  // po dodaniu i po edycji tak samo (zmiana statusu zdejmuje umowę z selectów).
  const invalidateAll = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: contractStructureQueryKey(clientId) }),
      queryClient.invalidateQueries({
        queryKey: executiveContractReviewQueryKey(clientId),
      }),
      queryClient.invalidateQueries({ queryKey: clientProfileQueryKey(clientId) }),
    ]);

  const onCreated = async (created: ExecutiveContractRead) => {
    showSuccess(`Dodano umowę wykonawczą ${created.number}`);
    await invalidateAll();
  };

  const onUpdated = async (updated: ExecutiveContractRead) => {
    showSuccess(`Zapisano umowę wykonawczą ${updated.number}`);
    await invalidateAll();
  };

  return (
    <section
      className="space-y-4 rounded-xl border border-border bg-card p-4"
      aria-labelledby="contract-structure-heading"
    >
      <div className="flex items-center gap-2">
        <FileStack className="h-4 w-4 text-primary" aria-hidden="true" />
        <h3
          id="contract-structure-heading"
          className="text-sm font-semibold text-foreground"
        >
          Struktura umów
        </h3>
        {structure.isSuccess ? (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
            {countPl(frameworks.length, "część", "części", "części")}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        Umowa ramowa (część) → umowy wykonawcze. Konsultant, zamówienie i karta
        MD są przypisywane do konkretnej umowy wykonawczej.
      </p>

      {structure.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie struktury umów…</p>
      ) : structure.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać struktury umów. Bez niej nie da się dodać umowy wykonawczej ani przypisać konsultanta."
          onRetry={() => structure.refetch()}
        />
      ) : frameworks.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-3 text-sm text-muted-foreground">
          Ten klient nie ma umowy ramowej z częścią — struktura umów jest pusta.
        </p>
      ) : (
        <ul className="space-y-3">
          {frameworks.map((fc) => (
            <FrameworkRow
              key={fc.id}
              framework={fc}
              onAdd={() => {
                setAddFor(fc.id);
                setEditing(null);
                setModalOpen(true);
              }}
              onEdit={(ec) => {
                setAddFor(ec.framework_contract_id);
                setEditing(ec);
                setModalOpen(true);
              }}
            />
          ))}
        </ul>
      )}

      <ExecutiveContractReviewPanel clientId={clientId} />

      <AddExecutiveContractModal
        clientId={clientId}
        open={modalOpen}
        onOpenChange={setModalOpen}
        frameworks={frameworks}
        initialFrameworkId={addFor}
        editing={editing}
        onCreated={onCreated}
        onUpdated={onUpdated}
      />
    </section>
  );
}

function FrameworkRow({
  framework,
  onAdd,
  onEdit,
}: {
  framework: FrameworkPartRead;
  onAdd: () => void;
  onEdit: (contract: ExecutiveContractRead) => void;
}) {
  const header = frameworkPartHeader(framework);
  return (
    <li className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{header}</span>
          <span className="text-xs text-muted-foreground">{framework.name}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onAdd}
          aria-label={`Dodaj umowę wykonawczą: ${header}`}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj umowę wykonawczą
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {framework.executive_contracts.length === 0 ? (
          <span className="text-xs italic text-muted-foreground">
            brak umowy wykonawczej
          </span>
        ) : (
          framework.executive_contracts.map((ec) => (
            <span
              key={ec.id}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
                ec.status === "active"
                  ? "border-primary/30 bg-primary/10 text-foreground"
                  : "border-border bg-muted text-muted-foreground",
              )}
            >
              <span className="font-medium">{ec.number}</span>
              <span
                className={cn(
                  "rounded px-1 py-0.5 text-[10px] font-semibold uppercase",
                  ec.status === "active"
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {ec.status === "active" ? "Aktywna" : "Zakończona"}
              </span>
              <span className="text-muted-foreground">
                {countPl(
                  ec.consultants_count,
                  "konsultant",
                  "konsultantów",
                  "konsultantów",
                )}
              </span>
              {/* Edycja (numer, notatka, status) — kryterium „edytowalna".
                  Ikona z `aria-label`: chip jest gęsty, tekst „Edytuj" przy
                  każdej umowie rozciągałby wiersz. */}
              <button
                type="button"
                onClick={() => onEdit(ec)}
                aria-label={`Edytuj umowę wykonawczą: ${ec.number}`}
                title="Edytuj umowę wykonawczą"
                className="-mr-1 rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Pencil className="h-3 w-3" aria-hidden="true" />
              </button>
            </span>
          ))
        )}
      </div>
    </li>
  );
}
