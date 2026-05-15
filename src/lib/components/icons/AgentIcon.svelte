<script lang="ts">
	export let className = 'size-4';
	export let strokeWidth = '1.5';
</script>

<svg
	stroke-width={strokeWidth}
	stroke="currentColor"
	class={className}
	aria-hidden="true"
	xmlns="http://www.w3.org/2000/svg"
	fill="none"
	viewBox="0 0 24 24"
	width="24"
	height="24"
>
	<rect x="4" y="7" width="16" height="14" rx="3" />
	<circle cx="9" cy="13" r="1" fill="currentColor" />
	<circle cx="15" cy="13" r="1" fill="currentColor" />
	<line x1="10" y1="17" x2="14" y2="17" />
	<line x1="12" y1="7" x2="12" y2="3" />
	<circle cx="12" cy="2" r="1.5" />
</svg>
