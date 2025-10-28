module.exports = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          900: '#0f172a',
          800: '#1e293b',
          700: '#27354a'
        },
        accent: '#6366f1'
      },
      borderRadius: {
        xl: '16px'
      }
    }
  },
  plugins: []
};
