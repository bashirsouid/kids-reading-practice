/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        surface2: 'var(--surface2)',
        accent: 'var(--accent)',
        gold: 'var(--gold)',
        text: 'var(--text)',
        'text-dim': 'var(--text-dim)',
      },
      fontFamily: {
        'bangers': ['"Bangers"', 'cursive'],
        'inter': ['"Inter"', 'sans-serif'],
      },
      maxWidth: {
        '8xl': '1600px',
      },
    },
  },
  plugins: [],
}