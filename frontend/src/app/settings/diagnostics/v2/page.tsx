"use client";

import Link from"next/link";
import { useEffect, useState } from"react";
import {
 Archive,
 ArrowRight,
 Building2,
 Check,
 ChevronDown,
 Command as CommandIcon,
 Download,
 Edit,
 FileText,
 Filter,
 Info,
 Mail,
 Plus,
 Search,
 Send,
 Settings,
 Star,
 Trash2,
 User,
 Users,
} from"lucide-react";
import { RequireRole } from"@/components/RequireRole";
import {
 Avatar,
 AvatarFallback,
 AvatarImage,
 Badge,
 Button,
 Card,
 CardContent,
 CardDescription,
 CardFooter,
 CardHeader,
 CardTitle,
 Checkbox,
 Command,
 CommandDialog,
 CommandEmpty,
 CommandGroup,
 CommandInput,
 CommandItem,
 CommandList,
 CommandSeparator,
 CommandShortcut,
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
 DialogTrigger,
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuLabel,
 DropdownMenuSeparator,
 DropdownMenuTrigger,
 FormField,
 Input,
 Kbd,
 Label,
 Popover,
 PopoverContent,
 PopoverTrigger,
 RadioGroup,
 RadioGroupItem,
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
 Separator,
 Sheet,
 SheetBody,
 SheetContent,
 SheetFooter,
 SheetHeader,
 SheetTitle,
 SheetTrigger,
 Switch,
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
 Tabs,
 TabsContent,
 TabsList,
 TabsTrigger,
 Textarea,
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from"@/components/ui";

export default function V2ShowcasePage() {
 const [cmdkOpen, setCmdkOpen] = useState(false);

 return (
 <RequireRole
 minRole="admin"
 fallback={<div className="p-6 text-sm text-muted-foreground">Widok tylko dla admin.</div>}
 >
 <TooltipProvider delayDuration={200}>
 <div className="mx-auto max-w-7xl p-8 space-y-14">
 <Header />

 <ColorsSection />
 <TypographySection />
 <ButtonsSection />
 <InputsSection />
 <FormControlsSection />
 <BadgesSection />
 <AvatarsSection />
 <SeparatorKbdSection />
 <TabsSection />
 <TableSection />
 <CardsSection />
 <DialogSheetSection />
 <DropdownPopoverTooltipSection />
 <CommandSection setCmdkOpen={setCmdkOpen} cmdkOpen={cmdkOpen} />

 <footer className="pt-8 border-t border-border text-xs text-muted-foreground">
 Phase 1 — Primitywy. Rozbudowa w kolejnych fazach. Growing target dla
 visual regression.
 </footer>
 </div>
 </TooltipProvider>
 </RequireRole>
 );
}

// ── Header ─────────────────────────────────────────────────────────────
function Header() {
 return (
 <header className="space-y-2">
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Dynaminds · Nexus
 </p>
 <h1 className="text-3xl font-extrabold tracking-[-0.02em] text-foreground font-[var(--font-poppins)]">
 UI Showcase
 </h1>
 <p className="text-sm text-foreground max-w-2xl">
 Single-scroll render of every primitive and page fragment in the Dynaminds
 design system. Visual regression target for Playwright.
 </p>
 <div className="mt-4 flex items-center gap-3 text-sm">
 <Badge variant="soft" uppercase size="sm">
 Dynaminds v2 — live
 </Badge>
 <Link
 href="/settings"
 className="text-xs text-muted-foreground hover:text-primary"
 >
 ← Ustawienia
 </Link>
 </div>
 </header>
 );
}

// ── Section scaffold ───────────────────────────────────────────────────
function Section({ num, title, children }: { num: number; title: string; children: React.ReactNode }) {
 return (
 <section className="space-y-4">
 <h2 className="text-xl font-bold text-foreground font-[var(--font-poppins)]">
 {num}. {title}
 </h2>
 <div className="space-y-4">{children}</div>
 </section>
 );
}

function SubRow({ label, children }: { label: string; children: React.ReactNode }) {
 return (
 <div className="space-y-2">
 <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
 {label}
 </h3>
 <div className="flex flex-wrap items-center gap-3 bg-card p-4 rounded-lg border border-border">
 {children}
 </div>
 </div>
 );
}

// ── 1. Colors ──────────────────────────────────────────────────────────
function ColorsSection() {
 return (
 <Section num={1} title="Colors & tokens">
 <SwatchGroup
 title="Deep Plum — chrome (sidebar, topbar, primary backgrounds)"
 swatches={[
 ["plum-50","#F7F5F6"],
 ["plum-100","#EAE6E9"],
 ["plum-200","#CEC6CD"],
 ["plum-300","#B1A5AF"],
 ["plum-400","#87778C"],
 ["plum-500","#5A4B5A"],
 ["plum-600","#433644"],
 ["plum-700","#2E1A2B"],
 ["plum-800","#1F1220"],
 ["plum-900","#15090E"],
 ["plum-950","#0A0407"],
 ]}
 />
 <SwatchGroup
 title="Burgundy — accent (CTAs, active states, alerts)"
 swatches={[
 ["burgundy-50","#FBF2F3"],
 ["burgundy-100","#F4DDE0"],
 ["burgundy-200","#E9B9BF"],
 ["burgundy-300","#DB939B"],
 ["burgundy-400","#C16F7B"],
 ["burgundy-500","#A63A4A"],
 ["burgundy-600","#8B1A2B"],
 ["burgundy-700","#6B1120"],
 ["burgundy-800","#4D0A16"],
 ["burgundy-900","#310711"],
 ["burgundy-950","#1A0308"],
 ]}
 />
 <SwatchGroup
 title="Warm Cream — canvas (body bg)"
 swatches={[
 ["cream-50","#FBF9F6"],
 ["cream-100","#F8F5EF"],
 ["cream-200","#F0EBE3"],
 ["cream-300","#E8E4DE"],
 ["cream-400","#D8CFBF"],
 ["cream-500","#B5AA9A"],
 ["cream-600","#92897B"],
 ["cream-700","#6F685E"],
 ["cream-800","#4C4841"],
 ["cream-900","#2A2824"],
 ["cream-950","#15130F"],
 ]}
 />

 <div className="pt-2">
 <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground mb-3">
 Semantic aliases
 </h3>
 <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
 <SemanticSwatch name="canvas" varName="--bg-canvas" />
 <SemanticSwatch name="surface" varName="--bg-surface" />
 <SemanticSwatch name="chrome" varName="--bg-chrome" />
 <SemanticSwatch name="accent" varName="--accent" />
 <SemanticSwatch name="accent-strong" varName="--accent-strong" />
 <SemanticSwatch name="accent-soft" varName="--accent-soft" />
 <SemanticSwatch name="subtle (border)" varName="--border-subtle" />
 <SemanticSwatch name="muted (text)" varName="--text-muted" />
 </div>
 </div>
 </Section>
 );
}

function SwatchGroup({ title, swatches }: { title: string; swatches: [string, string][] }) {
 return (
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground mb-2">
 {title}
 </h3>
 <div className="grid grid-cols-6 md:grid-cols-11 gap-1.5">
 {swatches.map(([name, hex]) => (
 <div key={name} className="space-y-1">
 <div
 className="aspect-square rounded-md border border-border"
 style={{ background: hex }}
 title={`${name} · ${hex}`}
 />
 <div className="text-[10px] font-mono text-muted-foreground truncate">
 {name}
 </div>
 </div>
 ))}
 </div>
 </div>
 );
}

function SemanticSwatch({ name, varName }: { name: string; varName: string }) {
 return (
 <div className="rounded-lg border border-border overflow-hidden">
 <div
 className="h-12"
 style={{ background: `hsl(var(${varName}))` }}
 aria-label={name}
 />
 <div className="px-3 py-2">
 <div className="text-xs font-semibold text-foreground">{name}</div>
 <code className="text-[10px] font-mono text-muted-foreground">
 hsl(var({varName}))
 </code>
 </div>
 </div>
 );
}

// ── 2. Typography ──────────────────────────────────────────────────────
function TypographySection() {
 return (
 <Section num={2} title="Typography">
 <div className="space-y-3 bg-card p-6 rounded-lg border border-border">
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Eyebrow · Poppins 600 · tracking 0.22em
 </p>
 <h1
 className="font-[var(--font-poppins)] font-extrabold text-foreground"
 style={{ fontSize:"clamp(2.88rem, 4.49vw, 7.58rem)", lineHeight: 1.02, letterSpacing:"-0.025em" }}
 >
 Define tomorrow.
 </h1>
 <h2 className="font-[var(--font-poppins)] font-extrabold text-3xl text-foreground tracking-[-0.02em]">
 Heading 2 — the trinity
 </h2>
 <h3 className="font-[var(--font-poppins)] font-bold text-2xl text-foreground">
 Heading 3 — chamber tint
 </h3>
 <h4 className="font-[var(--font-poppins)] font-semibold text-xl text-foreground">
 Heading 4 — subsection
 </h4>
 <p className="font-[var(--font-inter)] text-base text-foreground">
 Body · Inter 400 · Pasywna obrona to za mało. Dostarczamy proaktywny Offensive &amp;
 Intel. Nie czekamy, aż ktoś nas złamie — działamy pierwsi.
 </p>
 <p className="font-[var(--font-inter)] text-sm text-muted-foreground">
 Muted body · Inter 400 · We don&apos;t do standard. We set the standard.
 </p>
 </div>
 </Section>
 );
}

// ── 3. Buttons ─────────────────────────────────────────────────────────
function ButtonsSection() {
 return (
 <Section num={3} title="Buttons">
 <SubRow label="Variants · size md">
 <Button variant="primary">Primary CTA</Button>
 <Button variant="secondary">Secondary</Button>
 <Button variant="outline">Outline</Button>
 <Button variant="ghost">Ghost</Button>
 <Button variant="tertiary">Tertiary link</Button>
 <Button variant="destructive">Destructive</Button>
 </SubRow>
 <SubRow label="Sizes">
 <Button size="sm" variant="primary">Small</Button>
 <Button size="md" variant="primary">Medium</Button>
 <Button size="lg" variant="primary">Large</Button>
 <Button size="icon" variant="primary" aria-label="Add">
 <Plus className="h-4 w-4" />
 </Button>
 <Button size="icon-sm" variant="ghost" aria-label="Settings">
 <Settings className="h-3.5 w-3.5" />
 </Button>
 </SubRow>
 <SubRow label="Composition · leading/trailing icons">
 <Button variant="primary">
 <Plus className="h-4 w-4" />
 Nowy kandydat
 </Button>
 <Button variant="secondary">
 Zobacz wszystkich
 <ArrowRight className="h-4 w-4" />
 </Button>
 <Button variant="outline">
 <Download className="h-4 w-4" />
 Eksportuj CSV
 </Button>
 <Button variant="ghost">
 <Edit className="h-4 w-4" />
 Edytuj
 </Button>
 </SubRow>
 <SubRow label="States · loading / disabled">
 <Button variant="primary" loading>
 Zapisuję…
 </Button>
 <Button variant="primary" disabled>
 Disabled
 </Button>
 <Button variant="destructive" disabled>
 <Trash2 className="h-4 w-4" /> Disabled danger
 </Button>
 </SubRow>
 </Section>
 );
}

// ── 4. Inputs & FormFields ─────────────────────────────────────────────
function InputsSection() {
 const [query, setQuery] = useState("");
 return (
 <Section num={4} title="Inputs & Form Fields">
 <SubRow label="Input states">
 <div className="space-y-3 w-full max-w-md">
 <FormField label="Email" htmlFor="demo-email" required>
 <Input id="demo-email" placeholder="anna@dynaminds.eu" type="email" />
 </FormField>
 <FormField
 label="Hasło"
 htmlFor="demo-pass"
 description="Min. 12 znaków, w tym cyfra i znak specjalny."
 >
 <Input id="demo-pass" type="password" defaultValue="secret123" />
 </FormField>
 <FormField
 label="Telefon"
 htmlFor="demo-phone"
 error="Niepoprawny format numeru"
 >
 <Input id="demo-phone" invalid defaultValue="abc" />
 </FormField>
 <FormField label="Disabled" htmlFor="demo-dis">
 <Input id="demo-dis" disabled defaultValue="Nie edytuj" />
 </FormField>
 </div>
 </SubRow>
 <SubRow label="Input with icons">
 <div className="space-y-3 w-full max-w-md">
 <Input
 placeholder="Szukaj kandydatów…"
 leadingIcon={<Search className="h-4 w-4" />}
 value={query}
 onChange={(e) => setQuery(e.target.value)}
 />
 <Input
 placeholder="Filtruj stanowisko"
 leadingIcon={<Filter className="h-4 w-4" />}
 trailingIcon={<Kbd>⌘K</Kbd>}
 />
 </div>
 </SubRow>
 <SubRow label="Textarea">
 <div className="w-full max-w-md">
 <FormField
 label="Notatki rekrutera"
 htmlFor="demo-notes"
 description="Kontekst rozmowy, deal-breakers, follow-upy."
 >
 <Textarea
 id="demo-notes"
 placeholder="Kandydat ma 7 lat doświadczenia w Kubernetes…"
 rows={4}
 />
 </FormField>
 </div>
 </SubRow>
 <SubRow label="Select">
 <div className="w-full max-w-md">
 <FormField label="Etap procesu" htmlFor="demo-stage">
 <Select>
 <SelectTrigger id="demo-stage">
 <SelectValue placeholder="Wybierz etap…" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="sourcing">Sourcing</SelectItem>
 <SelectItem value="prep_call">Prep call</SelectItem>
 <SelectItem value="screening">Screening</SelectItem>
 <SelectItem value="cv_sent">CV wysłane</SelectItem>
 <SelectItem value="client_interview">Rozmowa z klientem</SelectItem>
 <SelectItem value="acceptance">Akceptacja</SelectItem>
 <SelectItem value="negotiation">Negocjacje</SelectItem>
 <SelectItem value="onboarding">Onboarding</SelectItem>
 </SelectContent>
 </Select>
 </FormField>
 </div>
 </SubRow>
 </Section>
 );
}

// ── 5. Checkbox / Radio / Switch ───────────────────────────────────────
function FormControlsSection() {
 const [checked, setChecked] = useState<boolean |"indeterminate">(true);
 const [radio, setRadio] = useState("remote");
 const [compact, setCompact] = useState(false);
 return (
 <Section num={5} title="Checkbox · Radio · Switch">
 <SubRow label="Checkbox">
 <div className="flex flex-col gap-3">
 <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
 <Checkbox
 checked={checked}
 onCheckedChange={(v) => setChecked(v)}
 />
 Interactive — NDA podpisana
 </label>
 <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
 <Checkbox checked="indeterminate" />
 Indeterminate (2 of 3 selected)
 </label>
 <label className="inline-flex items-center gap-2 text-sm text-muted-foreground cursor-not-allowed">
 <Checkbox disabled />
 Disabled
 </label>
 </div>
 </SubRow>
 <SubRow label="Radio group">
 <RadioGroup value={radio} onValueChange={setRadio} className="gap-2">
 <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
 <RadioGroupItem value="remote" />
 Remote
 </label>
 <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
 <RadioGroupItem value="hybrid" />
 Hybrid
 </label>
 <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
 <RadioGroupItem value="onsite" />
 Onsite
 </label>
 </RadioGroup>
 </SubRow>
 <SubRow label="Switch · density toggle">
 <label className="inline-flex items-center gap-3 text-sm cursor-pointer">
 <Switch checked={compact} onCheckedChange={setCompact} />
 Compact density ({compact ?"on" :"off"})
 </label>
 </SubRow>
 </Section>
 );
}

// ── 6. Badges ──────────────────────────────────────────────────────────
function BadgesSection() {
 return (
 <Section num={6} title="Badges">
 <SubRow label="Variants">
 <Badge variant="neutral">Neutral</Badge>
 <Badge variant="plum">Plum</Badge>
 <Badge variant="burgundy">Burgundy</Badge>
 <Badge variant="soft">Soft</Badge>
 <Badge variant="success">
 <Check className="h-3 w-3" />
 Sukces
 </Badge>
 <Badge variant="warning">Warning</Badge>
 <Badge variant="danger">Danger</Badge>
 <Badge variant="info">Info</Badge>
 <Badge variant="outline">Outline</Badge>
 </SubRow>
 <SubRow label="Sizes · uppercase">
 <Badge size="sm" variant="soft" uppercase>
 Sourcing
 </Badge>
 <Badge size="md" variant="plum" uppercase>
 Pipeline
 </Badge>
 <Badge size="lg" variant="burgundy">
 Deal-breaker
 </Badge>
 </SubRow>
 </Section>
 );
}

// ── 7. Avatars ─────────────────────────────────────────────────────────
function AvatarsSection() {
 return (
 <Section num={7} title="Avatars">
 <SubRow label="Sizes with fallback initials">
 <Avatar size="xs"><AvatarFallback>AK</AvatarFallback></Avatar>
 <Avatar size="sm"><AvatarFallback>MN</AvatarFallback></Avatar>
 <Avatar size="md"><AvatarFallback>KP</AvatarFallback></Avatar>
 <Avatar size="lg"><AvatarFallback>OL</AvatarFallback></Avatar>
 <Avatar size="xl"><AvatarFallback>DZ</AvatarFallback></Avatar>
 </SubRow>
 <SubRow label="With image + fallback while loading">
 <Avatar size="lg">
 <AvatarImage src="https://i.pravatar.cc/120?img=32" alt="Anna" />
 <AvatarFallback>AK</AvatarFallback>
 </Avatar>
 <Avatar size="md">
 <AvatarImage src="https://i.pravatar.cc/120?img=14" alt="Marcin" />
 <AvatarFallback>MN</AvatarFallback>
 </Avatar>
 </SubRow>
 </Section>
 );
}

// ── 8. Separator + Kbd ─────────────────────────────────────────────────
function SeparatorKbdSection() {
 return (
 <Section num={8} title="Separator · Kbd">
 <div className="bg-card p-4 rounded-lg border border-border space-y-3">
 <p className="text-sm">Poziomy separator pod spodem ↓</p>
 <Separator />
 <div className="flex items-center gap-2 text-xs text-muted-foreground">
 Otwórz command palette: <Kbd>⌘</Kbd><Kbd>K</Kbd> · Zamknij: <Kbd>Esc</Kbd>
 </div>
 <div className="flex items-center gap-3 h-6">
 Inline <Separator orientation="vertical" /> z separatorem <Separator orientation="vertical" /> pionowym
 </div>
 </div>
 </Section>
 );
}

// ── 9. Tabs ────────────────────────────────────────────────────────────
function TabsSection() {
 return (
 <Section num={9} title="Tabs">
 <div className="bg-card p-4 rounded-lg border border-border">
 <Tabs defaultValue="profile">
 <TabsList>
 <TabsTrigger value="profile">
 <User className="h-3.5 w-3.5" />
 Profil
 </TabsTrigger>
 <TabsTrigger value="timeline">
 <FileText className="h-3.5 w-3.5" />
 Timeline
 </TabsTrigger>
 <TabsTrigger value="matches">
 <Star className="h-3.5 w-3.5" />
 Rekrutacje
 </TabsTrigger>
 <TabsTrigger value="notes" disabled>
 Notatki (0)
 </TabsTrigger>
 </TabsList>
 <TabsContent value="profile">
 <p className="text-sm text-foreground">
 Tab panel <strong>Profil</strong> — tu pojawi się profil kandydata w Phase 5.
 </p>
 </TabsContent>
 <TabsContent value="timeline">
 <p className="text-sm text-foreground">
 Tab panel <strong>Timeline</strong> — zdarzenia, zmiany etapów, notatki.
 </p>
 </TabsContent>
 <TabsContent value="matches">
 <p className="text-sm text-foreground">
 Tab panel <strong>Rekrutacje</strong> — aktywne i historyczne dopasowania.
 </p>
 </TabsContent>
 </Tabs>
 </div>
 </Section>
 );
}

// ── 10. Table ──────────────────────────────────────────────────────────
function TableSection() {
 type BadgeVariant ="neutral" |"plum" |"burgundy" |"soft" |"success" |"warning" |"danger" |"info" |"outline";
 const rows: { id: number; name: string; role: string; stage: string; status: BadgeVariant; match: number }[] = [
 { id: 1, name:"Anna Kowalska", role:"Senior React Dev", stage:"Screening", status:"soft", match: 94 },
 { id: 2, name:"Marcin Nowak", role:"DevOps Lead", stage:"CV wysłane", status:"plum", match: 87 },
 { id: 3, name:"Katarzyna Piekarska", role:"Product Designer", stage:"Interview", status:"burgundy", match: 81 },
 { id: 4, name:"Olaf Zielski", role:"Data Engineer", stage:"Negotiation", status:"success", match: 78 },
 ];
 return (
 <Section num={10} title="Table — cozy + compact">
 <SubRow label="Cozy (default — row 48px)">
 <div className="w-full">
 <Table density="cozy">
 <TableHeader>
 <TableRow>
 <TableHead>Kandydat</TableHead>
 <TableHead>Rola</TableHead>
 <TableHead>Etap</TableHead>
 <TableHead className="text-right">Match</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 {rows.map((r) => (
 <TableRow key={r.id} interactive>
 <TableCell className="font-medium text-foreground">{r.name}</TableCell>
 <TableCell>{r.role}</TableCell>
 <TableCell>
 <Badge variant={r.status} size="sm">{r.stage}</Badge>
 </TableCell>
 <TableCell className="text-right font-mono">{r.match}%</TableCell>
 </TableRow>
 ))}
 </TableBody>
 </Table>
 </div>
 </SubRow>
 <SubRow label="Compact (row 36px) + selected row">
 <div className="w-full">
 <Table density="compact">
 <TableHeader>
 <TableRow>
 <TableHead>Kandydat</TableHead>
 <TableHead>Rola</TableHead>
 <TableHead>Etap</TableHead>
 <TableHead className="text-right">Match</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 {rows.map((r, i) => (
 <TableRow key={r.id} interactive selected={i === 1}>
 <TableCell className="font-medium text-foreground">{r.name}</TableCell>
 <TableCell>{r.role}</TableCell>
 <TableCell>
 <Badge variant={r.status} size="sm">{r.stage}</Badge>
 </TableCell>
 <TableCell className="text-right font-mono">{r.match}%</TableCell>
 </TableRow>
 ))}
 </TableBody>
 </Table>
 </div>
 </SubRow>
 </Section>
 );
}

// ── 11. Cards ──────────────────────────────────────────────────────────
function CardsSection() {
 return (
 <Section num={11} title="Cards">
 <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
 <Card variant="default">
 <CardHeader>
 <CardTitle>Default card</CardTitle>
 <CardDescription>Domyślny kontener. Hairline + subtle shadow.</CardDescription>
 </CardHeader>
 <CardContent>
 <p className="text-sm">Użyj dla stat cards, widgetów, form sections.</p>
 </CardContent>
 <CardFooter>
 <Button size="sm" variant="tertiary">
 Więcej <ArrowRight className="h-3.5 w-3.5" />
 </Button>
 </CardFooter>
 </Card>
 <Card variant="elevated">
 <CardHeader>
 <CardTitle>Elevated</CardTitle>
 <CardDescription>Większy shadow — użyj dla highlightów.</CardDescription>
 </CardHeader>
 <CardContent>
 <p className="text-sm">Placements MTD: <strong>17</strong> (+23%)</p>
 </CardContent>
 </Card>
 <Card variant="interactive">
 <CardHeader>
 <CardTitle>Interactive</CardTitle>
 <CardDescription>Hover: lift + stronger shadow. Klikalne karty.</CardDescription>
 </CardHeader>
 <CardContent>
 <p className="text-sm">Kliknięcie otwiera side sheet lub nawiguje.</p>
 </CardContent>
 </Card>
 </div>
 </Section>
 );
}

// ── 12. Dialog + Sheet ─────────────────────────────────────────────────
function DialogSheetSection() {
 return (
 <Section num={12} title="Dialog + Sheet">
 <SubRow label="Dialog (center modal)">
 <Dialog>
 <DialogTrigger asChild>
 <Button variant="primary">
 <Mail className="h-4 w-4" />
 Wyślij email do klienta
 </Button>
 </DialogTrigger>
 <DialogContent size="md">
 <DialogHeader>
 <DialogTitle>Wyślij profil kandydata</DialogTitle>
 <DialogDescription>
 Anna Kowalska → Dynaminds (Team Lead — Senior React)
 </DialogDescription>
 </DialogHeader>
 <DialogBody>
 <div className="space-y-3">
 <FormField label="Do" htmlFor="dlg-to">
 <Input id="dlg-to" defaultValue="client@example.com" />
 </FormField>
 <FormField label="Temat" htmlFor="dlg-subj">
 <Input id="dlg-subj" defaultValue="Kandydat na pozycję Senior React" />
 </FormField>
 <FormField label="Wiadomość" htmlFor="dlg-body">
 <Textarea id="dlg-body" rows={5} defaultValue="Dzień dobry, przesyłam profil..." />
 </FormField>
 </div>
 </DialogBody>
 <DialogFooter>
 <Button variant="ghost">Anuluj</Button>
 <Button variant="primary">
 <Send className="h-4 w-4" />
 Wyślij
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>

 <Dialog>
 <DialogTrigger asChild>
 <Button variant="outline">
 <Info className="h-4 w-4" /> Mały dialog
 </Button>
 </DialogTrigger>
 <DialogContent size="sm">
 <DialogHeader>
 <DialogTitle>Potwierdź usunięcie</DialogTitle>
 <DialogDescription>
 Tej operacji nie można cofnąć. Kandydat zostanie archiwizowany.
 </DialogDescription>
 </DialogHeader>
 <DialogFooter>
 <Button variant="ghost">Anuluj</Button>
 <Button variant="destructive">
 <Trash2 className="h-4 w-4" />
 Usuń
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 </SubRow>

 <SubRow label="Sheet (side panel — screening, scorecard)">
 <Sheet>
 <SheetTrigger asChild>
 <Button variant="secondary">
 <Edit className="h-4 w-4" />
 Screening (side sheet)
 </Button>
 </SheetTrigger>
 <SheetContent side="right" size="lg">
 <SheetHeader>
 <SheetTitle>Screening — Anna Kowalska</SheetTitle>
 </SheetHeader>
 <SheetBody>
 <div className="space-y-4">
 <FormField label="Dlaczego ten projekt?" htmlFor="scr-1">
 <Textarea id="scr-1" rows={3} placeholder="Odpowiedź kandydata…" />
 </FormField>
 <FormField label="Oczekiwania finansowe" htmlFor="scr-2">
 <Input id="scr-2" placeholder="np. 21 000 PLN B2B" />
 </FormField>
 <FormField label="Dostępność" htmlFor="scr-3">
 <Input id="scr-3" placeholder="2 tygodnie wypowiedzenia" />
 </FormField>
 <RadioGroup defaultValue="fit">
 <h3 className="text-sm font-semibold">Ogólna ocena</h3>
 <label className="inline-flex items-center gap-2 text-sm">
 <RadioGroupItem value="fit" /> Dobrze pasuje
 </label>
 <label className="inline-flex items-center gap-2 text-sm">
 <RadioGroupItem value="uncertain" /> Niepewne
 </label>
 <label className="inline-flex items-center gap-2 text-sm">
 <RadioGroupItem value="miss" /> Nie pasuje
 </label>
 </RadioGroup>
 </div>
 </SheetBody>
 <SheetFooter>
 <Button variant="ghost">Anuluj</Button>
 <Button variant="primary">Zapisz screening</Button>
 </SheetFooter>
 </SheetContent>
 </Sheet>

 <Sheet>
 <SheetTrigger asChild>
 <Button variant="ghost">
 <Archive className="h-4 w-4" />
 Bottom sheet
 </Button>
 </SheetTrigger>
 <SheetContent side="bottom">
 <SheetHeader>
 <SheetTitle>Bulk actions · 3 wybrane</SheetTitle>
 </SheetHeader>
 <SheetBody>
 <div className="flex gap-2 flex-wrap">
 <Button variant="primary">Przypisz do oferty</Button>
 <Button variant="secondary">Zmień etap</Button>
 <Button variant="outline">Eksportuj CSV</Button>
 <Button variant="ghost">Anuluj zaznaczenie</Button>
 </div>
 </SheetBody>
 </SheetContent>
 </Sheet>
 </SubRow>
 </Section>
 );
}

// ── 13. DropdownMenu + Popover + Tooltip ───────────────────────────────
function DropdownPopoverTooltipSection() {
 return (
 <Section num={13} title="Dropdown · Popover · Tooltip">
 <SubRow label="Dropdown menu">
 <DropdownMenu>
 <DropdownMenuTrigger asChild>
 <Button variant="outline">
 Akcje <ChevronDown className="h-3.5 w-3.5" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent>
 <DropdownMenuLabel>Akcje kandydata</DropdownMenuLabel>
 <DropdownMenuItem>
 <Edit className="h-4 w-4" /> Edytuj profil
 </DropdownMenuItem>
 <DropdownMenuItem>
 <Mail className="h-4 w-4" /> Wyślij email
 </DropdownMenuItem>
 <DropdownMenuItem>
 <FileText className="h-4 w-4" /> Generuj CV
 </DropdownMenuItem>
 <DropdownMenuSeparator />
 <DropdownMenuItem danger>
 <Trash2 className="h-4 w-4" /> Archiwizuj
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 </SubRow>

 <SubRow label="Popover (filter / column config)">
 <Popover>
 <PopoverTrigger asChild>
 <Button variant="outline">
 <Filter className="h-4 w-4" />
 Filtry <Badge variant="soft" size="sm">3</Badge>
 </Button>
 </PopoverTrigger>
 <PopoverContent className="w-72">
 <div className="space-y-3">
 <FormField label="Lokalizacja" htmlFor="pop-loc">
 <Input id="pop-loc" placeholder="np. Warszawa" />
 </FormField>
 <FormField label="Umiejętności" htmlFor="pop-skills">
 <Input id="pop-skills" placeholder="React, Kubernetes…" />
 </FormField>
 <div className="flex justify-between pt-2">
 <Button variant="ghost" size="sm">Wyczyść</Button>
 <Button variant="primary" size="sm">Zastosuj</Button>
 </div>
 </div>
 </PopoverContent>
 </Popover>
 </SubRow>

 <SubRow label="Tooltip">
 <Tooltip>
 <TooltipTrigger asChild>
 <Button variant="ghost" size="icon" aria-label="Info">
 <Info className="h-4 w-4" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>
 Champion fit scoring — ocena AI na podstawie screeningu.
 </TooltipContent>
 </Tooltip>
 <Tooltip>
 <TooltipTrigger asChild>
 <Badge variant="burgundy">
 <Users className="h-3 w-3" /> 17 kandydatów
 </Badge>
 </TooltipTrigger>
 <TooltipContent side="right">
 Aktywni w pipeline&apos;ie dla tej oferty.
 </TooltipContent>
 </Tooltip>
 </SubRow>
 </Section>
 );
}

// ── 14. Command palette ────────────────────────────────────────────────
function CommandSection({
 setCmdkOpen,
 cmdkOpen,
}: {
 setCmdkOpen: (v: boolean) => void;
 cmdkOpen: boolean;
}) {
 return (
 <Section num={14} title="Command palette (⌘K)">
 <div className="space-y-3 bg-card p-4 rounded-lg border border-border">
 <div className="flex items-center gap-3">
 <Button variant="primary" onClick={() => setCmdkOpen(true)}>
 <CommandIcon className="h-4 w-4" />
 Otwórz command palette
 </Button>
 <span className="text-xs text-muted-foreground">
 W Phase 2 globalny ⌘K trigger będzie w TopbarV2.
 </span>
 </div>

 <Command className="rounded-lg border border-border max-w-lg">
 <CommandInput placeholder="Inline command — szukaj akcji…" />
 <CommandList>
 <CommandEmpty>Brak wyników.</CommandEmpty>
 <CommandGroup heading="Sugerowane">
 <CommandItem>
 <Plus className="h-4 w-4" />
 Nowy kandydat
 <CommandShortcut>N</CommandShortcut>
 </CommandItem>
 <CommandItem>
 <Building2 className="h-4 w-4" />
 Nowa oferta
 <CommandShortcut>J</CommandShortcut>
 </CommandItem>
 </CommandGroup>
 </CommandList>
 </Command>
 </div>

 <CommandDialog open={cmdkOpen} onOpenChange={setCmdkOpen}>
 <CommandInput placeholder="Szukaj kandydatów, ofert, akcji…" />
 <CommandList>
 <CommandEmpty>Brak wyników.</CommandEmpty>
 <CommandGroup heading="Akcje">
 <CommandItem onSelect={() => setCmdkOpen(false)}>
 <Plus className="h-4 w-4" />
 Nowy kandydat
 <CommandShortcut>N</CommandShortcut>
 </CommandItem>
 <CommandItem onSelect={() => setCmdkOpen(false)}>
 <Building2 className="h-4 w-4" />
 Nowa oferta
 <CommandShortcut>J</CommandShortcut>
 </CommandItem>
 <CommandItem onSelect={() => setCmdkOpen(false)}>
 <Mail className="h-4 w-4" />
 Wyślij email
 </CommandItem>
 </CommandGroup>
 <CommandSeparator />
 <CommandGroup heading="Nawigacja">
 <CommandItem onSelect={() => setCmdkOpen(false)}>
 <Users className="h-4 w-4" />
 Kandydaci
 </CommandItem>
 <CommandItem onSelect={() => setCmdkOpen(false)}>
 <Building2 className="h-4 w-4" />
 Klienci
 </CommandItem>
 <CommandItem onSelect={() => setCmdkOpen(false)}>
 <FileText className="h-4 w-4" />
 Kontrakty
 </CommandItem>
 </CommandGroup>
 </CommandList>
 </CommandDialog>
 </Section>
 );
}
