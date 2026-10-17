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
  useReceivers,
  useSetReceivers,
  type TransferKind,
} from "@/lib/api/hr-lifecycle";

const NONE = "none";

interface ReceiverSelectProps {
  caseId: number;
  kind: TransferKind;
  receiverId: number | null;
  receiverName: string | null;
  label: string;
}

/** Wybór przejmującego dla jednego rodzaju pracy (lista z serwera: tylko osoby z właściwą rolą). */
export function ReceiverSelect({
  caseId,
  kind,
  receiverId,
  receiverName,
  label,
}: ReceiverSelectProps) {
  const { showToast } = useToast();
  const receivers = useReceivers(caseId, kind);
  const save = useSetReceivers(caseId);
  const options = receivers.data ?? [];
  const known = receiverId == null || options.some((o) => o.user_id === receiverId);

  return (
    <Select
      value={receiverId == null ? NONE : String(receiverId)}
      disabled={save.isPending}
      onValueChange={(value) =>
        save.mutate(
          { [kind]: value === NONE ? null : Number(value) },
          {
            onError: (err) =>
              showToast(apiErrorMessage(err, "Nie udało się zapisać przejmującego."), "error"),
          },
        )
      }
    >
      <SelectTrigger className="h-8 max-w-[240px]" aria-label={`Przekaż do: ${label}`}>
        <SelectValue placeholder="Wybierz osobę" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>Nie wskazano</SelectItem>
        {!known && receiverId != null ? (
          <SelectItem value={String(receiverId)}>{receiverName ?? "Wybrana osoba"}</SelectItem>
        ) : null}
        {options.map((option) => (
          <SelectItem key={option.user_id} value={String(option.user_id)}>
            {option.name}
          </SelectItem>
        ))}
        {receivers.isError ? (
          <p role="alert" className="px-2 py-1.5 text-xs text-destructive">
            {apiErrorMessage(receivers.error, "Nie udało się wczytać listy osób.")}
          </p>
        ) : null}
      </SelectContent>
    </Select>
  );
}
