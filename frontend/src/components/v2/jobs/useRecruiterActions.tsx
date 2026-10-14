"use client";

import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { apiErrorMessage } from "@/lib/api-error";
import { decideProposal } from "@/lib/api/requestAllocation";
import {
  addRecruiter,
  removeRecruiter,
  type RecruiterLike,
} from "@/lib/job-team";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { useAuthStore } from "@/store/auth";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";

/** Osoba wybrana z listy — z katalogu albo z obłożenia pulpitu. */
export interface PickedPerson {
  id: number;
  name: string;
}

export interface RecruiterActions {
  /** Klucz trwającego zapisu (`"add"`, `"remove:12"`…); `null` = nic nie trwa. */
  pending: string | null;
  /** Okno potwierdzenia zdjęcia jest otwarte. */
  confirming: boolean;
  /** Okno potwierdzenia — wołający renderuje je w swoim drzewie. */
  confirmDialog: ReactNode;
  run: (
    key: string,
    action: () => Promise<unknown>,
    messages: { done: string; failed: string },
  ) => Promise<void>;
  remove: (person: RecruiterLike) => Promise<void>;
  decide: (person: RecruiterLike, decision: "accept" | "reject") => Promise<void>;
  /** „Zmień” przy propozycji automatu — wskazana osoba pracuje zamiast niej. */
  replaceProposal: (person: RecruiterLike, user: PickedPerson) => Promise<void>;
  add: (user: PickedPerson, options: { hasWorkingOwner: boolean }) => Promise<void>;
}

/**
 * Zapisy obsady jednej rekrutacji — wspólne dla panelu „Zespół”
 * (`JobOwnershipPanel`) i kolumny „Rekruter” listy (`RecruiterCellEditor`),
 * żeby reguły tras i komunikaty miały jedną kopię.
 *
 * `canStaff` (rola przydzielająca) wybiera trasę: przydzielający zdejmuje
 * osobę z pulpitu i ustawia pierwszego rekrutera, pozostali redaktorzy
 * dopisują i zdejmują tylko współpracowników (`lib/job-team.ts`).
 *
 * Każdy zapis kończy się odświeżeniem obsady — także nieudany: 409 znaczy,
 * że ktoś zmienił ją w międzyczasie i ekran pokazuje nieaktualny stan.
 */
export function useRecruiterActions({
  jobId,
  canStaff,
}: {
  jobId: number;
  canStaff: boolean;
}): RecruiterActions {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const meId = useAuthStore((s) => s.user?.id ?? null);
  const [pending, setPending] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const run: RecruiterActions["run"] = async (key, action, messages) => {
    if (pending != null) return;
    setPending(key);
    try {
      await action();
      toast.showSuccess(messages.done);
    } catch (err) {
      toast.showError(apiErrorMessage(err, messages.failed));
    } finally {
      invalidateJobTeam(queryClient, jobId);
      setPending(null);
    }
  };

  const remove: RecruiterActions["remove"] = async (person) => {
    if (pending != null) return;
    const self = person.user_id === meId;
    setConfirming(true);
    let confirmed = false;
    try {
      confirmed = await askConfirm({
        title: self
          ? "Zdjąć siebie z tej rekrutacji?"
          : `Zdjąć ${person.name} z tej rekrutacji?`,
        description: self
          ? "Przestaniesz być rekruterem tej rekrutacji."
          : `${person.name} przestanie być rekruterem tej rekrutacji.`,
        confirmLabel: "Zdejmij",
      });
    } finally {
      setConfirming(false);
    }
    if (!confirmed) return;
    await run(
      `remove:${person.user_id}`,
      () => removeRecruiter(jobId, person, { canStaff }),
      {
        done: self
          ? "Nie jesteś już rekruterem tej rekrutacji."
          : `${person.name}: zdjęto z rekrutacji.`,
        failed: "Nie udało się zdjąć osoby z rekrutacji.",
      },
    );
  };

  const decide: RecruiterActions["decide"] = (person, decision) =>
    run(
      `${decision}:${person.user_id}`,
      () => decideProposal(jobId, person.user_id, { decision }),
      decision === "accept"
        ? {
            done: `${person.name} pracuje nad tą rekrutacją.`,
            failed: "Nie udało się zaakceptować propozycji.",
          }
        : {
            done: "Propozycja automatu odrzucona.",
            failed: "Nie udało się odrzucić propozycji.",
          },
    );

  const replaceProposal: RecruiterActions["replaceProposal"] = (person, user) =>
    run(
      `replace:${person.user_id}`,
      () =>
        decideProposal(jobId, person.user_id, {
          decision: "replace",
          replacement_user_id: user.id,
        }),
      {
        done: `${user.name} pracuje nad tą rekrutacją zamiast propozycji automatu.`,
        failed: "Nie udało się zmienić propozycji.",
      },
    );

  const add: RecruiterActions["add"] = (user, { hasWorkingOwner }) =>
    run(
      "add",
      () => addRecruiter(jobId, user.id, { hasWorkingOwner, canStaff }),
      {
        done: `${user.name}: dodano do rekrutacji.`,
        failed: "Nie udało się dodać osoby do rekrutacji.",
      },
    );

  return {
    pending,
    confirming,
    confirmDialog,
    run,
    remove,
    decide,
    replaceProposal,
    add,
  };
}
