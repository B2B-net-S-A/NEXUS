"use client";

import { useState } from "react";

import { ContractPicker } from "@/components/admin-cases/CaseFormDialog";
import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useCreateCase, type CaseArea, type CaseContractRef } from "@/lib/api/admin-cases";
import { useBoSyncCases, type BoBoard, type BoTeamId } from "@/lib/api/back-office";
import { cn } from "@/lib/utils";

import { FamilyDot } from "./CardTile";

/**
 * Etykiety, które może mieć sprawa założona przez człowieka: obszar sprawy
 * wyznacza kolumnę (`AREA_LANE` w `services/back_office/sources.py`). Reszta
 * etykiet (raporty, poczta zamówień, przedłużenia…) przychodzi z automatów.
 */
export const MANUAL_LABELS: { lane: string; area: CaseArea; family: BoTeamId; days: number }[] = [
  { lane: "help", area: "administration", family: "care", days: 5 },
  { lane: "entry", area: "onboarding", family: "care", days: 5 },
  { lane: "exit", area: "offboarding", family: "care", days: 5 },
  { lane: "annex", area: "negotiation", family: "contracts", days: 5 },
];

interface NewCaseDialogProps {
  board: Pick<BoBoard, "labels" | "me">;
  onClose: () => void;
  /** Kontrakt z karty konsultanta: formularz od razu z osobą. */
  contract?: CaseContractRef | null;
}

/** Nowa sprawa (wariant A z 19.11.2026): czego dotyczy, etykieta, konsultant, opis. */
export function NewCaseDialog({ board, onClose, contract = null }: NewCaseDialogProps) {
  const { showToast } = useToast();
  const create = useCreateCase();
  const syncCases = useBoSyncCases();
  const [title, setTitle] = useState("");
  const [lane, setLane] = useState(MANUAL_LABELS[0].lane);
  const [picked, setPicked] = useState<CaseContractRef | null>(contract);
  const [description, setDescription] = useState("");
  const [takeNow, setTakeNow] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const choice = MANUAL_LABELS.find((item) => item.lane === lane) ?? MANUAL_LABELS[0];
  const labelOf = (id: string) => board.labels.find((label) => label.id === id)?.label ?? id;

  const submit = async () => {
    if (!title.trim()) {
      setError("Napisz, czego dotyczy sprawa.");
      return;
    }
    setError(null);
    try {
      await create.mutateAsync({
        title: title.trim(),
        area: choice.area,
        priority: "P2",
        description: description.trim() || null,
        contract_id: picked?.id ?? null,
        assignee_user_id: takeNow ? board.me.user_id : null,
      });
      // Karta od razu, bez czekania na pętlę synchronizacji.
      await syncCases.mutateAsync().catch(() => undefined);
      showToast("Sprawa założona", "success");
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się założyć sprawy."));
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Nowa sprawa"
      description="Trafia do „Nowe”. Bez zaznaczenia „Biorę ją od razu” weźmie ją pierwsza wolna osoba."
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <label className="inline-flex items-center gap-2 text-sm" htmlFor="bo-new-take">
            <input
              id="bo-new-take"
              type="checkbox"
              checked={takeNow}
              onChange={(event) => setTakeNow(event.target.checked)}
            />
            Biorę ją od razu
          </label>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Anuluj
            </Button>
            <Button onClick={submit} disabled={create.isPending}>
              Załóż sprawę
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1" htmlFor="bo-new-title">
          <span className="text-sm font-medium">Czego dotyczy *</span>
          <Input
            id="bo-new-title"
            placeholder="np. Polisa OC dla konsultanta"
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <div className="space-y-1">
          <span className="text-sm font-medium">Etykieta *</span>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Etykieta">
            {MANUAL_LABELS.map((item) => (
              <button
                key={item.lane}
                type="button"
                role="radio"
                aria-checked={lane === item.lane}
                onClick={() => setLane(item.lane)}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-sm",
                  lane === item.lane
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "border-border text-foreground hover:border-primary/40",
                )}
              >
                <FamilyDot family={item.family} />
                {labelOf(item.lane)}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Raporty, faktury, zamówienia i przedłużenia trafiają do spraw same, z systemu.
          </p>
        </div>
        <div className="space-y-1">
          <span className="text-sm font-medium">Konsultant</span>
          <ContractPicker value={picked} onChange={setPicked} />
        </div>
        <label className="block space-y-1" htmlFor="bo-new-description">
          <span className="text-sm font-medium">Opis</span>
          <Textarea
            id="bo-new-description"
            rows={3}
            placeholder="Co trzeba zrobić i co już wiadomo"
            value={description}
            maxLength={5000}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <p className="text-xs text-muted-foreground">Termin: {choice.days} dni roboczych — można go zmienić w sprawie.</p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
