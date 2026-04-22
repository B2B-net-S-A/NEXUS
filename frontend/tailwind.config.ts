import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // ── V1 tokens (legacy — keep untouched so v1 surfaces render unchanged) ──
        border: "hsl(var(--border, 214.3 31.8% 91.4%))",
        background: "hsl(var(--background, 0 0% 100%))",
        foreground: "hsl(var(--foreground, 222.2 84% 4.9%))",
        primary: {
          DEFAULT: "hsl(var(--primary, 221.2 83.2% 53.3%))",
          foreground: "hsl(var(--primary-foreground, 210 40% 98%))",
        },
        gray: {
          950: "#0a0a0f",
        },

        // ── Dynaminds brand palette (raw hex, v2 only) ────────────────────
        plum: {
          50: "#F7F5F6",
          100: "#EAE6E9",
          200: "#CEC6CD",
          300: "#B1A5AF",
          400: "#87778C",
          500: "#5A4B5A",
          600: "#433644",
          700: "#2E1A2B", // brandbook — Deep Plum (dominant chrome)
          800: "#1F1220",
          900: "#15090E",
          950: "#0A0407",
        },
        burgundy: {
          50: "#FBF2F3",
          100: "#F4DDE0",
          200: "#E9B9BF",
          300: "#DB939B",
          400: "#C16F7B",
          500: "#A63A4A",
          600: "#8B1A2B", // brandbook — Burgundy (accent)
          700: "#6B1120",
          800: "#4D0A16",
          900: "#310711",
          950: "#1A0308",
        },
        cream: {
          50: "#FBF9F6",
          100: "#F8F5EF",
          200: "#F0EBE3", // brandbook — Warm Cream (canvas)
          300: "#E8E4DE",
          400: "#D8CFBF",
          500: "#B5AA9A",
          600: "#92897B",
          700: "#6F685E",
          800: "#4C4841",
          900: "#2A2824",
          950: "#15130F",
        },
        // Brandbook neutrals (for exact matches where hex is called out)
        ink: {
          black: "#000000",
          dark: "#5A5650",
          medium: "#9E9A94",
          light: "#E8E4DE",
          white: "#FFFFFF",
        },

        // ── Semantic aliases (v2 uses these; they resolve via CSS vars) ───
        canvas: "hsl(var(--bg-canvas) / <alpha-value>)",
        surface: "hsl(var(--bg-surface) / <alpha-value>)",
        chrome: "hsl(var(--bg-chrome) / <alpha-value>)",
        title: "hsl(var(--text-title) / <alpha-value>)",
        body: "hsl(var(--text-body) / <alpha-value>)",
        muted: "hsl(var(--text-muted) / <alpha-value>)",
        subtle: "hsl(var(--border-subtle) / <alpha-value>)",
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
          strong: "hsl(var(--accent-strong) / <alpha-value>)",
          soft: "hsl(var(--accent-soft) / <alpha-value>)",
        },
      },

      fontFamily: {
        // v1 keeps --font-inter as default sans
        sans: ["var(--font-inter)", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        // v2 headings / display
        display: ["var(--font-poppins)", "system-ui", "-apple-system", "sans-serif"],
      },

      // ── Dynaminds border radii ─────────────────────────────────────────
      borderRadius: {
        // Map Tailwind scale to Dynaminds scale
        xs: "0.4rem", // 4px — inputs, tags
        // keep sm default (Tailwind 0.125rem) — unused in v2 but preserves v1 behavior
        // md default (0.375rem) and lg default (0.5rem) preserved
        // v2 additions:
        "v2-s": "0.6rem", // 6-8px — small buttons, badges
        "v2-m": "1rem", // 10-12px — default cards, buttons, images (v2 default)
        "v2-l": "1.6rem", // 16-20px — feature cards
        "v2-xl": "2.6rem", // 26px — hero cards
        // "full" already exists (Tailwind: 9999px)
      },

      // ── Dynaminds shadow scale (soft, low-opacity) ─────────────────────
      boxShadow: {
        "v2-xs": "0 1px 2px rgba(46, 26, 43, 0.08)",
        "v2-s": "0 1.5px 3px rgba(46, 26, 43, 0.09)",
        "v2-m": "0 2px 8px rgba(46, 26, 43, 0.10)", // default card
        "v2-l": "0 4px 16px rgba(46, 26, 43, 0.12)",
        "v2-xl": "0 8px 48px rgba(46, 26, 43, 0.14)",
        "v2-focus": "0 0 0 4px hsl(var(--accent-soft))",
      },

      // ── Dynaminds fluid spacing scale (additive — Tailwind defaults still work) ──
      spacing: {
        "fluid-4xs": "clamp(0.49rem, 0vw + 0.52rem, 0.52rem)",
        "fluid-3xs": "clamp(0.66rem, 0.04vw + 0.64rem, 0.70rem)",
        "fluid-2xs": "clamp(0.82rem, 0.16vw + 0.77rem, 0.99rem)",
        "fluid-xs": "clamp(1.02rem, 0.36vw + 0.91rem, 1.40rem)",
        "fluid-s": "clamp(1.28rem, 0.67vw + 1.07rem, 1.98rem)",
        "fluid-m": "clamp(1.60rem, 1.15vw + 1.23rem, 2.80rem)",
        "fluid-l": "clamp(2.00rem, 1.87vw + 1.40rem, 3.96rem)",
        "fluid-xl": "clamp(2.50rem, 2.96vw + 1.55rem, 5.60rem)",
        "fluid-2xl": "clamp(3.13rem, 4.58vw + 1.66rem, 7.92rem)",
        "fluid-3xl": "clamp(3.91rem, 6.97vw + 1.68rem, 11.19rem)",
      },

      // ── Letter spacing presets ─────────────────────────────────────────
      letterSpacing: {
        "display-tight": "-0.025em",
        "heading-tight": "-0.02em",
        "heading": "-0.01em",
        "eyebrow": "0.22em",
      },

      keyframes: {
        fadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
        slideInBottom: {
          from: { transform: "translateY(100%)" },
          to: { transform: "translateY(0)" },
        },
      },
      animation: {
        fadeIn: "fadeIn 200ms ease-out both",
        "slide-in-right": "slideInRight 300ms ease-out both",
        "slide-in-bottom": "slideInBottom 300ms ease-out both",
      },

      transitionTimingFunction: {
        "dynaminds": "cubic-bezier(0.4, 0, 0.2, 1)", // ease-in-out approximation
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
