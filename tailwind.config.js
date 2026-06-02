import typography from '@tailwindcss/typography';
import containerQueries from '@tailwindcss/container-queries';

/** @type {import('tailwindcss').Config} */
export default {
	darkMode: 'class',
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			colors: {
				myah: {
					pink: '#DF3377',
					'pink-dark': '#E94A8A',
					ink: '#0A0A0A',
					'ink-dark': '#F5F2ED',
					paper: '#FBFAF7',
					'paper-dark': '#201F1E',
					surface: '#FFFFFF',
					'surface-dark': '#262626',
					'surface-alt': '#F5F4F0',
					'surface-alt-dark': '#2E2D2C',
					line: '#DEE2DE',
					'line-dark': '#35332F',
					muted: '#737373',
					'muted-dark': '#A8A49C',
					muted2: '#A3A3A3',
					'muted2-dark': '#787470',
					body: '#404040',
					'body-dark': '#D2CEC6',
				}
			},
			fontFamily: {
				serif: ['"Instrument Serif"', '"Iowan Old Style"', 'Georgia', 'serif'],
				sans: ['"Inter"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
			},
			typography: {
				DEFAULT: {
					css: {
						pre: false,
						code: false,
						'pre code': false,
						'code::before': false,
						'code::after': false
					}
				}
			},
			padding: {
				'safe-bottom': 'env(safe-area-inset-bottom)'
			},
			transitionProperty: {
				width: 'width'
			}
		}
	},
	plugins: [typography, containerQueries]
};