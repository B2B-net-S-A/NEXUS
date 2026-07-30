"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import api, { extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

export interface IdentityEditorCandidate {
  id: number;
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
  phone?: string | null;
}

/**
 * Inline edycja tożsamości i kontaktu kandydata (imię, nazwisko, e-mail,
 * telefon) wprost w nagłówku profilu — bez otwierania pełnego modala "Edytuj".
 *
 * Szczególnie przydatne dla kandydatów zaimportowanych z Traffit jako "?"
 * (brak sparsowanego imienia): rekruter widzi profil i może od razu poprawić
 * dane. PATCH /api/candidates/{id} akceptuje te pola od dawna — brakowało tylko
 * widocznego, prostego wejścia w UI.
 */
export function IdentityEditor({
  candidate,
  onClose,
}: {
  candidate: IdentityEditorCandidate;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState({
    name: candidate.name ?? "",
    lastname: candidate.lastname ?? "",
    email: candidate.email ?? "",
    phone: candidate.phone ?? "",
  });

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/api/candidates/${candidate.id}`, {
        name: form.name.trim(),
        lastname: form.lastname.trim(),
        // Pusty string → null: pozwala WYCZYŚCIĆ pole. Backend EmailStr
        // odrzuca "" (422), a null kasuje wartość. Trim, by nie zapisać spacji.
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
      }),
    onSuccess: () => {
      showSuccess("Zapisano dane kandydata");
      queryClient.invalidateQueries({ queryKey: ["candidate", candidate.id] });
      // Lista/kafelki V2 cache'ują imię i nazwisko — odśwież, by zmiana była
      // widoczna po zamknięciu drawera bez twardego reloadu.
      queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      onClose();
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się zapisać danych kandydata"),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.lastname.trim()) {
      showError("Imię i nazwisko są wymagane");
      return;
    }
    save.mutate();
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Imię</Label>
          <Input
            className="min-h-11"
            autoFocus
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="Jan"
          />
        </div>
        <div>
          <Label className="text-xs">Nazwisko</Label>
          <Input
            className="min-h-11"
            value={form.lastname}
            onChange={(e) => setForm((f) => ({ ...f, lastname: e.target.value }))}
            placeholder="Kowalski"
          />
        </div>
        <div>
          <Label className="text-xs">E-mail</Label>
          <Input
            className="min-h-11"
            type="email"
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            placeholder="jan.kowalski@firma.pl"
          />
        </div>
        <div>
          <Label className="text-xs">Telefon</Label>
          <Input
            className="min-h-11"
            type="tel"
            value={form.phone}
            onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
            placeholder="+48 500 600 700"
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="submit"
          size="sm"
          variant="primary"
          className="min-h-11 min-w-11"
          disabled={save.isPending}
        >
          {save.isPending ? "Zapisywanie…" : "Zapisz"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="min-h-11 min-w-11"
          onClick={onClose}
          disabled={save.isPending}
        >
          Anuluj
        </Button>
      </div>
    </form>
  );
}
