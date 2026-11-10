"use client";

import Link from "next/link";
import { ChevronDown } from "lucide-react";

import { StatusDot } from "@/components/ds/StatusDot";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Meeting, MeetingOpportunityOption } from "@/lib/api/sales";

import { formatDealAmount } from "./format";

const NO_LEAD_LABEL = "Klient bez Delivery Leada: zgłoś do Heada";

function optionDetails(option: MeetingOpportunityOption): string {
  const amount = option.value === null ? null : formatDealAmount(option.value, option.currency);
  return [option.stage_name, amount].filter(Boolean).join(" · ");
}

function ClientNotice({ meeting }: { meeting: Meeting }) {
  if (meeting.delivery_lead) {
    return (
      <StatusDot
        tone="info"
        title={`${meeting.client_name} to klient NEXUSA. Temat prowadzi Delivery Lead: ${meeting.delivery_lead}.`}
      >
        Klient NEXUSA, przekaż do: {meeting.delivery_lead}
      </StatusDot>
    );
  }
  return (
    <StatusDot
      tone="warning"
      title={`${meeting.client_name} to klient NEXUSA, ale nie ma przypisanego Delivery Leada.`}
    >
      {NO_LEAD_LABEL}
    </StatusDot>
  );
}

interface MeetingDecisionCellProps {
  meeting: Meeting;
  canEdit: boolean;
  busy: boolean;
  onPin: (option: MeetingOpportunityOption) => void;
  onCreate: () => void;
  onUnpin: () => void;
}

/** Kolumna „Co dalej”: co zrobić z tym spotkaniem. */
export function MeetingDecisionCell({ meeting, canEdit, busy, onPin, onCreate, onUnpin }: MeetingDecisionCellProps) {
  const row = "flex min-h-8 items-center justify-end gap-2";
  switch (meeting.decision) {
    case "linked":
      return (
        <div className={row}>
          {meeting.auto_pinned && (
            <span
              className="shrink-0 text-xs text-muted-foreground"
              title="Przypięte samo, bo firma miała jedną otwartą szansę. „Odepnij”, jeśli to spotkanie dotyczy czegoś innego: nie przypnie się ponownie."
            >
              samo
            </span>
          )}
          <StatusDot tone="success">
            <Link
              href={`/sales/opportunities/${meeting.opportunity?.id}`}
              className="hover:underline"
              title={meeting.opportunity?.name}
            >
              <TruncatedText className={meeting.auto_pinned ? "max-w-[148px]" : "max-w-[188px]"}>
                {meeting.opportunity?.name ?? ""}
              </TruncatedText>
            </Link>
          </StatusDot>
          {canEdit && meeting.can_unpin && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-muted-foreground"
              disabled={busy}
              onClick={onUnpin}
            >
              {meeting.auto_pinned ? "Odepnij" : "Cofnij"}
            </Button>
          )}
        </div>
      );
    case "client":
      return (
        <div className={row}>
          <ClientNotice meeting={meeting} />
        </div>
      );
    case "internal":
      return (
        <div className={row}>
          <span className="text-sm text-muted-foreground" title="Spotkanie przy karcie naszej firmy. Szansy się tu nie zakłada.">
            Spotkanie wewnętrzne
          </span>
        </div>
      );
    case "create":
      return (
        <div className={row}>
          {canEdit ? (
            <Button size="sm" onClick={onCreate}>
              Załóż szansę
            </Button>
          ) : (
            <span className="text-sm text-muted-foreground">Bez szansy</span>
          )}
        </div>
      );
    case "pin": {
      const option = meeting.open_opportunities[0];
      // Szansę mógł ktoś zamknąć między wyliczeniem decyzji a listą szans.
      if (!option) return null;
      return (
        <div className={row}>
          {canEdit ? (
            <Button
              size="sm"
              variant="outline"
              className="max-w-[264px]"
              disabled={busy}
              title={`Przypnij do szansy: ${option.title}`}
              aria-label={`Przypnij: ${option.title}`}
              onClick={() => onPin(option)}
            >
              <span className="truncate">Przypnij: {option.title}</span>
            </Button>
          ) : (
            <span className="text-sm text-muted-foreground">Do przypięcia</span>
          )}
        </div>
      );
    }
    case "choose":
      return (
        <div className={row}>
          {canEdit ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" disabled={busy}>
                  Przypnij ({meeting.open_opportunities.length})
                  <ChevronDown aria-hidden className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuLabel>Do której szansy?</DropdownMenuLabel>
                {meeting.open_opportunities.map((option) => (
                  <DropdownMenuItem
                    key={option.id}
                    onSelect={() => onPin(option)}
                    className="flex-col items-start gap-0"
                  >
                    <span className="w-full truncate text-sm">{option.title}</span>
                    <span className="text-[11.5px] leading-4 text-muted-foreground">{optionDetails(option)}</span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <span className="text-sm text-muted-foreground">Do przypięcia</span>
          )}
        </div>
      );
    default:
      return (
        <div className={row}>
          {meeting.company ? (
            <Link
              href={`/sales/companies/${meeting.company.id}`}
              className="text-sm text-muted-foreground hover:underline"
              title="Spotkanie spoza Outlooka zostaje przy firmie. Otwórz jej kartę."
            >
              Tylko przy firmie
            </Link>
          ) : (
            <span className="text-sm text-muted-foreground">—</span>
          )}
        </div>
      );
  }
}
