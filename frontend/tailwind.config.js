/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f5f7fa",
          100: "#e4e9f0",
          200: "#c8d1de",
          300: "#9ba8bb",
          400: "#6c7a91",
          500: "#4a5670",
          600: "#384158",
          700: "#2b3245",
          800: "#1c2233",
          900: "#0f1322",
        },
        accent: {
          50: "#eef4ff",
          100: "#dbe6ff",
          200: "#b6ccff",
          300: "#83a8ff",
          400: "#5684f5",
          500: "#3460db",
          600: "#2748b1",
          700: "#1f388a",
          800: "#172a68",
          900: "#0f1c45",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};
