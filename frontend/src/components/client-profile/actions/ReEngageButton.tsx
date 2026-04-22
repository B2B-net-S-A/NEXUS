"use client";

import { Mail } from "lucide-react";
import type { HistoricalPlacementItem } from "@/types/client-profile";

interface Props {
  placement: HistoricalPlacementItem;
}

/**
 * Re-engage an ex-consultant via a pre-filled mailto: link.
 *
 * Minimal v1: no server composer, no email-template picker — just open the
 * user's default mail client with a Polish starter draft. If/when we have
 * M365 composer (`microsoft365Api.compose`) wired for non-candidate flows,
 * upgrade this to an in-app modal.
 */
export function ReEngageButton({ placement }: Props) {
  const subject = encodeURIComponent(
    `Cześć ${placement.candidate.name.split(" ")[0]} — czy jesteś aktualnie otwarty na nowy projekt?`
  );
  const body = encodeURIComponent(
    `Cześć ${placement.candidate.name.split(" ")[0]},\n\n` +
      `Kojarzę, że pracowałeś z nami przy projekcie${placement.job_title ? ` „${placement.job_title}"` : ""}. ` +
      `Mam kilka ciekawych rekrutacji, które mogą Cię zainteresować — czy jesteś obecnie otwarty na rozmowę?\n\n` +
      `Daj znać, kiedy byłby dobry moment na 10-minutowy telefon.\n\n` +
      `Pozdrawiam,\n`
  );

  // No email on candidate → nothing to do. Graceful: render disabled stub.
  // We don't have the email on the brief — use mailto: without the recipient
  // so the user picks from their mail client's contacts. Lightweight workaround
  // until we extend CandidateBrief with `email`.
  return (
    <a
      href={`mailto:?subject=${subject}&body=${body}`}
      className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/30 hover:bg-purple-100 dark:hover:bg-purple-900/50 rounded-md transition-colors"
    >
      <Mail className="w-3 h-3" />
      Re-engage
    </a>
  );
}
