<script lang="ts">
	export let name = '';
	export let subtitle: string | undefined = undefined;
	export let src: string | undefined = undefined;

	// Derive initials from name: take first letter of each word, max 2
	$: initials = name
		.split(' ')
		.filter(Boolean)
		.slice(0, 2)
		.map((w) => w[0].toUpperCase())
		.join('');
</script>

<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
	<!-- Avatar circle / image -->
	{#if src}
		<img
			{src}
			alt={name}
			style="width:36px;height:36px;border-radius:50%;object-fit:cover;flex-shrink:0"
		/>
	{:else}
		<div
			style="width:36px;height:36px;border-radius:50%;background:var(--myah-accent-blue);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#000;flex-shrink:0"
		>
			{initials}
		</div>
	{/if}
	<!-- Text -->
	<div>
		<div style="font-size:13px;font-weight:600;color:var(--myah-text)">{name}</div>
		{#if subtitle}
			<div style="font-size:11px;color:var(--myah-text-muted);margin-top:1px">{subtitle}</div>
		{/if}
	</div>
</div>
