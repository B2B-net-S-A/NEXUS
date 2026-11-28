"use client";

import { useState } from "react";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  marketCompanyLookup,
  type MarketPanelInput,
  type MarketTrainerApplication,
} from "@/lib/api/trainings";

interface Props {
  application: MarketTrainerApplication;
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: MarketPanelInput) => void;
}

function initial(application: MarketTrainerApplication): MarketPanelInput {
  const { panel } = application;
  return {
    company_name: panel.company_name,
    nip: panel.nip ?? "",
    regon: panel.regon,
    company_address: panel.company_address,
    panel_email: panel.panel_email ?? application.email,
  };
}

/**
 * „Otwórz panel trenera” (0807, decyzja Artura 28.11.2026): dane firmy do umowy
 * szkoleniowej wpisuje TCM, NIP podpowiada Biała Lista jak w Generatorze B2B.
 * Zapis wysyła trenerowi link do panelu (gdy wejście trenerów jest włączone).
 */
export function MarketPanelDialog({ application, busy, onClose, onSubmit }: Props) {
  const [form, setForm] = useState<MarketPanelInput>(() => initial(application));
  const [lookup, setLookup] = useState<{ state: "idle" | "busy" | "done" | "error"; note: string }>({
    state: "idle",
    note: "",
  });
  const set = (key: keyof MarketPanelInput) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const fetchCompany = async () => {
    setLookup({ state: "busy", note: "" });
    try {
      const found = await marketCompanyLookup(form.nip.trim());
      setForm((current) => ({ ...current, ...found, panel_email: current.panel_email }));
      setLookup({ state: "done", note: "Dane z rejestru. Sprawdź je przed zapisem." });
    } catch (error: unknown) {
      setLookup({ state: "error", note: apiErrorMessage(error, "Nie udało się odczytać rejestru.") });
    }
  };

  const reopening = application.panel.panel_opened_at !== null;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{reopening ? "Dane firmy i link do panelu" : "Otwórz panel trenera"}</DialogTitle>
          <DialogDescription>
            {application.full_name}. Te dane trafią do umowy szkoleniowej. Trener widzi je w panelu, ale
            zmienia tylko przez Ciebie.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({
              company_name: form.company_name.trim(),
              nip: form.nip.trim(),
              regon: form.regon.trim(),
              company_address: form.company_address.trim(),
              panel_email: form.panel_email.trim(),
            });
          }}
        >
          <DialogBody className="space-y-3">
            <div className="flex items-end gap-2">
              <FormField label="NIP firmy" htmlFor="market-nip" className="min-w-0 flex-1">
                <Input id="market-nip" inputMode="numeric" value={form.nip} onChange={set("nip")} />
              </FormField>
              <Button
                type="button"
                variant="outline"
                disabled={lookup.state === "busy" || form.nip.replace(/\D/g, "").length !== 10}
                onClick={() => void fetchCompany()}
              >
                <Search aria-hidden className="size-4" /> Biała Lista
              </Button>
            </div>
            {lookup.note ? (
              <p
                role={lookup.state === "error" ? "alert" : undefined}
                className={lookup.state === "error" ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
              >
                {lookup.note}
              </p>
            ) : null}
            <FormField label="Nazwa firmy" htmlFor="market-company">
              <Input id="market-company" value={form.company_name} onChange={set("company_name")} />
            </FormField>
            <FormField label="REGON (opcjonalnie)" htmlFor="market-regon">
              <Input id="market-regon" inputMode="numeric" value={form.regon} onChange={set("regon")} />
            </FormField>
            <FormField label="Adres siedziby" htmlFor="market-address">
              <Input id="market-address" value={form.company_address} onChange={set("company_address")} />
            </FormField>
            <FormField
              label="E-mail do panelu"
              htmlFor="market-email"
              description="Na ten adres pójdzie link. Zmiana adresu zamyka stare sesje."
            >
              <Input id="market-email" type="email" value={form.panel_email} onChange={set("panel_email")} />
            </FormField>
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Anuluj
            </Button>
            <Button type="submit" disabled={busy}>
              {reopening ? "Zapisz i wyślij nowy link" : "Otwórz panel i wyślij link"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
