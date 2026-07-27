"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

export default function Microsoft365CallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const status = params.get("status");
  const message = params.get("message");

  const [countdown, setCountdown] = useState(2);

  useEffect(() => {
    if (status !== "success") return;
    const id = setInterval(
      () => setCountdown((c) => (c > 0 ? c - 1 : 0)),
      1000,
    );
    const jump = setTimeout(() => router.push("/settings"), 2000);
    return () => {
      clearInterval(id);
      clearTimeout(jump);
    };
  }, [status, router]);

  if (status === "success") {
    return (
      <Centered>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-8 w-8 text-green-500" />
          <div>
            <p className="text-lg font-semibold text-foreground">
              Połączono z Microsoft 365
            </p>
            <p className="text-sm text-muted-foreground mt-0.5">
              Synchronizacja wątków rozpoczęta. Wracamy do ustawień za{" "}
              {countdown}s...
            </p>
          </div>
        </div>
      </Centered>
    );
  }

  if (status === "error") {
    return (
      <Centered>
        <div className="flex items-start gap-3 max-w-lg">
          <AlertCircle className="h-8 w-8 text-destructive shrink-0 mt-1" />
          <div>
            <p className="text-lg font-semibold text-foreground">
              Nie udało się połączyć
            </p>
            <p className="text-sm text-muted-foreground mt-1 wrap-break-word">
              {message ?? "Nieznany błąd."}
            </p>
            <Link
              href="/settings"
              className="inline-flex mt-4 items-center gap-2 text-sm font-medium text-primary hover:underline"
            >
              Wróć do ustawień i spróbuj ponownie
            </Link>
          </div>
        </div>
      </Centered>
    );
  }

  return (
    <Centered>
      <div className="flex items-center gap-3">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" />
        <p className="text-sm text-muted-foreground">Finalizacja połączenia...</p>
      </div>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-[60vh] flex items-center justify-center p-6">
      <div className="bg-card border border-border rounded-2xl shadow-xs p-8">
        {children}
      </div>
    </div>
  );
}
