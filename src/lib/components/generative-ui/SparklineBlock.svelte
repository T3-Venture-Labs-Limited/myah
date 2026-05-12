<script lang="ts">
	export let values: number[] = [];
	export let color: string | undefined = undefined;

	const width = 80;
	const height = 28;
	const strokeColor = color ?? 'var(--myah-accent-blue)';

	// Build SVG polyline points string from values
	$: points = (() => {
		if (values.length < 2) return '';
		const min = Math.min(...values);
		const max = Math.max(...values);
		const range = max - min || 1;
		const step = width / (values.length - 1);
		return values
			.map((v, i) => {
				const x = i * step;
				const y = height - ((v - min) / range) * (height - 4) - 2;
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	})();
</script>

<svg
	{width}
	{height}
	viewBox="0 0 {width} {height}"
	style="display:inline-block;vertical-align:middle"
	aria-hidden="true"
>
	{#if points}
		<polyline
			{points}
			fill="none"
			stroke={strokeColor}
			stroke-width="1.5"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
	{/if}
</svg>
