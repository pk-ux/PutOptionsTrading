/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#f0f1ff',
          100: '#e0e4ff',
          200: '#c7cdfe',
          300: '#a5abfc',
          400: '#8182f8',
          500: '#667eea',
          600: '#5a5fdd',
          700: '#4c4cc3',
          800: '#3f3f9e',
          900: '#37377d',
        },
        secondary: {
          500: '#764ba2',
          600: '#6a4190',
        },
        dark: {
          50: '#f7f7f8',
          100: '#eeeef0',
          200: '#d9d9de',
          300: '#b8b8c1',
          400: '#91919f',
          500: '#747484',
          600: '#5e5e6c',
          700: '#4d4d58',
          800: '#42424b',
          900: '#1a1a2e',
          950: '#0f0f1a',
        },
      },
      backgroundImage: {
        'gradient-primary': 'linear-gradient(90deg, #667eea 0%, #764ba2 100%)',
      },
    },
  },
  plugins: [],
}
