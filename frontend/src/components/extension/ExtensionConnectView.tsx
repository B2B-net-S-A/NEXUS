"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, PlugZap, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { linkedinExtensionApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

/** Wiadomość do wtyczki — ten sam kształt czyta `chrome.runtime.onMessageExternal`. */
export interface ExtensionKeyMessage {
  type: "nexus-extension-key";
  key: string;
  apiBase: string;
  frontUrl: string;
}

type SendToExtension = (extensionId: string, message: ExtensionKeyMessage) => Promise<void>;

type ConnectState =
  | { status: "missing_extension" }
  | { status: "connecting" }
  | { status: "connected"; name: string }
  | { status: "error"; message: string };

interface ChromeRuntimeLike {
  sendMessage: (
    extensionId: string,
    message: ExtensionKeyMessage,
    callback: (response: unknown) => void,
  ) => void;
  lastError?: { message?: string };
}

function chromeRuntime(): ChromeRuntimeLike | null {
  const candidate = (globalThis as { chrome?: { runtime?: ChromeRuntimeLike } }).chrome;
  return candidate?.runtime && typeof candidate.runtime.sendMessage === "function"
    ? candidate.runtime
    : null;
}

/** Domyślna droga do wtyczki: `chrome.runtime.sendMessage` z oczekiwaniem na odpowiedź. */
export const sendViaChromeRuntime: SendToExtension = (extensionId, message) =>
  new Promise<void>((resolve, reject) => {
    const runtime = chromeRuntime();
    if (!runtime) {
      reject(new Error("no_runtime"));
      return;
    }
    runtime.sendMessage(extensionId, message, (response) => {
      if (runtime.lastError || (response as { ok?: boolean } | undefined)?.ok !== true) {
        reject(new Error("extension_rejected"));
        return;
      }
      resolve();
    });
  });

const EXTENSION_ID_RE = /^[a-p]{32}$/;

export interface ExtensionConnectViewProps {
  extensionId: string | null;
  extensionVersion: string | null;
  send?: SendToExtension;
}

export function ExtensionConnectView({
  extensionId,
  extensionVersion,
  send = sendViaChromeRuntime,
}: ExtensionConnectViewProps) {
  const validId = extensionId && EXTENSION_ID_RE.test(extensionId) ? extensionId : null;
  const [state, setState] = useState<ConnectState>(
    validId ? { status: "connecting" } : { status: "missing_extension" },
  );
  const started = useRef(false);

  const connect = async (id: string) => {
    setState({ status: "connecting" });
    try {
      const { data } = await linkedinExtensionApi.connect({
        extension_id: id,
        extension_version: extensionVersion,
      });
      await send(id, {
        type: "nexus-extension-key",
        key: data.key,
        apiBase: data.api_base,
        frontUrl: data.frontend_url,
      });
      setState({ status: "connected", name: data.user.name });
    } catch (error: unknown) {
      const local = error instanceof Error && (error.message === "no_runtime" || error.message === "extension_rejected");
      setState({
        status: "error",
        message: local
          ? "Wtyczka nie odebrała połączenia. Sprawdź, czy jest zainstalowana i włączona w Chrome, i kliknij „Połącz ponownie”."
          : apiErrorMessage(error, "Nie udało się połączyć wtyczki. Spróbuj ponownie."),
      });
    }
  };

  useEffect(() => {
    if (!validId || started.current) return;
    started.current = true;
    void connect(validId);
    // Jedno połączenie na wejście na stronę; ponowienie tylko przyciskiem.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validId]);

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 py-12">
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <PlugZap className="h-4 w-4" aria-hidden="true" />
        Wtyczka LinkedIn
      </div>
      <h1 className="text-xl font-semibold text-foreground">Połącz wtyczkę z NEXUSEM</h1>

      {state.status === "missing_extension" ? (
        <p className="text-sm text-muted-foreground">
          Tę stronę otwiera wtyczka NEXUS na LinkedInie. Otwórz panel wtyczki
          i kliknij „Zaloguj przez NEXUS”.
        </p>
      ) : null}

      {state.status === "connecting" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Łączę wtyczkę z Twoim kontem…
        </p>
      ) : null}

      {state.status === "connected" ? (
        <div
          className="flex items-start gap-2 rounded-lg bg-success-muted p-3 text-sm text-success-muted-foreground"
          role="status"
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Połączono jako <strong>{state.name}</strong>. Możesz zamknąć tę kartę
            i wrócić na LinkedIna. Wtyczka widzi to samo co Ty w NEXUSIE.
          </span>
        </div>
      ) : null}

      {state.status === "error" ? (
        <div className="flex flex-col gap-3">
          <div
            className="flex items-start gap-2 rounded-lg bg-destructive-muted p-3 text-sm text-destructive-muted-foreground"
            role="alert"
          >
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{state.message}</span>
          </div>
          {validId ? (
            <Button type="button" onClick={() => void connect(validId)} className="self-start">
              Połącz ponownie
            </Button>
          ) : null}
        </div>
      ) : null}

      <p className="text-xs text-muted-foreground">
        Odłączenie: Ustawienia → Wtyczka LinkedIn. Zmiana roli albo hasła odłącza
        wtyczkę sama.
      </p>
    </div>
  );
}
