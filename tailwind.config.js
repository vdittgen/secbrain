/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/interface/**/*.{html,js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Geist",
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "SF Pro Text",
          "system-ui",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "Geist Mono",
          "SF Mono",
          "ui-monospace",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        bg: "var(--bg)",
        "bg-2": "var(--bg-2)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        hairline: "var(--hairline)",
        "hairline-2": "var(--hairline-2)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        indigo: {
          DEFAULT: "var(--indigo)",
          2: "var(--indigo-2)",
          soft: "var(--indigo-soft)",
          tint: "var(--indigo-tint)",
        },
        work: {
          tint: "var(--work-tint)",
          ink: "var(--work-ink)",
        },
        personal: {
          tint: "var(--personal-tint)",
          ink: "var(--personal-ink)",
        },
        health: {
          tint: "var(--health-tint)",
          ink: "var(--health-ink)",
        },
        success: "var(--success)",
        "success-soft": "var(--success-soft)",
        amber: "var(--amber)",
        "amber-soft": "var(--amber-soft)",
        danger: "var(--danger)",
        "danger-soft": "var(--danger-soft)",
      },
      borderRadius: {
        1: "6px",
        2: "10px",
        3: "14px",
        4: "20px",
        5: "28px",
        pill: "999px",
      },
      boxShadow: {
        1: "0 1px 2px oklch(0.18 0.01 250 / 0.04), 0 0 0 1px oklch(0.18 0.01 250 / 0.04)",
        2: "0 1px 3px oklch(0.18 0.01 250 / 0.04), 0 4px 12px oklch(0.18 0.01 250 / 0.05)",
        3: "0 2px 6px oklch(0.18 0.01 250 / 0.05), 0 12px 32px oklch(0.18 0.01 250 / 0.08)",
        glow: "0 0 0 4px oklch(0.55 0.20 265 / 0.10)",
      },
      transitionTimingFunction: {
        lucid: "cubic-bezier(.2, .8, .2, 1)",
      },
      transitionDuration: {
        hover: "140ms",
        panel: "240ms",
      },
      letterSpacing: {
        tight: "-0.005em",
        tighter: "-0.015em",
        "lucid-display": "-0.025em",
        "lucid-display-xl": "-0.04em",
      },
    },
  },
  plugins: [],
};
