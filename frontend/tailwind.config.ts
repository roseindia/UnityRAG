import type { Config } from 'tailwindcss'

// Design tokens come from the Frontend Design Document, section 14.1.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#2B4C7E', foreground: '#FFFFFF' },
        ink: { DEFAULT: '#1F2933', muted: '#617183' },
        canvas: '#F4F6F8',
        surface: '#FFFFFF',
        line: '#D8DEE6',
        nav: { DEFAULT: '#14213D', platform: '#2D1E3E', text: '#DBE4F0' },
        success: { DEFAULT: '#1D6B3A', bg: '#E3F4EA' },
        warning: { DEFAULT: '#8A5A00', bg: '#FFF4DC' },
        danger: { DEFAULT: '#B42318', bg: '#FDE8E7' },
        info: { bg: '#E8EEF6' },
        highlight: '#FFF1A8',
        chart: { 1: '#2B4C7E', 2: '#C2571A', 3: '#1D6B3A', 4: '#7A3E9D', 5: '#0E7490', 6: '#9A6700' },
      },
      fontFamily: {
        sans: ['Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'Consolas', 'monospace'],
      },
      fontSize: { xs: ['12px', '1.45'], sm: ['14px', '1.45'], base: ['16px', '1.45'] },
      borderRadius: { control: '6px', card: '8px', pill: '16px' },
      boxShadow: {
        raised: '0 4px 12px rgba(20,33,61,.12)',
        overlay: '0 12px 32px rgba(20,33,61,.22)',
      },
    },
  },
  plugins: [],
} satisfies Config
