<script lang="ts">
	import { onMount } from 'svelte';

	export let chartType: string = 'bar';
	export let labels: string[] = [];
	export let datasets: Array<{ label: string; data: number[]; color?: string }> = [];
	export let title: string = '';
	export let description: string = '';

	let canvas: HTMLCanvasElement;

	const PALETTE = [
		'#60a5fa', // blue
		'#4ade80', // green
		'#f87171', // red
		'#fbbf24', // amber
		'#a78bfa', // purple
		'#f472b6', // pink
		'#34d399', // emerald
		'#fb923c' // orange
	];

	const COLOR_MAP: Record<string, string> = {
		blue: '#60a5fa',
		green: '#4ade80',
		red: '#f87171',
		amber: '#fbbf24',
		purple: '#a78bfa',
		pink: '#f472b6',
		emerald: '#34d399',
		orange: '#fb923c',
		teal: '#2dd4bf',
		cyan: '#22d3ee'
	};

	function resolveColor(raw: string | undefined, idx: number): string {
		if (!raw) return PALETTE[idx % PALETTE.length];
		if (raw.startsWith('#') || raw.startsWith('rgb')) return raw;
		return COLOR_MAP[raw] ?? PALETTE[idx % PALETTE.length];
	}

	const isRadial = (t: string) => t === 'pie' || t === 'doughnut';

	onMount(async () => {
		const { Chart, registerables } = await import('chart.js');
		Chart.register(...registerables);

		// Guard: component may have been destroyed before the dynamic import resolved
		if (!canvas) return;

		const resolvedDatasets = datasets.map((ds, i) => {
			const color = resolveColor(ds.color, i);
			const isLine = chartType === 'line';
			return {
				label: ds.label,
				data: ds.data,
				backgroundColor: isLine
					? `${color}33` // ~20 % alpha fill under line
					: isRadial(chartType)
						? datasets.map((_, j) => resolveColor(undefined, j)) // distinct slices
						: color,
				borderColor: color,
				borderWidth: isLine ? 2 : isRadial(chartType) ? 1 : 0,
				tension: isLine ? 0.35 : 0,
				fill: isLine ? 'origin' : undefined,
				pointRadius: isLine ? 3 : 0,
				pointHoverRadius: isLine ? 5 : 0
			};
		});

		const gridColor = 'rgba(255,255,255,0.06)';
		const tickColor = '#666';

		new Chart(canvas, {
			type: chartType as 'bar' | 'line' | 'pie' | 'doughnut' | 'radar',
			data: { labels, datasets: resolvedDatasets },
			options: {
				responsive: true,
				maintainAspectRatio: true,
				animation: { duration: 400 },
				plugins: {
					legend: {
						display: datasets.length > 1 || isRadial(chartType),
						position: isRadial(chartType) ? 'bottom' : 'top',
						labels: { color: '#a3a3a3', font: { size: 11 }, boxWidth: 12, padding: 16 }
					},
					tooltip: {
						backgroundColor: '#1a1a1a',
						borderColor: '#2a2a2a',
						borderWidth: 1,
						titleColor: '#fafafa',
						bodyColor: '#a3a3a3',
						padding: 10
					}
				},
				scales:
					!isRadial(chartType) && chartType !== 'radar'
						? {
								x: {
									ticks: { color: tickColor, font: { size: 11 } },
									grid: { color: gridColor }
								},
								y: {
									ticks: { color: tickColor, font: { size: 11 } },
									grid: { color: gridColor }
								}
							}
						: undefined
			}
		});
	});
</script>

<div
	style="background:var(--myah-bg-card);border:1px solid var(--myah-border);border-radius:var(--myah-radius);padding:16px;margin-bottom:12px"
>
	{#if title}
		<div style="font-size:13px;font-weight:600;color:var(--myah-text);margin-bottom:4px">
			{title}
		</div>
	{/if}
	{#if description}
		<div style="font-size:11px;color:var(--myah-text-muted);margin-bottom:10px">{description}</div>
	{/if}
	<canvas bind:this={canvas}></canvas>
</div>
