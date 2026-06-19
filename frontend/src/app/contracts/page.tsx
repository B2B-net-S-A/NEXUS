"use client";

import { useEffect, useState } from "react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import {
  ContractsClientPicker,
  type ClientRef,
} from "@/components/contracts/ContractsClientPicker";
import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";

/**
 * Client-only gate: Next.js 15 + React 19 streaming SSR wieszało hydrację
 * ContractsListV2 na skeleton. `mounted` flag forsuje pierwszy render
 * dopiero po useEffect, co pomija SSR boundary i odblokowuje useQuery.
 *
 * Wybór klienta (per-klient rejestr kontraktów) trzymamy w URL (?client=11&
 * clientName=Nordea) przez History API — deep-link działa, a brak wybranego
 * klienta = globalna lista (ContractsListV2).
 */
export default function ContractsPage() {
  const [mounted, setMounted] = useState(false);
  const [client, setClient] = useState<ClientRef | null>(null);

  useEffect(() => {
    setMounted(true);
    const params = new URLSearchParams(window.location.search);
    const id = params.get("client");
    const name = params.get("clientName");
    if (id) setClient({ id: Number(id), name: name ?? `#${id}` });
  }, []);

  const handleChange = (next: ClientRef | null) => {
    setClient(next);
    const params = new URLSearchParams(window.location.search);
    if (next) {
      params.set("client", String(next.id));
      params.set("clientName", next.name);
    } else {
      params.delete("client");
      params.delete("clientName");
    }
    const qs = params.toString();
    window.history.replaceState(null, "", `/contracts${qs ? `?${qs}` : ""}`);
  };

  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie kontraktów…</div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-4">
      <ContractsClientPicker value={client} onChange={handleChange} />
      {client ? (
        <ClientContractRegister clientId={client.id} clientName={client.name} />
      ) : (
        <ContractsListV2 />
      )}
    </div>
  );
}
