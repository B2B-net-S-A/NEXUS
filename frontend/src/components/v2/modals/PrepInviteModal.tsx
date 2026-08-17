"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { helpMaterialsApi } from "@/lib/api/help-materials";
import { fillInviteDraft, findPrepInviteTemplate } from "@/lib/help-invite";
import {
  PrepInviteActions,
  PrepInviteCvReminder,
} from "@/components/v2/PrepInviteActions";

/**
 * Zaproszenie na spotkanie przygotowujące (prep) z poziomu profilu kandydata.
 *
 * To NIE jest „Zaplanuj interview" — tamta akcja wysyła zaproszenie od razu
 * przez Graph. Tu rekruter dostaje SZKIC do własnego Outlooka, dokłada CV i link
 * do ogłoszenia, i dopiero wtedy wysyła. Dwie różne funkcje, dlatego osobna
 * pozycja w menu i inne nazewnictwo — pomylenie ich kosztuje wysłane
 * zaproszenie bez CV.
 *
 * Treść pochodzi z jednego źródła: pozycji-szablonu w zakładce Pomoc, którą
 * edytuje admin. Kopia w kodzie rozjechałaby się z nią po pierwszej edycji.
 */
export interface PrepInviteModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateName: string;
  /** Przekazywany wprost do akcji — patrz `PrepInviteActionsProps.onToast`. */
  onToast?: (message: string, type?: "success" | "error") => void;
}

export function PrepInviteModal({
  open,
  onOpenChange,
  candidateName,
  onToast,
}: PrepInviteModalProps) {
  const templateQuery = useQuery({
    queryKey: ["help-materials", "prep-invite"],
    // Szablon zmienia się rzadko, a modal otwiera się przy każdym kandydacie.
    staleTime: 5 * 60_000,
    enabled: open,
    queryFn: () => helpMaterialsApi.list({ published_only: true }),
  });

  const template = useMemo(
    () => findPrepInviteTemplate(templateQuery.data ?? []),
    [templateQuery.data],
  );

  const prefilled = useMemo(
    () =>
      template
        ? fillInviteDraft(
            {
              subject: template.template_subject ?? template.title,
              body: template.template_body,
            },
            { candidateName },
          )
        : null,
    [template, candidateName],
  );

  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  // Reset przy każdym otwarciu: modal jest współdzielony między kandydatami,
  // więc bez tego drugi kandydat dostałby treść poprawioną dla pierwszego.
  useEffect(() => {
    if (open && prefilled) {
      setSubject(prefilled.subject);
      setBody(prefilled.body);
    }
  }, [open, prefilled]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" className="flex flex-col max-h-[90vh]">
        <DialogHeader>
          <DialogTitle>Zaproszenie na spotkanie przygotowujące</DialogTitle>
        </DialogHeader>

        <DialogBody className="space-y-4 flex-1">
          {/* Kolejność gałęzi jest load-bearing: błąd MUSI wyprzedzić „pusto",
              inaczej awaria pobrania renderuje się jak brak szablonu. */}
          {templateQuery.isError ? (
            <div className="rounded-lg border border-border bg-card p-4">
              <p className="text-sm text-foreground">
                Nie udało się wczytać szablonu zaproszenia.
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                To błąd pobierania, nie brak danych — spróbuj ponownie.
              </p>
              <Button
                size="sm"
                variant="outline"
                className="mt-3"
                onClick={() => templateQuery.refetch()}
              >
                Spróbuj ponownie
              </Button>
            </div>
          ) : !templateQuery.isSuccess ? (
            <p className="text-sm text-muted-foreground">Ładowanie szablonu…</p>
          ) : !template ? (
            <div className="rounded-lg border border-border bg-card p-4">
              <p className="text-sm text-foreground">
                Brak szablonu zaproszenia w Materiałach.
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Administrator może go dodać w zakładce Pomoc → Materiały jako
                pozycję z treścią szablonu.
              </p>
            </div>
          ) : (
            <>
              <div>
                <label
                  htmlFor="prep-invite-subject"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  Temat
                </label>
                <Input
                  id="prep-invite-subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </div>

              <div>
                <label
                  htmlFor="prep-invite-body"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  Treść
                </label>
                <Textarea
                  id="prep-invite-body"
                  rows={12}
                  className="font-mono text-xs"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  aria-describedby="prep-invite-body-hint"
                />
                <p
                  id="prep-invite-body-hint"
                  className="text-xs text-muted-foreground mt-1"
                >
                  Nazwisko kandydata jest już podstawione. Nazwę klienta,
                  stanowisko, termin i link do ogłoszenia uzupełnij ręcznie —
                  adresy ofert w NEXUSie są generowane roboczo i nie nadają się
                  do wysyłki.
                </p>
              </div>

              <PrepInviteCvReminder className="rounded border border-border bg-muted/40 p-2" />
            </>
          )}
        </DialogBody>

        <DialogFooter className="flex-wrap gap-2">
          {template && (
            <PrepInviteActions
              draft={{ subject, body }}
              onToast={onToast}
              className="mr-auto"
            />
          )}
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
