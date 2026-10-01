/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "var(--navy)", deep: "var(--navy-deep)" },
        cyan: "var(--cyan)",
        accent: { DEFAULT: "var(--accent)", hover: "var(--accent-hover)" },
        workspace: "var(--surface-workspace)",
        panel: "var(--surface-panel)",
        toprail: "var(--surface-toprail)",
        pagebg: "var(--surface-pagebg)",
        hairline: {
          DEFAULT: "var(--border-hairline)",
          subtle: "var(--border-hairline-subtle)",
        },
        main: "var(--text-main)",
        muted: "var(--text-muted)",
        dim: "var(--text-dim)",
        reject: { DEFAULT: "var(--status-reject)", bg: "var(--status-reject-bg)" },
        review: { DEFAULT: "var(--status-review)", bg: "var(--status-review-bg)" },
        accept: { DEFAULT: "var(--status-accept)", bg: "var(--status-accept-bg)" },
        info: { DEFAULT: "var(--status-info)", bg: "var(--status-info-bg)" },
        trace: {
          neutral: "var(--chart-trace-neutral)",
          selected: "var(--chart-trace-selected)",
        },
      },
      fontFamily: {
        sans: ["'Noto Sans'", "'Nunito Sans'", "-apple-system", "BlinkMacSystemFont", "'Segoe UI'", "Roboto", "sans-serif"],
        mono: ["'Noto Sans Mono'", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        DEFAULT: "6px",
        sm: "4px",
        md: "6px",
        lg: "8px",
        card: "12px",
      },
      fontSize: {
        'xxs': '10px',
        'xs': '11px',
        'sm': '12px',
        'base': '13px',
        'md': '14px',
        'lg': '16px',
        'card': ['18px', '24px'],
        'title': ['28px', '34px'],
      },
      height: {
        'row': '32px',
      },
    },
  },
  plugins: [],
};
