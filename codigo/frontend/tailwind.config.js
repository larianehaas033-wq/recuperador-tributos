export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: '#0B1F3A', 700: '#13294B', 600: '#1C3760', 100: '#E7ECF3', 50: '#F3F6FA' },
        gold: { DEFAULT: '#C9A24B', 600: '#B08A35', 100: '#F6EEDC' },
        paper: '#F6F7F9', ink: '#1A2230', muted: '#5D6878', line: '#E1E5EB',
        ok: '#1E7A4C', warn: '#B26B00', bad: '#B42318',
      },
      fontFamily: { sans: ['Figtree', 'Segoe UI', 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
}
