/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
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
        reject: {
          DEFAULT: "var(--status-reject)",
          bg: "var(--status-reject-bg)",
        },
        review: {
          DEFAULT: "var(--status-review)",
          bg: "var(--status-review-bg)",
        },
        accept: {
          DEFAULT: "var(--status-accept)",
          bg: "var(--status-accept-bg)",
        },
        trace: {
          neutral: "var(--chart-trace-neutral)",
          selected: "var(--chart-trace-selected)",
        },
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "-apple-system", "BlinkMacSystemFont", "'Segoe UI'", "Roboto", "sans-serif"],
        mono: ["'IBM Plex Mono'", "Menlo", "Monaco", "Consolas", "'Liberation Mono'", "monospace"],
      },
      borderRadius: {
        DEFAULT: "2px",
        none: "0px",
        sm: "2px",
        md: "2px",
        lg: "2px",
      },
      boxShadow: {
        none: "none",
      },
      fontSize: {
        'xxs': '10px',
        'xs': '11px',
        'sm': '12px',
        'base': '13px',
        'md': '14px',
        'lg': '16px',
      },
      height: {
        'row': '28px',
      },
      lineHeight: {
        'tight': '1.25',
      },
    },
  },
  plugins: [],
};
