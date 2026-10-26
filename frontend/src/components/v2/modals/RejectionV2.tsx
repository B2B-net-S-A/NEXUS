"use client";

import * as React from"react";
import { useState, useEffect } from"react";
import { AlertTriangle, Trophy } from"lucide-react";
import {
 RejectionRateField,
 type RejectionRateProfile,
} from "./RejectionRateField";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { FormField } from"@/components/ui/form-field";
import { Textarea } from"@/components/ui/textarea";
import { RadioGroup, RadioGroupItem } from"@/components/ui/radio-group";
import {
 pendingAgreement,
 signedAgreementWithContract,
 type CardAgreement,
} from "@/lib/b2b-agreement";
import type { RejectionEmailText } from "@/lib/rejection-email";
import {
 RejectionEmailField,
 type RejectionEmailFieldState,
 type RejectionEmailPeople,
} from "@/components/v2/modals/RejectionEmailField";
import {
 RejectionWorkModeField,
 type RejectionWorkModeChoice,
 type RejectionWorkModeJob,
 type RejectionWorkModeProfile,
} from "@/components/v2/modals/RejectionWorkModeField";
import {
 AutofillFeedbackField,
 parseRateInput,
} from "@/components/v2/modals/AutofillFeedbackField";
import type {
 AutofillFeedbackChoice,
 AutofillLearnedFrom,
 AutofillReason,
} from "@/lib/autofill-feedback";
import {
 HM_ALREADY_INTERVIEWED_REASON,
 WORK_MODE_MISMATCH_REASON,
 isRateTooHighReason,
 reasonNeedsDescription,
} from "@/lib/rejection-reasons";

interface RejectionReason {
 id: string;
 label: string;
 /** Klucz danych powodu — `work_mode_mismatch` otwiera pytanie o dni w biurze. */
 name?: string;
 applies_to: ("rejected" |"withdrawn")[];
}

type PreviousStageCategory ="internal" |"external" | null;

/** Lustro POST_ACCEPT_STAGES z `app/services/candidate_risk.py`. */
const POST_ACCEPT_STAGES = new Set<string>(["acceptance","negotiation","onboarding",
]);

export type CandidateOfferResponse ="pending" |"accepted" |"declined";

/** Kto zakończył proces (Pipeline v4, 0352) — przy odrzuceniu wybór, przy
 *  rezygnacji zawsze kandydat. */
export type EndedBy = "candidate" | "recruiter" | "delivery_lead" | "client";

const ENDED_BY_OPTIONS: { value: Exclude<EndedBy, "candidate">; label: string; hint: string }[] = [
 { value: "recruiter", label: "Odrzucamy my", hint: "decyzja rekrutera" },
 { value: "delivery_lead", label: "Odrzuca Delivery Lead", hint: "przegląd DL" },
 { value: "client", label: "Odrzuca klient", hint: "decyzja po stronie klienta" },
];

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 terminalType: "rejected" |"withdrawn";
 reasons: RejectionReason[];
 // Stage the candidate is coming FROM. Drives the default state of the
 //"send email" checkbox: pre-checked for external (= client-visible)
 // rejections, off for early-internal ones. Null when unknown (e.g.
 // quick-action path) — defaults to off to avoid surprise emails.
 previousStageCategory?: PreviousStageCategory;
 // Phase 17 (migracja 0068): konkretny stage z którego kandydat wychodzi.
 // Gdy ∈ {acceptance, negotiation, onboarding} ORAZ terminalType='withdrawn',
 // pokazujemy radio `candidate_offer_response` żeby odróżnić post-accept
 // dropout od zwykłego wycofania.
 previousStage?: string | null;
 onConfirm: (
 reasonId: string,
 notes: string,
 sendRejectionEmail: boolean | null,
 candidateOfferResponse?: CandidateOfferResponse | null,
 // Wolny tekst powodu — przekazywany tylko w trybie fallback (brak
 // zdefiniowanych powodów). Backend przyjmuje go jako `rejection_reason`.
 freeReason?: string,
 endedBy?: EndedBy,
 /** Id niepodpisanej umowy z Generatora do anulowania po ruchu (04.10.2026). */
 cancelAgreementId?: number | null,
 /** Temat i treść maila poprawione w podglądzie (jedna osoba, 13.10.2026);
  *  `null` — treść domyślna. */
 emailText?: RejectionEmailText | null,
 /** Powód „Nie akceptuje trybu pracy” (14.10.2026): ile dni w biurze
  *  kandydat akceptuje i czy zapisać to na profilu; `null` przy innym powodzie. */
 workMode?: RejectionWorkModeChoice | null,
 /** Osoba od systemu (23.10.2026): powód dla systemu; `null`, gdy okno
  *  go nie pytało (żadna osoba od systemu z „Nowych”/„Screeningu”). */
 autofill?: AutofillFeedbackChoice | null
 ) => void;
 /** Wstępny wybór „kto kończy" (np. upuszczenie na „Odrzucony przez klienta"). */
 initialEndedBy?: Exclude<EndedBy, "candidate"> | null;
 /** „Odrzuca Delivery Lead" widzi tylko admin, DL i Head of Recruitment. */
 canEndAsDeliveryLead?: boolean;
 /** Czy osoba była widoczna dla klienta — ta sama reguła co serwer
  *  (`lib/rejection-email.ts`). Podane wygrywa z `previousStageCategory`,
  *  które mówi o kategorii kolumny, a nie o tym, co widział klient
  *  (runda 9, R9-N11-2: „CV wysłane" ma kategorię `internal`). */
 emailAvailable?: boolean;
 /** Notatka wstawiona przy otwarciu (np. „Odpada, gdy…” z wymagań ruchu).
  *  Czytana tylko w chwili otwarcia — nie nadpisuje tego, co ktoś już pisze. */
 initialNotes?: string | null;
 /** Umowa z Generatora tej pary (tylko przy jednej osobie). Niepodpisaną
  *  domyślnie anulujemy, przy podpisanej z kontraktem prowadzimy do
  *  „Zakończ współpracę” (decyzja Artura 04.10.2026). */
 agreement?: CardAgreement | null;
 /** Jedna osoba: kogo zamykasz (13.10.2026). Przy przechodzeniu z panelu
  *  osoby od razu do następnej łatwo pomylić osoby — okno to ostatnie
  *  miejsce, gdzie to widać. */
 subject?: { name: string; stageLabel?: string | null } | null;
 /** Okno otwarte z panelu osoby: kogo panel pokaże po potwierdzeniu.
  *  `null` — to ostatnia osoba, panel się zamknie. Bez propu (kilka osób,
  *  karta, przeciągnięcie) okno niczego nie zapowiada. */
 nextPerson?: { name: string; stageLabel: string } | null;
 /** Odrzucana osoba jest championem (D7, 15.10.2026): co stanie się
  *  z rekrutacją — zostają inni championi albo wraca „Szukamy”. Liczy
  *  `championRemovalOutcome` z detalu rekrutacji; `null` = bez linii. */
 championNotice?: string | null;
 /** Rekrutacja i odrzucane osoby — podgląd maila odrzucenia przed wysyłką
  *  (13.10.2026). Bez propu okno pokazuje sam checkbox. */
 emailPreview?: RejectionEmailPeople | null;
 /** Zapis ruchu w toku — „Potwierdź” zablokowany, bo drugi klik wysłałby
  *  drugi ruch (z panelu osoby już przy następnej osobie; audyt 13.10.2026). */
 pending?: boolean;
 /** Tryb pracy rekrutacji — pytanie przy „Nie akceptuje trybu pracy” pokazuje
  *  tylko mniej dni, niż wymaga rekrutacja. Bez propu: 0–4 dni. */
 workModeJob?: RejectionWorkModeJob | null;
 /** Tryb pracy z profilu (tylko przy jednej osobie) — „Teraz na profilu: …”. */
 profileWorkMode?: RejectionWorkModeProfile | null;
 /** „Stawka od” z profilu (tylko przy jednej osobie) — przy „Za wysokie
  *  oczekiwania finansowe”. */
 profileRate?: RejectionRateProfile | null;
 /** Wśród odrzucanych jest osoba od systemu z „Nowych”/„Screeningu”
  *  (silnik „Nowi na 20”, 23.10.2026) — okno pyta o powód dla systemu.
  *  `rateKnown`: czy system znał stawkę (jedna osoba). */
 autofill?: { rateKnown: boolean; several: boolean } | null;
}

const EMAIL_STATE_IDLE: RejectionEmailFieldState = {
 blocked: false,
 invalid: false,
 text: null,
};

const TYPE_LABEL: Record<string, string> = {
 rejected: "Zamknij proces — odrzucenie",
 withdrawn: "Kandydat zrezygnował",
};

export function RejectionV2({
 open,
 onOpenChange,
 terminalType,
 reasons,
 previousStageCategory = null,
 previousStage = null,
 onConfirm,
 initialEndedBy = null,
 canEndAsDeliveryLead = false,
 emailAvailable: emailAvailableProp,
 initialNotes = null,
 agreement = null,
 subject = null,
 nextPerson,
 championNotice = null,
 emailPreview = null,
 pending = false,
 workModeJob = null,
 profileWorkMode,
 profileRate,
 autofill = null,
}: Props) {
 // Notatkę startową czytamy tylko przy otwarciu (efekt resetu niżej) —
 // zmiana propa przy otwartym oknie nie kasuje tego, co ktoś już wpisał.
 const initialNotesRef = React.useRef(initialNotes);
 useEffect(() => {
 initialNotesRef.current = initialNotes;
 }, [initialNotes]);
 const [reasonId, setReasonId] = useState("");
 const [endedBy, setEndedBy] = useState<Exclude<EndedBy, "candidate">>(
 initialEndedBy ?? "recruiter"
 );
 const [notes, setNotes] = useState("");
 const unsignedAgreement = pendingAgreement(agreement);
 const signedAgreement = signedAgreementWithContract(agreement);
 const [cancelAgreement, setCancelAgreement] = useState(true);

 // Mail odrzucenia dotyczy tylko `rejected` z etapu widocznego dla klienta
 // (wycofanie inicjuje kandydat). Od 17.09.2026 to OPT-IN: checkbox
 // domyślnie ODZNACZONY, serwer planuje wysyłkę wyłącznie przy `true`.
 const emailAvailable =
 terminalType === "rejected" &&
 (emailAvailableProp ?? previousStageCategory === "external");
 const [sendEmail, setSendEmail] = useState<boolean>(false);
 const [emailState, setEmailState] =
 useState<RejectionEmailFieldState>(EMAIL_STATE_IDLE);

 // Phase 17 — show offer response radio only for withdrawn FROM post-accept.
 const offerResponseRequired =
 terminalType === "withdrawn" &&
 !!previousStage &&
 POST_ACCEPT_STAGES.has(previousStage);
 const [offerResponse, setOfferResponse] =
 useState<CandidateOfferResponse |"">("");

 // Wolny tekst powodu — używany TYLKO gdy dla danego typu terminala nie ma
 // żadnych zdefiniowanych powodów (np. job bez pipeline_template_id i bez
 // szablonu domyślnego). Bez tego radio byłoby puste, reasonId zostawałby
 // pusty, a przycisk "Potwierdź" byłby trwale zablokowany.
 const [freeReason, setFreeReason] = useState("");

 // „Nie akceptuje trybu pracy” (D2–D3): domyślnie „Tylko zdalnie” i zapis
 // na profilu — najświeższa deklaracja z rozmowy nadpisuje profil.
 const [officeDays, setOfficeDays] = useState(0);
 const [saveWorkMode, setSaveWorkMode] = useState(true);
 // „Za wysokie oczekiwania finansowe” (26.10.2026): ile teraz chce.
 const [newRate, setNewRate] = useState("");
 const [newRateIsMinimum, setNewRateIsMinimum] = useState(true);
 // Osoba od systemu (23.10.2026): powód dla systemu.
 const [autofillLearnedFrom, setAutofillLearnedFrom] = useState<AutofillLearnedFrom | null>(null);
 const [autofillReason, setAutofillReason] = useState<AutofillReason | null>(null);
 const [autofillRate, setAutofillRate] = useState("");

 // Reset defaults when modal re-opens (e.g. user bails, opens again).
 useEffect(() => {
 if (open) {
 setReasonId("");
 setNotes(initialNotesRef.current ?? "");
 setSendEmail(false);
 setEmailState(EMAIL_STATE_IDLE);
 setOfferResponse("");
 setFreeReason("");
 setEndedBy(initialEndedBy ?? "recruiter");
 setCancelAgreement(true);
 setOfficeDays(0);
 setSaveWorkMode(true);
 setNewRate("");
 setNewRateIsMinimum(true);
 setAutofillLearnedFrom(null);
 setAutofillReason(null);
 setAutofillRate("");
 }
 }, [open, initialEndedBy]);
 const endedByValue: EndedBy = terminalType === "withdrawn" ? "candidate" : endedBy;
 const endedByOptions = ENDED_BY_OPTIONS.filter(
 (o) => o.value !== "delivery_lead" || canEndAsDeliveryLead || initialEndedBy === "delivery_lead"
 );

 const filtered = reasons.filter((r) => r.applies_to.includes(terminalType));
 const hasReasons = filtered.length > 0;
 const chosenReason = filtered.find((r) => r.id === reasonId);
 const workModeReason = chosenReason?.name === WORK_MODE_MISMATCH_REASON;
 const rateReason = isRateTooHighReason(chosenReason);
 // 20.10.2026: „Inne” i „Już po rozmowie u tego hiring managera” bez opisu
 // zostawiały w historii samo słowo — notatka jest wtedy opisem powodu.
 const autofillAsked = terminalType === "rejected" && autofill != null;
 // „Inne” dla systemu też potrzebuje opisu (serwer: 422 bez `notes`).
 const descriptionRequired =
 (hasReasons && reasonNeedsDescription(chosenReason)) ||
 (autofillAsked && autofillReason === "other");
 const autofillChoice: AutofillFeedbackChoice | null =
 autofillAsked && autofillReason && autofillLearnedFrom
 ? {
 reason: autofillReason,
 learnedFrom: autofillLearnedFrom,
 rateHourly:
 autofillReason === "too_expensive" && !autofill?.several
 ? parseRateInput(autofillRate)
 : null,
 }
 : null;
 const hmInterviewed = chosenReason?.name === HM_ALREADY_INTERVIEWED_REASON;
 const several = (emailPreview?.people.length ?? 1) > 1;

 const handleConfirm = () => {
 // Zawsze jawny boolean — serwer planuje mail WYŁĄCZNIE przy `true`.
 const emailFlag: boolean = emailAvailable && sendEmail && !emailState.blocked;
 const emailText = emailFlag ? emailState.text : null;
 const cancelAgreementId =
 unsignedAgreement && cancelAgreement ? unsignedAgreement.id : null;
 const offerResponseValue: CandidateOfferResponse | null =
 offerResponseRequired && offerResponse ? offerResponse : null;
 if (hasReasons) {
 onConfirm(
 reasonId,
 notes,
 emailFlag,
 offerResponseValue,
 undefined,
 endedByValue,
 cancelAgreementId,
 emailText,
 workModeReason
 ? { maxOnsiteDays: officeDays, saveToProfile: saveWorkMode }
 : null,
 autofillChoice
 );
 return;
 }
 // Fallback wolnego tekstu — brak zdefiniowanych powodów. Powód trafia do
 // `notes` (zapisywane + widoczne w timeline), a dodatkowo przekazujemy go
 // jako `freeReason` -> backend przyjmuje to jako `rejection_reason`, co
 // spełnia walidację ruchu na etap terminalny. reasonId zostaje pusty.
 const reasonText = freeReason.trim();
 const combinedNotes = notes.trim()
 ? `${reasonText}\n\n${notes.trim()}`
 : reasonText;
 onConfirm(
 "",
 combinedNotes,
 emailFlag,
 offerResponseValue,
 reasonText,
 endedByValue,
 cancelAgreementId,
 emailText,
 null,
 autofillChoice
 );
 };

 const submitDisabled =
 pending ||
 (hasReasons ? !reasonId : !freeReason.trim()) ||
 (descriptionRequired && !notes.trim()) ||
 (offerResponseRequired && !offerResponse) ||
 (autofillAsked && autofillChoice == null) ||
 (emailAvailable && sendEmail && emailState.invalid);

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="md">
 <DialogHeader>
 <div className="flex items-center gap-2">
 <AlertTriangle className="h-4 w-4 text-primary" />
 <DialogTitle>{TYPE_LABEL[terminalType]}</DialogTitle>
 </div>
 <DialogDescription>
 Podaj powód — pomoże to raportom o lejku rekrutacyjnym.
 </DialogDescription>
 {subject ? (
 <p className="rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-sm font-medium text-foreground">
 {subject.stageLabel ? `${subject.name} · ${subject.stageLabel}` : subject.name}
 </p>
 ) : null}
 {championNotice ? (
 <p
 className="flex items-start gap-1.5 rounded-md bg-medal-gold px-2.5 py-1.5 text-sm text-medal-gold-foreground"
 data-testid="rejection-champion-notice"
 >
 <Trophy className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
 {championNotice}
 </p>
 ) : null}
 </DialogHeader>

 <DialogBody>
 <div className="space-y-3">
 {terminalType === "rejected" && (
 <FormField label="Kto kończy?" required>
 <RadioGroup
 value={endedBy}
 onValueChange={(v) => setEndedBy(v as Exclude<EndedBy, "candidate">)}
 className="grid gap-2 sm:grid-cols-3"
 >
 {endedByOptions.map((o) => (
 <label
 key={o.value}
 className={`flex cursor-pointer flex-col gap-0.5 rounded-md border p-2 text-sm ${
 endedBy === o.value ? "border-primary bg-primary/5" : "border-border hover:bg-accent"
 }`}
 >
 <span className="flex items-center gap-2 font-medium">
 <RadioGroupItem value={o.value} />
 {o.label}
 </span>
 <span className="pl-6 text-xs text-muted-foreground">{o.hint}</span>
 </label>
 ))}
 </RadioGroup>
 </FormField>
 )}
 <FormField
 label="Powód"
 required
 description={
 hasReasons
 ? undefined
 : "Brak zdefiniowanych powodów w szablonie — wpisz powód ręcznie."
 }
 >
 {hasReasons ? (
 <RadioGroup value={reasonId} onValueChange={setReasonId}>
 {filtered.map((r) => (
 <React.Fragment key={r.id}>
 <label className="flex items-center gap-2 text-sm cursor-pointer rounded-md p-1.5 hover:bg-primary/10">
 <RadioGroupItem value={r.id} />
 <span>{r.label}</span>
 </label>
 {r.id === reasonId && workModeReason ? (
 <RejectionWorkModeField
 job={workModeJob}
 profile={several ? undefined : profileWorkMode}
 several={several}
 days={officeDays}
 onDaysChange={setOfficeDays}
 saveToProfile={saveWorkMode}
 onSaveToProfileChange={setSaveWorkMode}
 />
 ) : null}
 {r.id === reasonId && rateReason && !several ? (
 <RejectionRateField
 profile={profileRate}
 rate={newRate}
 onRateChange={setNewRate}
 isMinimum={newRateIsMinimum}
 onIsMinimumChange={setNewRateIsMinimum}
 />
 ) : null}
 </React.Fragment>
 ))}
 </RadioGroup>
 ) : (
 <Textarea
 value={freeReason}
 onChange={(e) => setFreeReason(e.target.value)}
 rows={2}
 placeholder="Np. brak wymaganych kompetencji technicznych."
 />
 )}
 </FormField>
 {autofillAsked && autofill ? (
 <AutofillFeedbackField
 learnedFrom={autofillLearnedFrom}
 onLearnedFromChange={setAutofillLearnedFrom}
 reason={autofillReason}
 onReasonChange={setAutofillReason}
 rate={autofillRate}
 onRateChange={setAutofillRate}
 rateKnown={autofill.rateKnown}
 several={autofill.several}
 />
 ) : null}
 {offerResponseRequired && (
 <FormField
 label="Reakcja kandydata na ofertę"
 description="Pomaga w analizie ryzyka — wycofanie po akceptacji to mocny sygnał."
 required
 >
 <RadioGroup
 value={offerResponse}
 onValueChange={(v) =>
 setOfferResponse(v as CandidateOfferResponse)
 }
 >
 {(
 [
 { v: "declined", label: "Wycofał się PO akceptacji oferty" },
 { v: "accepted", label: "Zaakceptował, potem się wycofał z innego powodu" },
 { v: "pending", label: "Jeszcze nie odpowiedział na ofertę" },
 ] as const
 ).map(({ v, label }) => (
 <label
 key={v}
 className="flex items-center gap-2 text-sm cursor-pointer rounded-md p-1.5 hover:bg-primary/10"
 >
 <RadioGroupItem value={v} />
 <span>{label}</span>
 </label>
 ))}
 </RadioGroup>
 </FormField>
 )}
 <FormField
 label={
 hmInterviewed
 ? "Na jakiej rozmowie i kiedy?"
 : descriptionRequired
 ? "Opisz powód"
 : "Notatka (opcjonalnie)"
 }
 required={descriptionRequired}
 description={
 descriptionRequired
 ? "Bez opisu w historii kandydata zostaje samo słowo."
 : "Np. kontekst decyzji, follow-up."
 }
 >
 <Textarea
 value={notes}
 onChange={(e) => setNotes(e.target.value)}
 rows={3}
 placeholder={
 hmInterviewed
 ? "Np. Rating & Limit Management, rozmowa 21.08 — manager jej nie chce drugi raz."
 : "Kandydat dostał lepszą ofertę finansową gdzie indziej."
 }
 />
 </FormField>

 {unsignedAgreement && (
 <label
 data-testid="rejection-cancel-agreement"
 className="flex items-start gap-2 rounded-md p-1.5 text-sm cursor-pointer hover:bg-primary/10"
 >
 <input
 type="checkbox"
 className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
 checked={cancelAgreement}
 onChange={(e) => setCancelAgreement(e.target.checked)}
 />
 <span>
 Anuluj umowę {unsignedAgreement.number} w rejestrze (nie doszła do skutku).
 Numer zostaje zużyty.
 </span>
 </label>
 )}
 {signedAgreement && (
 <div
 data-testid="rejection-signed-agreement"
 className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
 >
 Umowa {signedAgreement.number} jest podpisana i kontrakt trwa. Zamknięcie
 karty nie kończy współpracy —{" "}
 <a
 className="font-medium text-primary underline-offset-2 hover:underline"
 href={`/contracts/${signedAgreement.contract_id}`}
 target="_blank"
 rel="noreferrer"
 >
 zakończ ją w kontrakcie
 </a>
 . Bez tego sprawa trafi do Delivery Leada na pulpit.
 </div>
 )}

 {emailAvailable && (
 <RejectionEmailField
 preview={emailPreview}
 checked={sendEmail}
 onCheckedChange={setSendEmail}
 onStateChange={setEmailState}
 />
 )}
 </div>
 </DialogBody>

 <DialogFooter>
 {nextPerson !== undefined ? (
 <p className="min-w-0 self-center text-xs text-muted-foreground sm:mr-auto">
 {nextPerson
 ? `Dalej: ${nextPerson.name} · ${nextPerson.stageLabel}`
 : "To ostatnia osoba w kolejce — panel się zamknie."}
 </p>
 ) : null}
 <Button variant="ghost" onClick={() => onOpenChange(false)}>
 Anuluj
 </Button>
 <Button
 variant="destructive"
 disabled={submitDisabled}
 onClick={handleConfirm}
 >
 Potwierdź
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
}
