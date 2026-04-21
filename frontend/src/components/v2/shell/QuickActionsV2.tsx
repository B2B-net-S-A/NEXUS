"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Briefcase, Building2, CalendarPlus, Plus, UserPlus } from "lucide-react";
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
  AddJobModal,
  AddMeetingModal,
} from "@/components/AppShell";

export type QuickActionModal = "candidate" | "job" | "client" | "meeting" | null;

interface Props {
  externalModal?: QuickActionModal;
  onExternalModalClear?: () => void;
}

/**
 * QuickActionsV2 — uses v2 primitives (Button + DropdownMenu) but reuses the
 * existing v1 Add*Modal implementations (they'll be redesigned in Phase 8).
 */
export function QuickActionsV2({ externalModal, onExternalModalClear }: Props) {
  const [modal, setModal] = useState<QuickActionModal>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (externalModal) {
      setModal(externalModal);
      onExternalModalClear?.();
    }
  }, [externalModal, onExternalModalClear]);

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
    queryClient.invalidateQueries({ queryKey: ["candidates"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["clients"] });
    queryClient.invalidateQueries({ queryKey: ["contacts"] });
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
    queryClient.invalidateQueries({ queryKey: ["sidebar-badges-v2"] });
  };

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
          <DropdownMenuItem onSelect={() => setModal("candidate")}>
            <UserPlus className="h-4 w-4" />
            Dodaj kandydata
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setModal("job")}>
            <Briefcase className="h-4 w-4" />
            Dodaj ofertę
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setModal("client")}>
            <Building2 className="h-4 w-4" />
            Dodaj firmę
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setModal("meeting")}>
            <CalendarPlus className="h-4 w-4" />
            Zaplanuj spotkanie
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {modal === "candidate" && <AddCandidateModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "job" && <AddJobModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "client" && <AddClientModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "meeting" && <AddMeetingModal onClose={() => setModal(null)} onSuccess={showToast} />}

      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-[9999] px-4 py-3 rounded-v2-m shadow-v2-xl text-sm ${
            toast.type === "success"
              ? "bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))]"
              : "bg-[hsl(var(--accent))] text-white"
          }`}
          role="alert"
        >
          {toast.message}
        </div>
      )}
    </>
  );
}
