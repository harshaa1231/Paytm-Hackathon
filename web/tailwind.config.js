/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['"Inter Variable"', "system-ui", "sans-serif"] },
      colors: {
        ink: { DEFAULT: "#0f172a", 2: "#475569", 3: "#94a3b8" },
        navy: { DEFAULT: "#0b2a5b", 2: "#16407f" },
        money: { DEFAULT: "#0f9d58", soft: "#e7f6ee" },
        trust: { DEFAULT: "#b45309", soft: "#fdf3e4" },
        sky: { DEFAULT: "#2a78d6", soft: "#eaf2fc" },
        s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", s4: "#eda100", s5: "#e87ba4",
      },
      boxShadow: { card: "0 1px 2px rgba(15,23,42,.06), 0 4px 16px rgba(15,23,42,.06)", phone: "0 30px 80px rgba(15,23,42,.25)" },
    },
  },
  plugins: [],
};
