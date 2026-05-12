<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	export let label = '';
	export let checked = false;
	export let action: string | undefined = undefined;
	export let messageId = '';

	const dispatch = createEventDispatcher();

	function handleToggle() {
		checked = !checked;
		dispatch('ui-interaction', {
			type: 'ui:toggle',
			action,
			checked,
			messageId
		});
	}

	$: trackBg = checked ? 'var(--myah-accent-green)' : 'var(--myah-bg-input)';
	$: thumbLeft = checked ? '18px' : '2px';
</script>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
	<span style="font-size:13px;color:var(--myah-text)">{label}</span>
	<button
		role="switch"
		aria-checked={checked}
		aria-label={label}
		on:click={handleToggle}
		style="position:relative;width:36px;height:20px;border-radius:10px;background:{trackBg};border:1px solid var(--myah-border-input);cursor:pointer;transition:background 0.2s;flex-shrink:0"
	>
		<span
			style="position:absolute;top:2px;left:{thumbLeft};width:14px;height:14px;border-radius:50%;background:var(--myah-text);transition:left 0.2s"
		></span>
	</button>
</div>
