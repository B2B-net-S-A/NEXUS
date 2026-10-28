"use client";

// Ustawienia → Integracje → „Wtyczka LinkedIn” — kontener: react-query
// i odłączanie. Widok: `components/settings/linkedin-extension`.
// Dostęp: admin (middleware `/settings/linkedin-extension` + `AdminUser`
// w `backend/app/api/linkedin_extension.py::list_connections`).

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  LinkedinExtensionSettingsView,
  type LinkedinExtensionLoad,
} from "@/components/settings/linkedin-extension/LinkedinExtensionSettingsView";
import { linkedinExtensionApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { isForbiddenError } from "@/lib/view-state";

const CONNECTIONS_KEY = ["linkedin-extension", "connections"] as const;

export default function LinkedinExtensionSettingsPage() {
  const queryClient = useQueryClient();
  const [revokingKeyId, setRevokingKeyId] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: CONNECTIONS_KEY,
    queryFn: () => linkedinExtensionApi.connections().then((r) => r.data),
  });

  let load: LinkedinExtensionLoad;
  if (query.isSuccess) {
    load = { status: "success", items: query.data.items, readsLimit: query.data.reads_limit };
  } else if (query.isError) {
    const forbidden = isForbiddenError(query.error);
    load = {
      status: "error",
      forbidden,
      message: forbidden
        ? "Połączenia wtyczki widzi wyłącznie administrator."
        : apiErrorMessage(query.error, "Nie udało się pobrać połączeń wtyczki. Spróbuj ponownie."),
      onRetry: () => void query.refetch(),
    };
  } else {
    load = { status: "loading" };
  }

  const onRevoke = async (keyId: string) => {
    setRevokingKeyId(keyId);
    setRevokeError(null);
    try {
      await linkedinExtensionApi.revoke(keyId);
      await queryClient.invalidateQueries({ queryKey: CONNECTIONS_KEY });
    } catch (error: unknown) {
      setRevokeError(apiErrorMessage(error, "Nie udało się odłączyć wtyczki. Spróbuj ponownie."));
    } finally {
      setRevokingKeyId(null);
    }
  };

  return (
    <LinkedinExtensionSettingsView
      load={load}
      onRevoke={onRevoke}
      revokingKeyId={revokingKeyId}
      revokeError={revokeError}
    />
  );
}
