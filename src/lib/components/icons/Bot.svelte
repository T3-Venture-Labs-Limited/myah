<script lang="ts">
	export let className = 'w-4 h-4';
	export let strokeWidth = '1.5';
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	fill="none"
	viewBox="0 0 24 24"
	stroke-width={strokeWidth}
	aria-hidden="true"
	stroke="currentColor"
	class={className}
>
	<path stroke-linecap="round" stroke-linejoin="round" d="M12 8V4H8" />
	<rect x="4" y="8" width="16" height="12" rx="2" stroke-linejoin="round" />
	<path stroke-linecap="round" stroke-linejoin="round" d="M2 14h2" />
	<path stroke-linecap="round" stroke-linejoin="round" d="M20 14h2" />
	<path stroke-linecap="round" stroke-linejoin="round" d="M15 13v2" />
	<path stroke-linecap="round" stroke-linejoin="round" d="M9 13v2" />
</svg>
