import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: {
          50: "#fdfbf4",
          100: "#f9f3e1",
          200: "#f1e6c2",
        },
        wood: {
          50: "#fbf3df",
          100: "#f1dfa9",
          200: "#e8c77a",
          300: "#d4a574",
          400: "#b98552",
          500: "#8f6235",
          600: "#6b4a1f",
          700: "#4a321a",
          800: "#2f1f10",
        },
        ink: {
          900: "#1a1a1a",
          800: "#2a2621",
          700: "#3f382f",
          600: "#5a5147",
          500: "#7a7065",
        },
        accent: {
          50: "#fff7ed",
          500: "#d97706",
          600: "#b45309",
          700: "#92400e",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Inter",
          '"Segoe UI"',
          "Roboto",
          '"Noto Sans SC"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          "sans-serif",
        ],
        display: [
          '"Cormorant Garamond"',
          '"Noto Serif SC"',
          "ui-serif",
          "Georgia",
          "serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(74,50,26,.04), 0 4px 14px rgba(74,50,26,.06)",
        card: "0 1px 3px rgba(74,50,26,.06), 0 8px 24px rgba(74,50,26,.08)",
        brand: "0 1px 2px rgba(180,83,9,.15), 0 6px 20px rgba(180,83,9,.18)",
      },
      animation: {
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.55", transform: "scale(1.35)" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
