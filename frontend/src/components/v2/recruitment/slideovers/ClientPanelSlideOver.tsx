"use client";

/**
 * Okno „Panel klienta” z menu „⋯” rekrutacji (`?win=client-panel`): włącznik
 * linku z CV, to, co widzi klient, i sprawy, które od niego przyszły.
 */

import { ClientPanelManage } from "@/components/v2/client-panel/ClientPanelManage";
import type { ClientPanelAdminTransport } from "@/lib/api/clientPanelAdmin";

import { RecruitmentSheet } from "./RecruitmentSheet";

export interface ClientPanelSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** Harness `/preview/*`: dane fikcyjne, zero zapytań. */
  transport?: ClientPanelAdminTransport;
}

export function ClientPanelSlideOver({
  open,
  onOpenChange,
  jobId,
  transport,
}: ClientPanelSlideOverProps) {
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Panel klienta"
      description="Link z CV dla managera klienta: co widzi, o co pyta i kiedy zagląda."
      width="wide"
      data-testid="client-panel-slideover"
    >
      <ClientPanelManage jobId={jobId} transport={transport} />
    </RecruitmentSheet>
  );
}

export default ClientPanelSlideOver;
