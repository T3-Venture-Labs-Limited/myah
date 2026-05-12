<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	export let fields: Array<{
		name: string;
		label: string;
		type: string;
		value?: string;
		hint?: string;
		placeholder?: string;
		options?: string[];
	}> = [];
	export let formId = '';
	export let submitLabel = 'Submit';
	export let submitAction = 'submit';
	export let messageId = '';
	export let componentId: string | undefined = undefined;

	const dispatch = createEventDispatcher();
	let values: Record<string, string> = {};
	let submitted = false;

	// Build default values from fields.  We assign a new object to `values`
	// (instead of mutating the existing one) to work around a Svelte 5
	// legacy-mode compiler bug: when `values` is mutated inside a reactive
	// block, the compiler's invalidation callback incorrectly references the
	// {#each} block variable `field` (which is out of scope), causing a
	// ReferenceError that crashes the entire component tree.
	$: values = fields.reduce((acc, f) => {
		if (!(f.name in acc)) acc[f.name] = f.value ?? '';
		return acc;
	}, values);

	function handleSubmit() {
		if (submitted) return;
		submitted = true;
		dispatch('ui-interaction', {
			type: 'TOOL_CALL_RESULT',
			toolCallId: messageId,
			componentId: componentId || formId,
			action: submitAction,
			result: {
				formId,
				submitAction,
				data: { ...values },
				timestamp: Date.now()
			}
		});
	}
</script>

<div
	style="background:var(--myah-bg-card);border-radius:var(--myah-radius);padding:16px;margin-bottom:12px"
>
	{#each fields as field}
		<div style="margin-bottom:12px">
			<label
				for={field.name}
				style="display:block;font-size:11px;color:var(--myah-text-muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:0.04em"
			>
				{field.label}
			</label>
			{#if field.type === 'textarea'}
				<textarea
					id={field.name}
					bind:value={values[field.name]}
					placeholder={field.hint || field.placeholder || ''}
					rows={4}
					disabled={submitted}
					style="width:100%;background:var(--myah-bg-input);border:1px solid var(--myah-border-input);border-radius:var(--myah-radius-sm);padding:8px 10px;color:var(--myah-text);font-size:13px;font-family:var(--myah-font);resize:vertical"
				></textarea>
			{:else if field.type === 'select'}
				<select
					id={field.name}
					bind:value={values[field.name]}
					disabled={submitted}
					style="width:100%;background:var(--myah-bg-input);border:1px solid var(--myah-border-input);border-radius:var(--myah-radius-sm);padding:8px 10px;color:var(--myah-text);font-size:13px;font-family:var(--myah-font)"
				>
					{#each field.options ?? [] as opt}
						<option value={opt}>{opt}</option>
					{/each}
				</select>
			{:else}
				<input
					id={field.name}
					type={field.type || 'text'}
					bind:value={values[field.name]}
					placeholder={field.hint || field.placeholder || ''}
					disabled={submitted}
					style="width:100%;background:var(--myah-bg-input);border:1px solid var(--myah-border-input);border-radius:var(--myah-radius-sm);padding:8px 10px;color:var(--myah-text);font-size:13px;font-family:var(--myah-font)"
				/>
			{/if}
		</div>
	{/each}
	<button
		on:click={handleSubmit}
		disabled={submitted}
		style="padding:8px 20px;border-radius:var(--myah-radius-sm);background:var(--myah-accent-blue);border:none;color:#000;font-size:13px;font-weight:500;cursor:{submitted
			? 'default'
			: 'pointer'};opacity:{submitted ? '0.5' : '1'};font-family:var(--myah-font)"
	>
		{#if submitted}
			Submitted
		{:else}
			{submitLabel}
		{/if}
	</button>
</div>
