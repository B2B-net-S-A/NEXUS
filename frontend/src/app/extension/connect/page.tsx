"use client";

// „Połącz wtyczkę z NEXUSEM” — wtyczka LinkedIn otwiera tę kartę
// (`/extension/connect?ext=<id wtyczki>&v=<wersja>`). Zalogowany użytkownik
// dostaje klucz `nxe_…` (`POST /api/extension/connect`), a strona oddaje go
// wtyczce przez `chrome.runtime.sendMessage` (manifest:
// `externally_connectable`). Klucz nie trafia do adresu ani do localStorage.

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { ExtensionConnectView } from "@/components/extension/ExtensionConnectView";

function ConnectWithParams() {
  const params = useSearchParams();
  return (
    <ExtensionConnectView
      extensionId={params.get("ext")}
      extensionVersion={params.get("v")}
    />
  );
}

export default function ExtensionConnectPage() {
  return (
    <Suspense fallback={null}>
      <ConnectWithParams />
    </Suspense>
  );
}
