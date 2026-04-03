import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Arial", "Helvetica Neue", "Helvetica", "sans-serif"],
        display: ["Arial", "Helvetica Neue", "Helvetica", "sans-serif"],
      },
      colors: {
        canvas: "#f3efe6",
        ink: "#0f2b34",
        calm: "#166f78",
        warm: "#ce6d2e",
        moss: "#4f7b63",
      },
      boxShadow: {
        panel: "0 24px 54px rgba(16, 42, 49, 0.15)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        rise: "rise 520ms ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
