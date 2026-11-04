"use client";

import { useState, type ReactNode } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCancelProtocol,
  useConfirmProtocol,
  useCreateProtocolLink,
  type EquipmentHolderKind,
  type ProtocolKind,
} from "@/lib/api/equipment";

import { ProtocolLinkBox } from "./ProtocolLinkBox";

export interface QuickProtocol {
  id: number;
  number: string;
}

export interface CancellableProtocol extends QuickProtocol {
  kind: ProtocolKind;
  holder: { kind: EquipmentHolderKind | null };
}

/** Co się stanie po anulowaniu — zdanie w oknie z powodem. */
export function cancelEffect(protocol: CancellableProtocol): string {
  const tail = "Link do podpisu przestanie działać. Numer zostaje w rejestrze jako anulowany.";
  if (protocol.kind === "zwrot") {
    return `Sprzęt wróci do osoby jako wydany, jakby zwrotu nie było. ${tail}`;
  }
  return protocol.holder.kind === "contract"
    ? `Sprzęt z protokołu wróci na stan, a pozycje znikną z zakładki „Sprzęt” kontraktu. ${tail}`
    : `Sprzęt z protokołu wróci na stan. ${tail}`;
}

/**
 * Akcje protokołu prosto z wiersza („Wyślij link”, „Potwierdź”) — te same
 * trasy co okno protokołu. Nowy link unieważnia poprzedni (D8), więc pytamy;
 * potwierdzenie podpisu to decyzja człowieka (D4), więc też pytamy.
 * Anulowanie (decyzja 28.10.2026) pyta o powód — trafia do audytu.
 */
export function useProtocolQuickActions(): {
  sendLink: (protocol: QuickProtocol) => Promise<void>;
  confirmSigned: (protocol: QuickProtocol) => Promise<void>;
  cancelProtocol: (protocol: CancellableProtocol, onDone?: () => void) => Promise<void>;
  busy: boolean;
  dialogs: ReactNode;
} {
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const link = useCreateProtocolLink();
  const confirm = useConfirmProtocol();
  const cancel = useCancelProtocol();
  const [created, setCreated] = useState<{
    number: string;
    url: string;
    email: string | null;
  } | null>(null);

  const sendLink = async (protocol: QuickProtocol) => {
    const ok = await askConfirm({
      title: `Wysłać nowy link do ${protocol.number}?`,
      description:
        "Powstanie nowy link do potwierdzenia odbioru (14 dni, jednorazowy). Poprzedni link do tego protokołu przestanie działać.",
      confirmLabel: "Utwórz link",
    });
    if (!ok) return;
    link.mutate(protocol.id, {
      onSuccess: (data) =>
        setCreated({ number: protocol.number, url: data.url, email: data.holder_email }),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się utworzyć linku."), "error"),
    });
  };

  const confirmSigned = async (protocol: QuickProtocol) => {
    const ok = await askConfirm({
      title: `Potwierdzić podpis ${protocol.number}?`,
      description:
        "Osoba podpisała protokół. Po potwierdzeniu protokół jest zamknięty, a link przestaje działać.",
      confirmLabel: "Potwierdź podpis",
    });
    if (!ok) return;
    confirm.mutate(
      { protocolId: protocol.id },
      {
        onSuccess: () => showToast(`Protokół ${protocol.number} potwierdzony`, "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się potwierdzić podpisu."), "error"),
      },
    );
  };

  const cancelProtocol = async (protocol: CancellableProtocol, onDone?: () => void) => {
    const reason = await askReason({
      title: `Anulować protokół ${protocol.number}?`,
      description: cancelEffect(protocol),
      confirmLabel: "Anuluj protokół",
      cancelLabel: "Wróć",
      variant: "destructive",
      field: {
        label: "Powód anulowania",
        placeholder: "Np. pomyłka w osobie, ćwiczenie, sprzęt nie został wydany",
        minLength: 3,
        maxLength: 500,
      },
    });
    if (reason === null) return;
    cancel.mutate(
      { protocolId: protocol.id, reason },
      {
        onSuccess: () => {
          showToast(`Protokół ${protocol.number} anulowany`, "success");
          onDone?.();
        },
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się anulować protokołu."), "error"),
      },
    );
  };

  const dialogs = (
    <>
      {confirmDialog}
      {created ? (
        <AppModal
          open
          onOpenChange={(next) => {
            if (!next) setCreated(null);
          }}
          title={`Link do podpisu · ${created.number}`}
          footer={<Button onClick={() => setCreated(null)}>Gotowe</Button>}
        >
          <ProtocolLinkBox url={created.url} number={created.number} email={created.email} />
        </AppModal>
      ) : null}
    </>
  );

  return {
    sendLink,
    confirmSigned,
    cancelProtocol,
    busy: link.isPending || confirm.isPending || cancel.isPending,
    dialogs,
  };
}
