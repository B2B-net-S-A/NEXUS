"use client";

import { Suspense, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api, { extractErrorMsg } from "@/lib/api";
import { postLoginDestination, useAuthStore } from "@/store/auth";
import { AlertCircle } from "lucide-react";

/**
 * Microsoft SSO landing page.
 *
 * Backend's /api/auth/microsoft/callback redirected here with one of:
 *   - ?code=<uuid>     → POST to /api/auth/microsoft/exchange to get JWTs
 *   - ?error=<reason>  → forwarded by frontend to /login?error=...
 *
 * After exchange, fetch /api/auth/me to get the full user shape (same flow
 * as email+password login), then setAuth and redirect to onboarding or
 * the dashboard. The exchange code has a 60s TTL and is single-use, so the
 * effect runs only once via the `consumed` ref.
 */
function CallbackBody() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const code = searchParams.get("code");
  const error = searchParams.get("error");
  const { setAuth } = useAuthStore();
  const consumed = useRef(false);

  useEffect(() => {
    if (consumed.current) return;

    if (error) {
      consumed.current = true;
      router.replace(`/login?error=${encodeURIComponent(error)}`);
      return;
    }
    if (!code) {
      consumed.current = true;
      router.replace("/login?error=missing_code");
      return;
    }

    consumed.current = true;
    (async () => {
      try {
        const { data: tokens } = await api.post(
          "/api/auth/microsoft/exchange",
          { code },
        );
        const accessToken: string | undefined = tokens?.access_token;
        if (!accessToken) {
          throw new Error("Brak access_token w odpowiedzi");
        }
        const me = await api.get("/api/auth/me", {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        setAuth(me.data, accessToken);
        router.replace(postLoginDestination(me.data));
      } catch (err: unknown) {
        // extractErrorMsg, nie surowe `e.message`: 429 z limitera (ciało
        // slowapi bez klucza `detail`) trafiał na /login jako techniczne
        // „Request failed with status code 429".
        const detail = extractErrorMsg(err) || "Nie udało się dokończyć logowania";
        router.replace(`/login?error=${encodeURIComponent(detail)}`);
      }
    })();
  }, [code, error, router, setAuth]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center max-w-sm px-6">
        {error ? (
          <div className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>Logowanie Microsoft nie powiodło się — przekierowuję…</span>
          </div>
        ) : (
          <>
            <div className="w-8 h-8 rounded-md bg-primary text-primary-foreground flex items-center justify-center mx-auto mb-4">
              <span className="font-semibold text-sm">N</span>
            </div>
            <p className="text-sm text-muted-foreground">
              Kończę logowanie przez Microsoft…
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default function MicrosoftCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="text-sm text-muted-foreground">Ładowanie…</div>
        </div>
      }
    >
      <CallbackBody />
    </Suspense>
  );
}
