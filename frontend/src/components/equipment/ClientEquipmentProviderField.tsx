"use client";

import { useToast } from "@/components/Toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useClientProvider,
  useSetClientProvider,
  type EquipmentProvider,
} from "@/lib/api/equipment";

import { PROVIDER_LABELS } from "./equipment-format";

interface ClientEquipmentProviderFieldProps {
  clientId: number;
  /** Edycja klientów albo „Sprzęt”; bez prawa zapisu pole jest tylko do odczytu. */
  canEdit: boolean;
}

/**
 * Flaga klienta „sprzęt od nas / od klienta” (D7). „Od nas” = start kontraktu
 * zakłada recepcji zadanie 7 dni roboczych wcześniej. Wyłączony moduł (404)
 * albo brak dostępu (403) chowa pole.
 */
export function ClientEquipmentProviderField({ clientId, canEdit }: ClientEquipmentProviderFieldProps) {
  const { showToast } = useToast();
  const provider = useClientProvider(clientId);
  const save = useSetClientProvider(clientId);
  if (provider.isLoading || provider.isError || !provider.data) return null;

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">Sprzęt dla konsultantów</span>
      {canEdit ? (
        <Select
          value={provider.data}
          onValueChange={(value) =>
            save.mutate(value as EquipmentProvider, {
              onSuccess: () => showToast("Zapisano", "success"),
              onError: (err) =>
                showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
            })
          }
        >
          <SelectTrigger aria-label="Sprzęt dla konsultantów" className="h-8 w-48 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(PROVIDER_LABELS) as EquipmentProvider[]).map((value) => (
              <SelectItem key={value} value={value}>
                {PROVIDER_LABELS[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span>{PROVIDER_LABELS[provider.data]}</span>
      )}
    </div>
  );
}
