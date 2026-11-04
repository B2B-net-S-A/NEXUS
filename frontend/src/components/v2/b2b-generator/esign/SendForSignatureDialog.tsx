"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, Send } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/lib/api-error";
import type { B2BGeneratedContractRow } from "@/lib/api";
import { b2bEsignApi, type EsignSendResult } from "@/lib/api/b2bEsign";

type Route = "nexus" | "usual";

/**
 * „Wyślij do podpisu” (makieta 4): droga W NEXUSIE albo jak dotąd. Droga
 * zwykła niczego nie wysyła — mówi, co zrobić, i zostawia „Oznacz jako
 * podpisaną” z plikiem.
 */
export function SendForSignatureDialog({
  row,
  onClose,
}: {
  row: B2BGeneratedContractRow;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const defaults = useQuery({
    queryKey: ["b2b-esign-defaults", row.id],
    queryFn: () => b2bEsignApi.defaults(row.id),
    staleTime: 0,
  });
  const [route, setRoute] = useState<Route>("nexus");
  const [email, setEmail] = useState("");
  const [signerId, setSignerId] = useState<number | null>(null);
  // 26.10.2026 (Sandra): krótkie terminy; przypomnienie dzień przed końcem.
  const [days, setDays] = useState(3);
  const [checked, setChecked] = useState(false);
  const [result, setResult] = useState<EsignSendResult | null>(null);
  const [copied, setCopied] = useState(false);
  // DW (27.10.2026): mail z Twojej skrzynki, prowadzący rekrutację zaznaczony.
  const [cc, setCc] = useState<number[]>([]);

  useEffect(() => {
    if (!defaults.data) return;
    setEmail(defaults.data.contractor_email ?? "");
    setSignerId(defaults.data.company_signers[0]?.id ?? null);
    setCc((defaults.data.cc_candidates ?? []).filter((p) => p.suggested).map((p) => p.id));
  }, [defaults.data]);

  const send = useMutation({
    mutationFn: () =>
      b2bEsignApi.send(row.id, {
        contractor_email: email.trim(),
        company_signer_id: signerId ?? 0,
        days,
        cc_user_ids: cc,
      }),
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      queryClient.invalidateQueries({ queryKey: ["kanban"] });
      queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
    },
  });

  const signers = defaults.data?.company_signers ?? [];
  const canSend =
    route === "nexus" &&
    defaults.isSuccess &&
    /\S+@\S+\.\S+/.test(email.trim()) &&
    signerId !== null &&
    checked &&
    !send.isPending;

  const copy = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.sign_url);
    setCopied(true);
  };

  return (
    <Dialog open onOpenChange={(open) => (!open && !send.isPending ? onClose() : undefined)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Wyślij do podpisu — umowa {row.contract_number}</DialogTitle>
          <DialogDescription>
            {[row.partner_display_name ?? row.partner_name, row.canonical_client_name, row.job_title]
              .filter(Boolean)
              .join(" · ")}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {result ? (
            <div className="space-y-3">
              <Alert
                variant={result.mail_sent ? "success" : "warning"}
                title={
                  result.mail_sent
                    ? `Mail z linkiem wysłany do ${result.request.contractor_email ?? "kontraktora"}`
                    : "Wysyłka zapisana — wyślij link kontraktorowi"
                }
                description={
                  result.mail_sent
                    ? "Umowa czeka na podpis kontraktora. Stan widzisz w kolumnie „Podpis”."
                    : (result.mail_problem ?? "Skopiuj link i wyślij go kontraktorowi.")
                }
              />
              <div className="flex flex-wrap items-center gap-2">
                <Input readOnly value={result.sign_url} aria-label="Link do podpisu" className="min-w-0 flex-1" />
                <Button type="button" variant="outline" onClick={() => void copy()}>
                  {copied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
                  {copied ? "Skopiowano" : "Kopiuj link"}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <fieldset className="space-y-2">
                <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Jak podpisujemy?
                </legend>
                {(
                  [
                    {
                      value: "nexus" as const,
                      title: "W NEXUSIE — podpis kwalifikowany",
                      text: "Kontraktor dostaje link, podpisuje i wgrywa plik. Potem podpis za B2B Network w NEXUSIE. Podpisany PDF zostaje przy kontrakcie.",
                    },
                    {
                      value: "usual" as const,
                      title: "Jak dotąd — mail",
                      text: "Pobierz umowę i wyślij ją sam(a). Po powrocie podpisanej: „Oznacz jako podpisaną” i dołącz plik.",
                    },
                  ]
                ).map((option) => (
                  <label
                    key={option.value}
                    className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5"
                  >
                    <input
                      type="radio"
                      name={`esign-route-${row.id}`}
                      className="mt-0.5 accent-primary"
                      checked={route === option.value}
                      onChange={() => setRoute(option.value)}
                    />
                    <span>
                      <span className="font-medium text-foreground">{option.title}</span>
                      <span className="block text-xs text-muted-foreground">{option.text}</span>
                    </span>
                  </label>
                ))}
              </fieldset>

              {route === "nexus" ? (
                defaults.isPending ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytuję dane umowy…
                  </p>
                ) : defaults.isError ? (
                  <Alert
                    variant="error"
                    title="Nie udało się wczytać danych do wysyłki"
                    description={apiErrorMessage(defaults.error, "Spróbuj ponownie za chwilę.")}
                  />
                ) : (
                  <div className="space-y-3">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1">
                        <Label>1. Kontraktor</Label>
                        <p className="text-sm text-foreground">{defaults.data.contractor_name ?? "—"}</p>
                        <p className="text-xs text-muted-foreground">
                          Z umowy. Podpisuje ta osoba — inna zmiana wymaga poprawki umowy.
                        </p>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`esign-email-${row.id}`}>E-mail kontraktora</Label>
                        <Input
                          id={`esign-email-${row.id}`}
                          type="email"
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`esign-signer-${row.id}`}>2. Za B2B Network</Label>
                        <select
                          id={`esign-signer-${row.id}`}
                          className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                          value={signerId ?? ""}
                          onChange={(e) => setSignerId(Number(e.target.value) || null)}
                        >
                          {signers.length === 0 ? <option value="">Brak osób w ustawieniach</option> : null}
                          {signers.map((person) => (
                            <option key={person.id} value={person.id}>
                              {person.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`esign-days-${row.id}`}>Termin na podpis</Label>
                        <select
                          id={`esign-days-${row.id}`}
                          className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                          value={days}
                          onChange={(e) => setDays(Number(e.target.value))}
                        >
                          <option value={1}>1 dzień</option>
                          <option value={3}>3 dni</option>
                          <option value={5}>5 dni</option>
                          <option value={7}>7 dni</option>
                        </select>
                      </div>
                    </div>
                    {(defaults.data.cc_candidates ?? []).length > 0 ? (
                      <fieldset className="space-y-1.5" aria-describedby={`esign-cc-help-${row.id}`}>
                        <legend className="text-sm font-medium">3. Do wiadomości (DW)</legend>
                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                          {(defaults.data.cc_candidates ?? []).map((person) => (
                            <label key={person.id} className="flex items-center gap-2 text-sm">
                              <Checkbox
                                checked={cc.includes(person.id)}
                                onCheckedChange={(value) =>
                                  setCc((prev) =>
                                    value === true
                                      ? [...prev, person.id]
                                      : prev.filter((id) => id !== person.id),
                                  )
                                }
                              />
                              {person.name}
                              {person.suggested ? (
                                <span className="text-xs text-muted-foreground">(prowadzi rekrutację)</span>
                              ) : null}
                            </label>
                          ))}
                        </div>
                        <p id={`esign-cc-help-${row.id}`} className="text-xs text-muted-foreground">
                          Mail wychodzi z Twojej skrzynki. Osoby w DW dostają link, kopię podpisanej
                          umowy i dzwonki, a odpowiedź kontraktora trafi też do nich. Na liście są
                          tylko osoby z zespołu rekrutacji, które widzą tę umowę ze stawkami.
                        </p>
                      </fieldset>
                    ) : null}
                    {!defaults.data.mailbox_connected ? (
                      <Alert
                        variant="info"
                        title="Twoja skrzynka nie jest połączona"
                        description="NEXUS nie wyśle maila za Ciebie — po wysyłce skopiujesz link i wyślesz go sam(a)."
                      />
                    ) : null}
                    <div className="flex items-start gap-2">
                      <Checkbox
                        id={`esign-checked-${row.id}`}
                        checked={checked}
                        onCheckedChange={(value) => setChecked(value === true)}
                        className="mt-0.5"
                      />
                      <Label htmlFor={`esign-checked-${row.id}`} className="text-sm font-normal leading-snug">
                        Sprawdziłam/em treść umowy. Po wysyłce PDF jest zamrożony — poprawka to
                        wycofanie i nowa wysyłka.
                      </Label>
                    </div>
                  </div>
                )
              ) : (
                <Alert
                  variant="info"
                  title="Droga zwykła"
                  description="Pobierz DOCX z wiersza, wyślij go mailem jak dotąd. Gdy podpisana umowa wróci, kliknij „Oznacz jako podpisaną” i dołącz plik — trafi do Dokumentów kontraktu."
                />
              )}
              {send.isError ? (
                <Alert
                  variant="error"
                  title="Nie udało się wysłać"
                  description={apiErrorMessage(send.error, "Spróbuj ponownie.")}
                />
              ) : null}
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={send.isPending}>
            {result || route === "usual" ? "Zamknij" : "Anuluj"}
          </Button>
          {!result && route === "nexus" ? (
            <Button type="button" variant="primary" disabled={!canSend} onClick={() => send.mutate()}>
              {send.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Send className="h-4 w-4" aria-hidden />
              )}
              Wyślij link do kontraktora
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
