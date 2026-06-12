"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, MicOff, Phone, PhoneOff } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Web } from "sip.js";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { dialerApi, extractErrorMsg } from "@/lib/api";

interface DialerWidgetProps {
  candidateId: number;
  phone: string;
  candidateName?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type DialState =
  | "connecting"
  | "ringing"
  | "in-call"
  | "ended"
  | "error";

function normalizeNumber(phone: string): string {
  return phone.replace(/[^\d+]/g, "");
}

/**
 * In-browser SIP softphone (WebRTC) for click-to-call.
 *
 * Flow: GET /api/dialer/token → mic permission → SimpleUser connect+register
 * (WSS to jambonz) → POST /api/dialer/calls/initiate (fraud-gate + stub) →
 * place the call. Remote audio is attached to a hidden <audio>. SimpleUser
 * (sip.js) handles registration, media wiring, and session lifecycle.
 *
 * Cannot place real calls until the gateway (jambonz) + trunk are live; until
 * then GET /token returns 503 and we surface a friendly message.
 */
export default function DialerWidget({
  candidateId,
  phone,
  candidateName,
  open,
  onOpenChange,
}: DialerWidgetProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const userRef = useRef<Web.SimpleUser | null>(null);
  const [state, setState] = useState<DialState>("connecting");
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);

  const cleanup = useCallback(async () => {
    const user = userRef.current;
    userRef.current = null;
    if (!user) return;
    try {
      await user.hangup();
    } catch {
      /* not in a call */
    }
    try {
      await user.disconnect();
    } catch {
      /* already disconnected */
    }
  }, []);

  // In-call timer.
  useEffect(() => {
    if (state !== "in-call") return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [state]);

  // Run the full dial flow when the widget opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setState("connecting");
    setSeconds(0);
    setMuted(false);

    (async () => {
      try {
        const token = await dialerApi.getToken();
        if (cancelled) return;

        const audioEl = audioRef.current;
        if (!audioEl) throw new Error("audio element missing");

        const simpleUser = new Web.SimpleUser(token.websocket_url, {
          aor: `sip:${token.sip_username}@${token.sip_realm}`,
          media: { remote: { audio: audioEl } },
          userAgentOptions: {
            authorizationUsername: token.sip_username,
            authorizationPassword: token.sip_password,
            sessionDescriptionHandlerFactoryOptions: {
              peerConnectionConfiguration: {
                iceServers: token.ice_servers.map((s) => ({
                  urls: s.urls,
                  username: s.username ?? undefined,
                  credential: s.credential ?? undefined,
                })),
              },
            },
          },
        });
        simpleUser.delegate = {
          onCallAnswered: () => !cancelled && setState("in-call"),
          onCallHangup: () => {
            if (cancelled) return;
            setState("ended");
            queryClient.invalidateQueries({
              queryKey: ["candidate-calls", String(candidateId)],
            });
          },
        };
        userRef.current = simpleUser;

        await simpleUser.connect();
        await simpleUser.register();
        if (cancelled) return;

        // Fraud-gate + Call stub (PL-only allowlist, per-user caps) before dialing.
        await dialerApi.initiateCall(candidateId);
        if (cancelled) return;

        setState("ringing");
        await simpleUser.call(`sip:${normalizeNumber(phone)}@${token.sip_realm}`);
      } catch (err: unknown) {
        if (cancelled) return;
        setState("error");
        showError(extractErrorMsg(err));
      }
    })();

    return () => {
      cancelled = true;
      void cleanup();
    };
  }, [open, candidateId, phone, cleanup, queryClient, showError]);

  const handleHangup = useCallback(async () => {
    await cleanup();
    setState("ended");
    showSuccess("Rozmowa zakończona");
    queryClient.invalidateQueries({
      queryKey: ["candidate-calls", String(candidateId)],
    });
  }, [cleanup, showSuccess, queryClient, candidateId]);

  const toggleMute = useCallback(() => {
    const user = userRef.current;
    if (!user) return;
    if (muted) {
      user.unmute();
      setMuted(false);
    } else {
      user.mute();
      setMuted(true);
    }
  }, [muted]);

  const mmss = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>
            <div className="flex items-center gap-2">
              <Phone className="h-5 w-5 text-primary" />
              {candidateName ? `Rozmowa: ${candidateName}` : "Rozmowa"}
            </div>
          </DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <audio ref={audioRef} autoPlay className="hidden" />

          <div className="text-center">
            <div className="text-lg font-medium text-foreground">{phone}</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {state === "connecting" && (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Łączenie…
                </span>
              )}
              {state === "ringing" && (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Dzwonię…
                </span>
              )}
              {state === "in-call" && (
                <span className="text-emerald-600">Połączono · {mmss}</span>
              )}
              {state === "ended" && <span>Zakończona</span>}
              {state === "error" && (
                <span className="text-red-600">Nie udało się połączyć</span>
              )}
            </div>
          </div>

          <div className="flex items-center justify-center gap-3">
            {(state === "in-call" || state === "ringing") && (
              <Button
                variant="outline"
                size="icon"
                onClick={toggleMute}
                aria-label={muted ? "Wyłącz wyciszenie" : "Wycisz"}
                disabled={state !== "in-call"}
              >
                {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              </Button>
            )}
            {state === "ended" || state === "error" ? (
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Zamknij
              </Button>
            ) : (
              <Button variant="destructive" onClick={handleHangup}>
                <PhoneOff className="mr-1.5 h-4 w-4" /> Zakończ
              </Button>
            )}
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
