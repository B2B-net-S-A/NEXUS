"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Briefcase, Building2, CalendarPlus, Contact2, Link2, Plus, UserPlus } from "lucide-react";
import type { Capability } from "@/lib/capabilities";
import { useCapabilities } from "@/hooks/useCapability";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AddCandidateModal,
  AddClientModal,
  AddContactModal,
  AddJobModal,
  AddMeetingModal,
} from "@/components/AppShell";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";

export type QuickActionModal =
  | "candidate"
  | "job"
  | "client"
  | "contact"
  | "meeting"
  | "invite_link"
  | null;

interface Props {
  externalModal?: QuickActionModal;
  onExternalModalClear?: () => void;
}

/** Każda pozycja menu ma capability z rejestru — ta sama bramka, której
 *  używają Command Palette, skróty klawiszowe i empty states (audyt F-19). */
const ACTION_CAPABILITY: Record<Exclude<QuickActionModal, null>, Capability> = {
  candidate: "candidate.create",
  job: "job.create",
  client: "client.create",
  contact: "contact.create",
  meeting: "calendar_event.create",
  invite_link: "invite_link.create",
};

const ACTION_CAPABILITIES = Object.values(ACTION_CAPABILITY);

/**
 * QuickActionsV2 — uses v2 primitives (Button + DropdownMenu) but reuses the
 * existing v1 Add*Modal implementations (they'll be redesigned in Phase 8).
 */
export function QuickActionsV2({ externalModal, onExternalModalClear }: Props) {
  const [modal, setModal] = useState<QuickActionModal>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const queryClient = useQueryClient();
  const can = useCapabilities();

  /** Fail-closed: modal otwiera się WYŁĄCZNIE gdy user ma capability. Dotyczy
   *  także wejść zewnętrznych (skróty klawiszowe, Command Palette), żeby żadna
   *  alternatywna ścieżka nie ominęła bramki. */
  const openModal = (next: QuickActionModal) => {
    if (next && !can[ACTION_CAPABILITY[next]]) return;
    setModal(next);
  };

  useEffect(() => {
    if (externalModal) {
      if (can[ACTION_CAPABILITY[externalModal]]) setModal(externalModal);
      onExternalModalClear?.();
    }
  }, [externalModal, onExternalModalClear, can]);

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
    // Aktywne listy V2 używają kluczy z sufiksem `-v2` / `calendar-events`.
    // Stare (bezsufiksowe) klucze zostawiamy — są nieszkodliwe, a niektóre
    // ekrany V1 nadal ich używają. Bez kluczy V2 świeżo dodany rekord nie
    // pojawiał się na liście bez ręcznego odświeżenia strony.
    queryClient.invalidateQueries({ queryKey: ["candidates"] });
    queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
    queryClient.invalidateQueries({ queryKey: ["clients"] });
    queryClient.invalidateQueries({ queryKey: ["clients-v2"] });
    queryClient.invalidateQueries({ queryKey: ["contacts"] });
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
    queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
    queryClient.invalidateQueries({ queryKey: ["sidebar-badges-v2"] });
  };

  // Zero uprawnień do tworzenia czegokolwiek (np. rola `user` — read-only
  // viewer) → nie renderujemy nawet triggera „Dodaj".
  if (!ACTION_CAPABILITIES.some((c) => can[c])) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="primary">
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">Dodaj</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          {can["candidate.create"] && (
            <DropdownMenuItem onSelect={() => openModal("candidate")}>
              <UserPlus className="h-4 w-4" />
              Dodaj kandydata
            </DropdownMenuItem>
          )}
          {can["job.create"] && (
            <DropdownMenuItem onSelect={() => openModal("job")}>
              <Briefcase className="h-4 w-4" />
              Dodaj ofertę
            </DropdownMenuItem>
          )}
          {can["client.create"] && (
            <DropdownMenuItem onSelect={() => openModal("client")}>
              <Building2 className="h-4 w-4" />
              Dodaj firmę
            </DropdownMenuItem>
          )}
          {can["contact.create"] && (
            <DropdownMenuItem onSelect={() => openModal("contact")}>
              <Contact2 className="h-4 w-4" />
              Dodaj osobę kontaktową
            </DropdownMenuItem>
          )}
          {can["calendar_event.create"] && (
            <DropdownMenuItem onSelect={() => openModal("meeting")}>
              <CalendarPlus className="h-4 w-4" />
              Zaplanuj spotkanie
            </DropdownMenuItem>
          )}
          {can["invite_link.create"] && (
            <DropdownMenuItem onSelect={() => openModal("invite_link")}>
              <Link2 className="h-4 w-4" />
              Wygeneruj link aplikacyjny
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {modal === "candidate" && <AddCandidateModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "job" && <AddJobModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "client" && <AddClientModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "contact" && <AddContactModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "meeting" && <AddMeetingModal onClose={() => setModal(null)} onSuccess={showToast} />}

      <GenerateInviteLinkV2
        open={modal === "invite_link"}
        onOpenChange={(v) => {
          if (!v) setModal(null);
        }}
      />

      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-[9999] px-4 py-3 rounded-md shadow-md text-sm border ${
            toast.type === "success"
              ? "bg-card text-foreground border-border"
              : "bg-destructive text-destructive-foreground border-destructive"
          }`}
          role="alert"
        >
          {toast.message}
        </div>
      )}
    </>
  );
}
