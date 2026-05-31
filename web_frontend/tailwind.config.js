/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#fbfbe2",
        surface: "#fbfbe2",
        "surface-bright": "#fbfbe2",
        "surface-container-lowest": "#ffffff",
        "surface-container-low": "#f5f5dc",
        "surface-container": "#efefd7",
        "surface-container-high": "#eaead1",
        "surface-container-highest": "#e4e4cc",
        primary: "#322214",
        "primary-container": "#4a3728",
        secondary: "#735c00",
        "secondary-container": "#fed65b",
        tertiary: "#2f2319",
        outline: "#80756d",
        "outline-variant": "#d2c4bb",
        "on-background": "#1b1d0e",
        "on-surface": "#1b1d0e",
        "on-surface-variant": "#4e453e",
        "on-primary": "#ffffff",
        error: "#ba1a1a",
        "error-container": "#ffdad6"
      },
      fontFamily: {
        headline: ["Noto Serif SC", "serif"],
        body: ["Source Sans 3", "system-ui", "sans-serif"],
        mono: ["Fira Code", "Consolas", "monospace"]
      },
      borderRadius: {
        panel: "8px"
      }
    }
  },
  plugins: []
};
