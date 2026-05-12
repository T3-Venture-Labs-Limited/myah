<script lang="ts">
	export let items: Array<{ title?: string; description?: string; src?: string }> = [];

	let index = 0;

	function prev() {
		index = (index - 1 + items.length) % items.length;
	}

	function next() {
		index = (index + 1) % items.length;
	}
</script>

<div style="margin-bottom:12px">
	<!-- Card display -->
	<div
		style="background:var(--myah-bg-card);border:1px solid var(--myah-border);border-radius:var(--myah-radius);overflow:hidden"
	>
		{#if items[index]?.src}
			<img
				src={items[index].src}
				alt={items[index].title ?? ''}
				style="width:100%;max-height:160px;object-fit:cover;display:block"
			/>
		{/if}
		{#if items[index]?.title || items[index]?.description}
			<div style="padding:12px">
				{#if items[index]?.title}
					<div style="font-size:13px;font-weight:600;color:var(--myah-text);margin-bottom:4px">
						{items[index].title}
					</div>
				{/if}
				{#if items[index]?.description}
					<div style="font-size:12px;color:var(--myah-text-muted)">{items[index].description}</div>
				{/if}
			</div>
		{/if}
	</div>
	<!-- Navigation -->
	{#if items.length > 1}
		<div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px">
			<button
				on:click={prev}
				style="padding:4px 10px;background:var(--myah-bg-card);border:1px solid var(--myah-border);border-radius:var(--myah-radius-sm);color:var(--myah-text);font-size:13px;cursor:pointer;font-family:var(--myah-font)"
			>
				‹
			</button>
			<span style="font-size:11px;color:var(--myah-text-muted)">{index + 1} / {items.length}</span>
			<button
				on:click={next}
				style="padding:4px 10px;background:var(--myah-bg-card);border:1px solid var(--myah-border);border-radius:var(--myah-radius-sm);color:var(--myah-text);font-size:13px;cursor:pointer;font-family:var(--myah-font)"
			>
				›
			</button>
		</div>
	{/if}
</div>
