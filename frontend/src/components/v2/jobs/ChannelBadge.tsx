import { Linkedin } from "lucide-react";

import { CHANNEL_LABELS, type RecruiterChannel } from "@/lib/job-channels";
import { cn } from "@/lib/utils";

/** Znak Dynaminds (`public/brand/dynaminds-mark.svg`) — koszyk „Baza”. */
function DynamindsMark({ className }: { className?: string }) {
  return (
    <svg viewBox="10 4 84 56" aria-hidden="true" className={className}>
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M89.16,54.85L62.61,8.87l-5.31,9.2,21.24,36.79h10.62ZM62.61,45.65h-21.24s-5.31,9.2-5.31,9.2h31.86s-5.31-9.2-5.31-9.2h0ZM41.37,27.26l5.31,9.2h10.62s-15.93-27.59-15.93-27.59L14.82,54.85h10.62s15.93-27.59,15.93-27.59h0Z"
      />
    </svg>
  );
}

export function ChannelIcon({
  channel,
  className,
}: {
  channel: RecruiterChannel;
  className?: string;
}) {
  return channel === "base" ? (
    <DynamindsMark className={cn("text-primary", className)} />
  ) : (
    <Linkedin aria-hidden="true" className={cn("text-info", className)} />
  );
}

/**
 * Znaczek koszyka: ikonka i nazwa (`iconOnly` — sama ikonka z podpowiedzią,
 * do wąskich kolumn pulpitu przy 1280 px).
 */
export function ChannelBadge({
  channel,
  iconOnly = false,
  className,
}: {
  channel: RecruiterChannel;
  iconOnly?: boolean;
  className?: string;
}) {
  const label = CHANNEL_LABELS[channel];
  return (
    <span
      title={iconOnly ? label : undefined}
      data-channel={channel}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full text-[11px] font-semibold text-foreground",
        iconOnly ? "p-0.5" : "px-1.5 py-px",
        channel === "base" ? "bg-primary/10" : "bg-info-muted",
        className,
      )}
    >
      <ChannelIcon channel={channel} className="h-3 w-3" />
      {iconOnly ? <span className="sr-only">{label}</span> : label}
    </span>
  );
}
