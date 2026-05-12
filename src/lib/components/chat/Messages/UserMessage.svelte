<script lang="ts">
	import dayjs from 'dayjs';
	import { toast } from 'svelte-sonner';
	import { tick, getContext, onMount } from 'svelte';

	import { models, settings } from '$lib/stores';
	import { user as _user } from '$lib/stores';
	import { copyToClipboard as _copyToClipboard, formatDate } from '$lib/utils';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

	import Name from './Name.svelte';
	import ProfileImage from './ProfileImage.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import Markdown from './Markdown.svelte';
	import Image from '$lib/components/common/Image.svelte';
	import UserMessageRefs from './UserMessageRefs.svelte';
	// Workstream H Path 2 cleanup: edit/delete were removed.
	// See cleanup note in Messages.svelte for the architectural rationale.

	import localizedFormat from 'dayjs/plugin/localizedFormat';

	function parseActionEnvelope(content: string) {
		const startIdx = content.indexOf('[UI_ACTION]');
		const endIdx = content.indexOf('[/UI_ACTION]');
		if (startIdx === -1 || endIdx === -1 || endIdx <= startIdx) return null;
		try {
			const jsonStr = content.slice(startIdx + '[UI_ACTION]'.length, endIdx).trim();
			const parsed = JSON.parse(jsonStr);
			if (parsed?.type !== 'ui:action' && parsed?.type !== 'ui:submit') return null;
			return parsed as { type: 'ui:action' | 'ui:submit'; action?: string; formId?: string };
		} catch {
			return null;
		}
	}

	const i18n = getContext('i18n');
	dayjs.extend(localizedFormat);

	export let user;

	export let chatId;
	export let history;
	export let messageId;

	export let siblings;

	export let gotoMessage: Function;
	export let showPreviousMessage: Function;
	export let showNextMessage: Function;

	export let isFirstMessage: boolean;
	export let readOnly: boolean;
	export let editCodeBlock = true;
	export let topPadding = false;

	let messageIndexEdit = false;

	let message = structuredClone(history.messages[messageId]);
	$: if (history.messages) {
		const source = history.messages[messageId];
		if (source) {
			if (message.content !== source.content) {
				message = structuredClone(source);
			} else if (JSON.stringify(message) !== JSON.stringify(source)) {
				message = structuredClone(source);
			}
		}
	}

	$: actionEnvelope = parseActionEnvelope(message.content ?? '');

	const copyToClipboard = async (text) => {
		const res = await _copyToClipboard(text);
		if (res) {
			toast.success($i18n.t('Copying to clipboard was successful!'));
		}
	};

	onMount(() => {
		// console.log('UserMessage mounted');
	});
</script>

<div
	class=" flex w-full user-message group"
	dir={$settings.chatDirection}
	id="message-{message.id}"
	style="scroll-margin-top: 3rem;"
>
	{#if !($settings?.chatBubble ?? true)}
		<div class={`shrink-0 ltr:mr-3 rtl:ml-3 mt-1`}>
			<ProfileImage
				src={user?.id
					? `${WEBUI_API_BASE_URL}/users/${user.id}/profile/image`
					: `${WEBUI_BASE_URL}/static/favicon.png`}
				className={'size-8 user-message-profile-image'}
			/>
		</div>
	{/if}
	<div class="flex-auto w-0 max-w-full pl-1">
		{#if !($settings?.chatBubble ?? true)}
			<div>
				<Name>
					{#if message.user}
						{$i18n.t('You')}
						<span class=" text-gray-500 text-sm font-medium">{message?.user ?? ''}</span>
					{:else if $settings.showUsername || $_user?.name !== user?.name}
						{user?.name ?? $i18n.t('You')}
					{:else}
						{$i18n.t('You')}
					{/if}

					{#if message.timestamp}
						<div
							class="self-center text-xs font-medium first-letter:capitalize ml-0.5 translate-y-[1px] {($settings?.highContrastMode ??
							false)
								? 'dark:text-gray-900 text-gray-100'
								: 'invisible group-hover:visible transition'}"
						>
							<Tooltip content={dayjs(message.timestamp * 1000).format('LLLL')}>
								<!-- $i18n.t('Today at {{LOCALIZED_TIME}}') -->
								<!-- $i18n.t('Yesterday at {{LOCALIZED_TIME}}') -->
								<!-- $i18n.t('{{LOCALIZED_DATE}} at {{LOCALIZED_TIME}}') -->

								<span class="line-clamp-1"
									>{$i18n.t(formatDate(message.timestamp * 1000), {
										LOCALIZED_TIME: dayjs(message.timestamp * 1000).format('LT'),
										LOCALIZED_DATE: dayjs(message.timestamp * 1000).format('L')
									})}</span
								>
							</Tooltip>
						</div>
					{/if}
				</Name>
			</div>
		{:else if message.timestamp}
			<div class="flex justify-end pr-2 text-xs">
				<div
					class="text-[0.65rem] font-medium first-letter:capitalize mb-0.5 {($settings?.highContrastMode ??
					false)
						? 'dark:text-gray-100 text-gray-900'
						: 'invisible group-hover:visible transition text-gray-400'}"
				>
					<Tooltip content={dayjs(message.timestamp * 1000).format('LLLL')}>
						<span class="line-clamp-1"
							>{$i18n.t(formatDate(message.timestamp * 1000), {
								LOCALIZED_TIME: dayjs(message.timestamp * 1000).format('LT'),
								LOCALIZED_DATE: dayjs(message.timestamp * 1000).format('L')
							})}</span
						>
					</Tooltip>
				</div>
			</div>
		{/if}

		<div class="chat-{message.role} w-full min-w-full markdown-prose">
			{#if Array.isArray(message.refs) && message.refs.length > 0}
				<UserMessageRefs
					refs={message.refs}
					align={($settings?.chatBubble ?? true) ? 'end' : 'start'}
				/>
			{/if}
			{#if message.files}
				<div
					class="mb-1 w-full flex flex-col justify-end overflow-x-auto gap-1 flex-wrap"
					dir={$settings?.chatDirection ?? 'auto'}
				>
					{#each message.files as file}
						{@const fileUrl =
							file.url?.startsWith('data') || file.url?.startsWith('http')
								? file.url
								: `${WEBUI_API_BASE_URL}/files/${file.url}${file?.content_type ? '/content' : ''}`}
						<div class={($settings?.chatBubble ?? true) ? 'self-end' : ''}>
							{#if file.type === 'image' || (file?.content_type ?? '').startsWith('image/')}
								<Image src={fileUrl} imageClassName=" max-h-96 rounded-lg" />
							{:else}
								<FileItem
									item={file}
									url={file.url}
									name={file.name}
									type={file.type}
									size={file?.size}
									small={true}
								/>
							{/if}
						</div>
					{/each}
				</div>
			{/if}

			{#if (message?.content ?? '') !== ''}
				<div class="w-full">
					{#if actionEnvelope}
						<div class="flex {($settings?.chatBubble ?? true) ? 'justify-end pb-1' : 'w-full'}">
							<div
								class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500 italic py-1 px-2"
							>
								<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0"
								></span>
								{#if actionEnvelope.type === 'ui:submit'}
									Submitted {actionEnvelope.formId || 'form'}
								{:else}
									Clicked {actionEnvelope.action || 'action'}
								{/if}
							</div>
						</div>
					{:else}
						<div class="flex {($settings?.chatBubble ?? true) ? 'justify-end pb-1' : 'w-full'}">
							<div
								class="rounded-3xl {($settings?.chatBubble ?? true)
									? `max-w-[90%] px-4 py-1.5  bg-gray-50 dark:bg-gray-850 ${
											message.files ? 'rounded-tr-lg' : ''
										}`
									: ' w-full'}"
							>
								<Markdown
									id={`${chatId}-${message.id}`}
									content={message.content}
									{editCodeBlock}
									{topPadding}
								/>
							</div>
						</div>
					{/if}
				</div>
			{/if}

			{#if !actionEnvelope}
					<div
						class=" flex {($settings?.chatBubble ?? true)
							? 'justify-end'
							: ''}  text-gray-600 dark:text-gray-500"
					>
						{#if !($settings?.chatBubble ?? true)}
							{#if siblings.length > 1}
								<div class="flex self-center" dir="ltr">
									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showPreviousMessage(message);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M15.75 19.5 8.25 12l7.5-7.5"
											/>
										</svg>
									</button>

									{#if messageIndexEdit}
										<div
											class="text-sm flex justify-center font-semibold self-center dark:text-gray-100 min-w-fit"
										>
											<input
												id="message-index-input-{message.id}"
												type="number"
												value={siblings.indexOf(message.id) + 1}
												min="1"
												max={siblings.length}
												on:focus={(e) => {
													e.target.select();
												}}
												on:blur={(e) => {
													gotoMessage(message, e.target.value - 1);
													messageIndexEdit = false;
												}}
												on:keydown={(e) => {
													if (e.key === 'Enter') {
														gotoMessage(message, e.target.value - 1);
														messageIndexEdit = false;
													}
												}}
												class="bg-transparent font-semibold self-center dark:text-gray-100 min-w-fit outline-hidden"
											/>/{siblings.length}
										</div>
									{:else}
										<!-- svelte-ignore a11y-no-static-element-interactions -->
										<div
											class="text-sm tracking-widest font-semibold self-center dark:text-gray-100 min-w-fit"
											on:dblclick={async () => {
												messageIndexEdit = true;

												await tick();
												const input = document.getElementById(`message-index-input-${message.id}`);
												if (input) {
													input.focus();
													input.select();
												}
											}}
										>
											{siblings.indexOf(message.id) + 1}/{siblings.length}
										</div>
									{/if}

									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showNextMessage(message);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="m8.25 4.5 7.5 7.5-7.5 7.5"
											/>
										</svg>
									</button>
								</div>
							{/if}
						{/if}
						{#if message?.content}
							<Tooltip content={$i18n.t('Copy')} placement="bottom">
								<button
									class="{($settings?.highContrastMode ?? false)
										? ''
										: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
									on:click={() => {
										copyToClipboard(message.content);
									}}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="2.3"
										stroke="currentColor"
										class="w-4 h-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184"
										/>
									</svg>
								</button>
							</Tooltip>
						{/if}



						{#if $settings?.chatBubble ?? true}
							{#if siblings.length > 1}
								<div class="flex self-center" dir="ltr">
									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showPreviousMessage(message);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M15.75 19.5 8.25 12l7.5-7.5"
											/>
										</svg>
									</button>

									{#if messageIndexEdit}
										<div
											class="text-sm flex justify-center font-semibold self-center dark:text-gray-100 min-w-fit"
										>
											<input
												id="message-index-input-{message.id}"
												type="number"
												value={siblings.indexOf(message.id) + 1}
												min="1"
												max={siblings.length}
												on:focus={(e) => {
													e.target.select();
												}}
												on:blur={(e) => {
													gotoMessage(message, e.target.value - 1);
													messageIndexEdit = false;
												}}
												on:keydown={(e) => {
													if (e.key === 'Enter') {
														gotoMessage(message, e.target.value - 1);
														messageIndexEdit = false;
													}
												}}
												class="bg-transparent font-semibold self-center dark:text-gray-100 min-w-fit outline-hidden"
											/>/{siblings.length}
										</div>
									{:else}
										<!-- svelte-ignore a11y-no-static-element-interactions -->
										<div
											class="text-sm tracking-widest font-semibold self-center dark:text-gray-100 min-w-fit"
											on:dblclick={async () => {
												messageIndexEdit = true;

												await tick();
												const input = document.getElementById(`message-index-input-${message.id}`);
												if (input) {
													input.focus();
													input.select();
												}
											}}
										>
											{siblings.indexOf(message.id) + 1}/{siblings.length}
										</div>
									{/if}

									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showNextMessage(message);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="m8.25 4.5 7.5 7.5-7.5 7.5"
											/>
										</svg>
									</button>
								</div>
						{/if}
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
