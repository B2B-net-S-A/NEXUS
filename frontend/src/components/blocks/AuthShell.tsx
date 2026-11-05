import { cn } from "@/lib/utils"
import { DynamindsLogo } from "@/components/brand/DynamindsLogo"
import { DynamindsMark } from "@/components/brand/DynamindsMark"
import { B2BLogo } from "@/components/career/B2BLogo"

interface AuthShellProps {
  /** Page heading (e.g. powitanie albo "Ustaw nowe hasło"). */
  heading: string
  /** Optional subtitle under the heading. */
  subtitle?: React.ReactNode
  /** Duży nagłówek do krótkiego powitania; dłuższe nagłówki zostają w zwykłym rozmiarze. */
  largeHeading?: boolean
  /** The form (or a success/error state). */
  children: React.ReactNode
  className?: string
}

/**
 * Układ ekranów przed logowaniem (login, reset hasła, rejestracja): logo obu
 * marek, po lewej nagłówek z formularzem, resztę ekranu zajmuje znak firmy.
 * Logo B2B Network ma 45 px wysokości, czyli minimalne 96 px szerokości z brand
 * booka; odstęp od sąsiada to wymagane pole ochronne (połowa wysokości logo).
 * Purely presentational — all auth wiring lives in the page that supplies `children`.
 */
export function AuthShell({ heading, subtitle, largeHeading = false, children, className }: AuthShellProps) {
  return (
    <div className={cn("relative flex min-h-dvh flex-col overflow-hidden bg-background", className)}>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-[-68vw] top-[6dvh] h-[52dvh] md:right-[-26vw] lg:left-[24vw] lg:right-auto lg:top-[-4dvh] lg:h-[max(135dvh,76vw)]"
      >
        <DynamindsMark className="h-full w-auto text-primary" />
      </div>
      <div className="relative flex flex-1 flex-col justify-between gap-10 px-6 py-6 lg:px-16 lg:py-10">
        <div className="flex items-center gap-[23px] self-start">
          <DynamindsLogo className="-ml-[5px] h-6 w-auto text-foreground lg:h-7" />
          <span aria-hidden="true" className="h-8 w-px bg-border" />
          <B2BLogo height={45} className="dark:hidden" />
          <B2BLogo height={45} variant="onDark" className="hidden dark:block" />
        </div>
        <div className="w-full max-w-sm pb-2 lg:pb-8">
          <h1
            className={cn(
              "font-display font-semibold text-foreground",
              largeHeading
                ? "text-5xl tracking-display-tight lg:text-6xl"
                : "text-3xl tracking-heading-tight",
            )}
          >
            {heading}
          </h1>
          {subtitle && <p className="mt-3 text-base text-muted-foreground">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  )
}
