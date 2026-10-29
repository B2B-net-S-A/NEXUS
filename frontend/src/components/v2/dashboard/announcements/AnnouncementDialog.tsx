"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
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
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  editAnnouncement,
  invalidateAnnouncements,
  publishAnnouncement,
  type Announcement,
} from "@/lib/api/announcements";
import {
  ANNOUNCEMENT_BODY_MAX,
  ANNOUNCEMENT_TITLE_MAX,
  AUDIENCE_ROLE_LABELS,
  defaultVisibleUntil,
  maxVisibleUntil,
  validateAnnouncement,
  type AnnouncementForm,
} from "@/lib/announcements";
import { warsawToday } from "@/lib/warsaw-date";

const AUDIENCE_OPTIONS = [
  { value: "all", label: "Wszyscy" },
  { value: "roles", label: "Wybrane role" },
] as const;

function initialForm(edited: Announcement | null): AnnouncementForm {
  if (!edited) {
    return {
      title: "",
      body: "",
      visibleUntil: defaultVisibleUntil(),
      audience: "all",
      roles: [],
      pinned: false,
      important: false,
    };
  }
  return {
    title: edited.title,
    body: edited.body,
    visibleUntil: edited.visible_until,
    audience: edited.audience_roles.length ? "roles" : "all",
    roles: edited.audience_roles,
    pinned: edited.pinned,
    important: edited.important,
  };
}

export interface AnnouncementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ogłoszenie do poprawki; `null` = nowe. */
  edited?: Announcement | null;
  /** Role z serwera (`audience_roles` listy). */
  roles: string[];
}

/**
 * Okno „Nowe ogłoszenie” / „Popraw ogłoszenie” (28.10.2026) — Head of
 * Recruitment i administrator. Treść to zwykły tekst; „Ważne” wysyła od razu
 * dzwonek i mail obowiązkowy do odbiorców, raz na ogłoszenie.
 */
export function AnnouncementDialog({ open, onOpenChange, edited = null, roles }: AnnouncementDialogProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<AnnouncementForm>(() => initialForm(edited));
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const errors = validateAnnouncement(form);
  const shown = touched ? errors : {};
  // „Ważne” w poprawce już ogłoszonego nie dzwoni drugi raz (serwer pilnuje `notified_at`).
  const alreadyImportant = Boolean(edited?.important);
  // Kolejność z `AUDIENCE_ROLE_LABELS` (rekruterzy i DL-e na początku), nie enumu z serwera.
  const known = Object.keys(AUDIENCE_ROLE_LABELS);
  const orderedRoles = [...known.filter((r) => roles.includes(r)), ...roles.filter((r) => !known.includes(r))];
  const update = (patch: Partial<AnnouncementForm>) => setForm((current) => ({ ...current, ...patch }));
  const toggleRole = (role: string, checked: boolean) =>
    update({ roles: checked ? [...form.roles, role] : form.roles.filter((r) => r !== role) });

  const submit = async () => {
    setTouched(true);
    if (Object.keys(errors).length > 0) return;
    setSaving(true);
    try {
      const saved = edited ? await editAnnouncement(edited.id, form) : await publishAnnouncement(form);
      invalidateAnnouncements(queryClient);
      toast.showSuccess(
        saved.notified > 0
          ? `Ogłoszenie zapisane. Odbiorcy dostali powiadomienie i mail (${saved.notified}).`
          : edited
            ? "Ogłoszenie poprawione."
            : "Ogłoszenie opublikowane na pulpicie odbiorców.",
      );
      onOpenChange(false);
    } catch (err) {
      toast.showError(apiErrorMessage(err, "Nie udało się zapisać ogłoszenia."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setForm(initialForm(edited));
          setTouched(false);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent size="md" aria-describedby="announcement-desc" data-testid="announcement-dialog">
        <DialogHeader>
          <DialogTitle>{edited ? "Popraw ogłoszenie" : "Nowe ogłoszenie"}</DialogTitle>
          <DialogDescription id="announcement-desc">
            Ogłoszenie stoi na górze pulpitu odbiorców do końca dnia „widoczne do”. Przeczytane schodzi niżej.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="announcement-title" className="text-sm font-medium">
              Tytuł
            </label>
            <Input
              id="announcement-title"
              value={form.title}
              maxLength={ANNOUNCEMENT_TITLE_MAX + 20}
              placeholder="np. Piątek: Daily o 9:30 zamiast 10:00"
              invalid={Boolean(shown.title)}
              onChange={(event) => update({ title: event.target.value })}
            />
            {shown.title ? <p className="text-xs text-destructive">{shown.title}</p> : null}
          </div>
          <div className="space-y-1.5">
            <label htmlFor="announcement-body" className="text-sm font-medium">
              Treść (zwykły tekst)
            </label>
            <Textarea
              id="announcement-body"
              value={form.body}
              rows={5}
              maxLength={ANNOUNCEMENT_BODY_MAX + 50}
              aria-invalid={shown.body ? true : undefined}
              onChange={(event) => update({ body: event.target.value })}
            />
            {shown.body ? <p className="text-xs text-destructive">{shown.body}</p> : null}
          </div>
          <div className="grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)]">
            <div className="space-y-1.5">
              <label htmlFor="announcement-until" className="block text-sm font-medium">
                Widoczne do
              </label>
              <Input
                id="announcement-until"
                type="date"
                className="w-44"
                value={form.visibleUntil}
                min={warsawToday()}
                max={maxVisibleUntil()}
                invalid={Boolean(shown.visibleUntil)}
                onChange={(event) => update({ visibleUntil: event.target.value })}
              />
              {shown.visibleUntil ? <p className="text-xs text-destructive">{shown.visibleUntil}</p> : null}
            </div>
            <div className="space-y-1.5">
              <span id="announcement-audience-label" className="block text-sm font-medium">
                Odbiorcy
              </span>
              <SegmentedRadio<"all" | "roles">
                labelledBy="announcement-audience-label"
                value={form.audience}
                onChange={(audience) => update({ audience })}
                options={AUDIENCE_OPTIONS}
                size="sm"
              />
            </div>
          </div>
          {form.audience === "roles" ? (
            <fieldset className="space-y-1.5" data-testid="announcement-roles">
              <legend className="sr-only">Role odbiorców</legend>
              <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
                {orderedRoles.map((role) => (
                  <label key={role} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={form.roles.includes(role)}
                      onCheckedChange={(checked) => toggleRole(role, checked === true)}
                    />
                    {AUDIENCE_ROLE_LABELS[role] ?? role}
                  </label>
                ))}
              </div>
              {shown.roles ? <p className="text-xs text-destructive">{shown.roles}</p> : null}
            </fieldset>
          ) : null}
          <div className="space-y-2">
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                className="mt-0.5"
                checked={form.pinned}
                onCheckedChange={(checked) => update({ pinned: checked === true })}
              />
              <span>
                <span className="font-medium">Przypnij</span>
                <span className="block text-xs text-muted-foreground">Stoi nad innymi ogłoszeniami.</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                className="mt-0.5"
                checked={form.important}
                onCheckedChange={(checked) => update({ important: checked === true })}
              />
              <span>
                <span className="font-medium">Ważne</span>
                <span className="block text-xs text-muted-foreground">
                  {alreadyImportant
                    ? "Powiadomienie i mail już wyszły — poprawka nie wysyła ich drugi raz."
                    : "Odbiorcy dostaną od razu powiadomienie w dzwonku i mail, którego nie da się wyłączyć."}
                </span>
              </span>
            </label>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} loading={saving}>
            {edited ? "Zapisz poprawkę" : "Opublikuj"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
