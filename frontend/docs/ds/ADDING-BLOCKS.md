# Dodawanie bloków/prymitywów do NEXUSa (DYNAMINDS DS)

Dwie biblioteki, dwie domeny:

- **Tailwind Plus** → application UI (shell, dashboardy, tabele, formularze). Brak CLI/rejestru — kod kopiujesz z **zalogowanej sesji** (`tailwindcss.com/plus`) i **adaptujesz na tokeny**.
- **shadcnblocks ELITE** → marketing/login/landing/onboarding. Rejestr `@shadcnblocks` w `components.json`; klucz `SHADCNBLOCKS_API_KEY` w gitignorowanym `.env.local` (**exp 2026-08-21**, odnów w `shadcnblocks.com/dashboard/api`).

## Złota zasada: token-first (nic verbatim)

Obie biblioteki dają zaszyte kolory; Tailwind Plus dodatkowo Tailwind v4 + własny JS `@tailwindplus/elements`. Przepisz na tokeny:

| zaszyte | token |
|---|---|
| `text-gray-900` | `text-foreground` |
| `text-gray-500` / `text-gray-700` | `text-muted-foreground` |
| `bg-white` | `bg-card` |
| `bg-gray-50` | `bg-muted` |
| `bg-indigo-600` | `bg-primary` |
| `hover:bg-indigo-500` | `hover:bg-primary/90` |
| `text-white` (na primary) | `text-primary-foreground` |
| `border-gray-200/300` | `border-border` |
| `divide-gray-200` | `divide-border` |
| `ring-indigo-*` | `ring-ring` |
| kolor wykresu (hex) | `hsl(var(--chart-1..5))` |
| zielony status (`green-*`/`emerald-*`) | `bg-success-muted text-success-muted-foreground` |
| bursztynowy status (`amber-*`) | `bg-warning-muted text-warning-muted-foreground` |
| czerwony status (`red-*`/`rose-*`) | `bg-destructive-muted text-destructive-muted-foreground` |
| niebieski status informacyjny (`blue-*`/`sky-*`) | `bg-info-muted text-info-muted-foreground` |
| LinkedIn `#0A66C2` | `text-brand-linkedin` / `bg-brand-linkedin` |

- `--accent` to **subtelny neutral** (hover), **NIE** brand → emfaza zawsze przez `--primary`.
- Radius: używaj `rounded-lg/md/sm` (sterowane `--radius`) dla elementów reagujących na soft/kids.
- Kids-mode hooki zostawiaj nietknięte: `.bg-card`, `role="progressbar"`, `role="dialog"`, `:has(table)`.

## Prymitywy shadcn (atomy → `src/components/ui/`)

```bash
./scripts/add-block.sh primitive progress accordion
npm install <wypisane deps> --legacy-peer-deps
```

Pobiera z publicznego rejestru shadcn (new-york) **bezpośrednio** — bez `npx shadcn add`, bo CLI: (1) przepisuje blok `@theme inline` w `globals.css` i remapuje `--sidebar` → `--sidebar-background` (NEXUS tego nie ma → psuje sidebar), (2) bumpuje wersje istniejących deps. Prymitywy shadcn są już token-based (zwykle 0 przepisywania).

## Bloki shadcnblocks (sekcje → `src/components/blocks/`)

```bash
./scripts/add-block.sh shadcnblock login4 hero7
# następnie: przepisz raw-colory na tokeny wg tabeli wyżej
```

## Audyt (po każdym dodaniu)

```bash
git diff --stat                                                  # tylko zamierzone NOWE pliki
grep -nE "gray-[0-9]|indigo-[0-9]|bg-white|sidebar-background" <plik>   # ma być pusto
npm run lint:tokens                                                # DS + nowe ekrany kandydatów
npm run type-check && npm run build                              # zielone
```

## Awaryjnie: CLI mimo wszystko (Metoda A)

```bash
yes n | npx shadcn@latest add <name> -y      # 'n' = zachowaj komponenty NEXUSa
git checkout -- package.json package-lock.json src/app/globals.css
# dodaj wymagane @radix-ui/* ręcznie, pinned
```

⚠ Wymaga **wcześniejszego commita** zmian w `globals.css` (inaczej `git checkout` cofnie też Twoje tokeny).

## Tailwind v4 — gdzie teraz mieszka konfiguracja

Nie ma `tailwind.config.ts`. Całość jest w `src/app/globals.css`:

| co | gdzie |
|---|---|
| mapowanie tokenów na utilities (`bg-primary`…) | `@theme inline { --color-*: hsl(var(--*)) }` |
| wartości tokenów (7 palet × dark/soft/kids) | zwykłe `@layer base` — **bez zmian od v3** |
| dark mode | `@custom-variant dark (&:is(.dark *))` |
| pluginy | `@plugin "@tailwindcss/typography"` |
| skanowanie plików | automatyczne (brak `content:`) |

⚠ **`@theme inline` jest obowiązkowe** (nie samo `@theme`). Bez `inline` Tailwind wypisuje
`--color-primary` do `:root` z już-podstawioną wartością, więc nadpisanie `--primary`
w węźle innym niż `<html>` przestaje działać (dziś wszystkie 18 zakresów motywu siedzi
na `<html>`, więc byłoby to ciche do pierwszego zagnieżdżonego motywu).
