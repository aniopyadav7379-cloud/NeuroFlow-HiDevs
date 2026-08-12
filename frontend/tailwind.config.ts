import type { Config } from "tailwindcss";

// Design tokens for NeuroFlow's console — an instrument panel for
// engineers watching a RAG pipeline run, not a marketing surface.
// Near-black canvas so streaming text and score colors (the things that
// actually change moment to moment) read as the focal signal, not
// competing with a bright chrome. Deliberately NOT the cream/terracotta
// or acid-green defaults — teal-cyan reads as "live/active" without
// borrowing Claude's own accent.
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
        canvas: "#0B0D10",
        surface: "#14171B",
        "surface-raised": "#1B1F24",
        "surface-hover": "#20252B",
        border: {
          DEFAULT: "#262B31",
          strong: "#343B43",
        },
        ink: {
          DEFAULT: "#E7EAEE",
          muted: "#8A93A0",
          faint: "#5B6470",
        },
        accent: {
          DEFAULT: "#4FD1C5",
          dim: "#2A5F5B",
          bright: "#7EEAE0",
        },
        score: {
          good: "#34D399",
          mid: "#FBBF24",
          bad: "#F87171",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
