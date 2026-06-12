"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Phone } from "lucide-react";

// sip.js is browser-only → load the dialer widget client-side only.
const DialerWidget = dynamic(() => import("./DialerWidget"), { ssr: false });

interface CallButtonProps {
  candidateId: number;
  phone: string | null;
  candidateName?: string;
  /**
   * Render as the existing contact-row anchor (text + icon inline) when
   * ``compact`` is true; full button with bg/border otherwise.
   */
  compact?: boolean;
  className?: string;
}

/**
 * Click-to-call trigger. Opens the in-browser WebRTC dialer (`DialerWidget`),
 * which mints a SIP token, registers against the jambonz gateway, runs the
 * fraud-gate (`/api/dialer/calls/initiate`), and places the call. When the
 * dialer is disabled (`OWN_DIALER_ENABLED=false`) the widget surfaces the 503.
 */
export default function CallButton({
  candidateId,
  phone,
  candidateName,
  compact = false,
  className = "",
}: CallButtonProps) {
  const [dialerOpen, setDialerOpen] = useState(false);

  if (!phone) return null;

  const open = () => setDialerOpen(true);

  return (
    <>
      {compact ? (
        <button
          type="button"
          onClick={open}
          className={`inline-flex items-center gap-1.5 hover:text-primary ${className}`}
          title="Zadzwoń (dialer w przeglądarce)"
        >
          <Phone className="h-3.5 w-3.5 text-muted-foreground" />
          {phone}
        </button>
      ) : (
        <button
          type="button"
          onClick={open}
          className={`inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent ${className}`}
        >
          <Phone className="h-4 w-4" />
          Zadzwoń
        </button>
      )}
      {dialerOpen && (
        <DialerWidget
          candidateId={candidateId}
          phone={phone}
          candidateName={candidateName}
          open={dialerOpen}
          onOpenChange={setDialerOpen}
        />
      )}
    </>
  );
}
