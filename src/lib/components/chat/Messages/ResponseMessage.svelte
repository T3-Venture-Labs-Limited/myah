<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';

	import { createEventDispatcher, onDestroy } from 'svelte';
	import { onMount, tick, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType, t } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	const dispatch = createEventDispatcher();

	import { config, models, settings, temporaryChatEnabled, user } from '$lib/stores';
	import {
		copyToClipboard as _copyToClipboard,
		approximateToHumanReadable,
		getMessageContentParts,
		sanitizeResponseContent,
		formatDate,
		removeDetails,
		removeAllDetails
	} from '$lib/utils';
	import Name from './Name.svelte';
	import Skeleton from './Skeleton.svelte';
	import Image from '$lib/components/common/Image.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import { openMessageFeedback } from '$lib/utils/sentryFeedback';

	// Workstream H Path 2 cleanup: DeleteConfirmDialog import removed.
	// See cleanup note in Messages.svelte for the architectural rationale.

	import Error from './Error.svelte';
	import ContentRenderer from './ContentRenderer.svelte';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import FollowUps from './ResponseMessage/FollowUps.svelte';
	import { fade } from 'svelte/transition';
	import { flyAndScale } from '$lib/utils/transitions';
	// Workstream H Path 2 cleanup: RegenerateMenu import removed.
	import StatusHistory from './ResponseMessage/StatusHistory.svelte';
	import FullHeightIframe from '$lib/components/common/FullHeightIframe.svelte';
	import HermesOutputRenderer from './HermesOutputRenderer.svelte';
	import type { OutputItem } from './HermesOutputRenderer/types';
	import { filterTodoToolOutput } from '$lib/utils/todoOutput';
	import CronRunMessage from './CronRunMessage.svelte';

	interface MessageType {
		id: string;
		model: string;
		content: string;
		files?: { type: string; url: string }[];
		timestamp: number;
		role: string;
		statusHistory?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		}[];
		status?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		};
		done: boolean;
		error?: boolean | { content: string };
		info?: {
			openai?: boolean;
			prompt_tokens?: number;
			completion_tokens?: number;
			total_tokens?: number;
			eval_count?: number;
			eval_duration?: number;
			prompt_eval_count?: number;
			prompt_eval_duration?: number;
			total_duration?: number;
			load_duration?: number;
			usage?: unknown;
		};
		annotation?: { type: string; rating: number };
		output?: OutputItem[];
		modelUsed?: { id: string; provider?: string };
	}

	export let chatId = '';
	export let history;
	export let messageId;
	export let selectedModels = [];

	let message: MessageType = structuredClone(history.messages[messageId]);
	$: if (history.messages) {
		const source = history.messages[messageId];
		if (source) {
			// Fast path: O(1) check on the fields that change most often (content during streaming, done at end)
			// Avoids 2x O(n) JSON.stringify calls that are always true during streaming anyway
			if (message.content !== source.content || message.done !== source.done) {
				message = structuredClone(source);
			} else if (JSON.stringify(message) !== JSON.stringify(source)) {
				// Slow path: full comparison for infrequent changes (sources, annotations, status, etc.)
				message = structuredClone(source);
			}
		}
	}

	export let siblings;

	export let setInputText: Function = () => {};
	export let gotoMessage: Function = () => {};
	export let showPreviousMessage: Function;
	export let showNextMessage: Function;

	export let updateChat: Function;
	export let saveMessage: Function;
	export let rateMessage: Function;
	export let actionMessage: Function;
	export let sendMessage: Function = () => {};

	export let submitMessage: Function;

	export let addMessages: Function;

	export let isLastMessage = true;
	export let readOnly = false;
	export let editCodeBlock = true;
	export let topPadding = false;

	let contentContainerElement: HTMLDivElement;
	let buttonsContainerElement: HTMLDivElement;

	let model = null;
	$: model = $models.find((m) => m.id === message.model);

	$: statusEntries = message?.statusHistory ?? [...(message?.status ? [message?.status] : [])];
	$: renderedOutput = filterTodoToolOutput(message?.output as OutputItem[] | undefined);
	$: hasVisibleStatus =
		(model?.info?.meta?.capabilities?.status_updates ?? true) &&
		statusEntries.length > 0 &&
		!(statusEntries.at(-1)?.hidden ?? false);

	// Use the output-array renderer when the message has structured output items.
	// Falls back to ContentRenderer for older messages or non-Hermes responses.
	$: useOutputRenderer = Array.isArray(message?.output) && message.output.length > 0;

	$: isCronRun =
		message?.content?.startsWith('**Cron run** (') ||
		message?.content?.startsWith('⚠️**Cron run** (');

	let messageIndexEdit = false;

	// Workstream H Path 2 cleanup: edit-mode was removed (no inline editing of assistant
	// responses), but the `{#if !edit}` gate around the action buttons block was left in
	// place to keep diff size small. Declare `edit` as a permanent `false` so the gate
	// stays satisfied and the buttons render unconditionally.
	const edit = false;

	const copyToClipboard = async (text) => {
		text = removeAllDetails(text);

		if (($config?.ui?.response_watermark ?? '').trim() !== '') {
			text = `${text}\n\n${$config?.ui?.response_watermark}`;
		}

		const res = await _copyToClipboard(text, null, $settings?.copyFormatted ?? false);
		if (res) {
			toast.success($i18n.t('Copying to clipboard was successful!'));
		}
	};

	// Workstream H Path 2 cleanup: edit/regenerate/delete handlers were removed.
	// See cleanup note in Messages.svelte for the architectural rationale.

	let feedbackLoading = false;
	let thumbsUpShaking = false;

	const feedbackHandler = async (
		rating: number | null = null,
		_details: object | null = null
	) => {
		if (rating === null) return;
		if (rating === 1) {
			if (thumbsUpShaking) return;
			thumbsUpShaking = true;
			setTimeout(() => {
				thumbsUpShaking = false;
			}, 500);
			return;
		}
		if (feedbackLoading) return;
		feedbackLoading = true;
		try {
			await openMessageFeedback({
				rating,
				chatId,
				messageId: message.id,
				messageContent: message.content,
				model: message.model
			});
		} finally {
			feedbackLoading = false;
		}
	};

	const buttonsWheelHandler = (event: WheelEvent) => {
		if (buttonsContainerElement) {
			if (buttonsContainerElement.scrollWidth <= buttonsContainerElement.clientWidth) {
				// If the container is not scrollable, horizontal scroll
				return;
			} else {
				event.preventDefault();

				if (event.deltaY !== 0) {
					// Adjust horizontal scroll position based on vertical scroll
					buttonsContainerElement.scrollLeft += event.deltaY;
				}
			}
		}
	};

	const contentCopyHandler = (e) => {
		if (contentContainerElement) {
			e.preventDefault();
			// Get the selected HTML
			const selection = window.getSelection();
			const range = selection.getRangeAt(0);
			const tempDiv = document.createElement('div');

			// Remove background, color, and font styles
			tempDiv.appendChild(range.cloneContents());

			tempDiv.querySelectorAll('table').forEach((table) => {
				table.style.borderCollapse = 'collapse';
				table.style.width = 'auto';
				table.style.tableLayout = 'auto';
			});

			tempDiv.querySelectorAll('th').forEach((th) => {
				th.style.whiteSpace = 'nowrap';
				th.style.padding = '4px 8px';
			});

			// Put cleaned HTML + plain text into clipboard
			e.clipboardData.setData('text/html', tempDiv.innerHTML);
			e.clipboardData.setData('text/plain', selection.toString());
		}
	};

	onMount(async () => {
		// console.log('ResponseMessage mounted');

		await tick();
		if (buttonsContainerElement) {
			buttonsContainerElement.addEventListener('wheel', buttonsWheelHandler);
		}

		if (contentContainerElement) {
			contentContainerElement.addEventListener('copy', contentCopyHandler);
		}
	});

	onDestroy(() => {
		if (buttonsContainerElement) {
			buttonsContainerElement.removeEventListener('wheel', buttonsWheelHandler);
		}

		if (contentContainerElement) {
			contentContainerElement.removeEventListener('copy', contentCopyHandler);
		}
	});
</script>

{#key message.id}
	<div
		class=" flex w-full message-{message.id}"
		id="message-{message.id}"
		dir={$settings.chatDirection}
		style="scroll-margin-top: 3rem;"
	>
		<div class={`shrink-0 ltr:mr-3 rtl:ml-3 hidden @lg:flex mt-1 `}>
			<img
				src="/static/logo-mark.svg"
				class="size-8 dark:invert"
				aria-hidden="true"
				alt="profile"
				draggable="false"
			/>
		</div>

		<div class="flex-auto w-0 pl-1 relative">
			<Name>
				<Tooltip content={model?.name ?? message.model} placement="top-start">
					<span id="response-message-model-name" class="line-clamp-1 text-black dark:text-white">
						{model?.name ?? message.model}
					</span>
				</Tooltip>

				{#if message.timestamp}
					<div
						class="self-center text-xs font-medium first-letter:capitalize ml-0.5 translate-y-[1px] {($settings?.highContrastMode ??
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
				{/if}
			</Name>

			<div>
				<div class="chat-{message.role} w-full min-w-full markdown-prose">
					<div>
						{#if !useOutputRenderer && (model?.info?.meta?.capabilities?.status_updates ?? true)}
							<StatusHistory statusHistory={message?.statusHistory} />
						{/if}

						{#if message?.files && message.files?.filter((f) => f.type === 'image').length > 0}
							<div
								class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap"
								dir={$settings?.chatDirection ?? 'auto'}
							>
								{#each message.files as file}
									<div>
										{#if file.type === 'image' || (file?.content_type ?? '').startsWith('image/')}
											<Image src={file.url} alt={message.content} />
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

						{#if message?.embeds && message.embeds.length > 0}
							<div
								class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap"
								id={`${message.id}-embeds-container`}
							>
								{#each message.embeds as embed, idx}
									<div class="my-2 w-full" id={`${message.id}-embeds-${idx}`}>
										<FullHeightIframe
											src={embed}
											allowScripts={true}
											allowForms={true}
											allowSameOrigin={$settings?.iframeSandboxAllowSameOrigin ?? false}
											allowPopups={true}
										/>
									</div>
								{/each}
							</div>
						{/if}


						<div
							bind:this={contentContainerElement}
							class="w-full flex flex-col relative"
							id="response-content-container"
						>
							{#if message.content === '' && !message.done && !message.error && !hasVisibleStatus && !useOutputRenderer}
								<Skeleton />
							{:else if isCronRun}
								<CronRunMessage {message} output={message.output} />
							{:else if useOutputRenderer && message.error !== true && renderedOutput.length > 0}
								<HermesOutputRenderer
									output={renderedOutput}
									messageId={message.id}
									done={($settings?.chatFadeStreamingText ?? true)
										? (message?.done ?? false)
										: true}
									on:retry={async () => {
										// ConfirmationCard 404 recovery (Task 2.1):
										// create a fresh assistant branch from the original
										// parent user message. Using submitMessage(parentId,
										// originalPrompt) would create a duplicate user message
										// as a child of the original user message (user → user),
										// which corrupts the chat tree. sendMessage(history,
										// parentId) is the surviving append-only retry shape
										// after regenerateResponse was removed.
										const parentId = message?.parentId;
										if (!parentId) return;
										await sendMessage(history, parentId);
									}}
								/>
							{:else if message.content && message.error !== true}
								<!-- always show message contents even if there's an error -->
								<!-- unless message.error === true which is legacy error handling, where the error message is stored in message.content -->
						<ContentRenderer
								id={`${chatId}-${message.id}`}
								messageId={message.id}
								{history}
								{selectedModels}
								content={message.content}
								floatingButtons={message?.done &&
										!readOnly &&
										($settings?.showFloatingActionButtons ?? true)}
									save={!readOnly}
									preview={!readOnly}
									{editCodeBlock}
									{topPadding}
									done={($settings?.chatFadeStreamingText ?? true)
										? (message?.done ?? false)
										: true}
									{model}
									onTaskClick={async (e) => {
										console.log(e);
									}}
									onSourceClick={async (id) => {
										console.log(id);
									}}
									onAddMessages={({ modelId, parentId, messages }) => {
										addMessages({ modelId, parentId, messages });
									}}
									onSave={({ raw, oldContent, newContent }) => {
										history.messages[message.id].content = history.messages[
											message.id
										].content.replace(raw, raw.replace(oldContent, newContent));

										updateChat();
									}}
								/>
							{/if}

							{#if message?.error}
								<Error content={message?.error?.content ?? message.content} />
							{/if}

					</div>
					</div>
				</div>

				{#if message?.modelUsed?.id && message?.modelUsed?.id !== 'myah'}
					<div
						class="flex items-center gap-1 mt-1 text-[0.7rem] text-gray-500 dark:text-gray-400 font-primary select-none"
						title={message.modelUsed.provider
							? `${message.modelUsed.id} via ${message.modelUsed.provider}`
							: message.modelUsed.id}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-3 h-3"
							aria-hidden="true"
						>
							<path
								fill-rule="evenodd"
								d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
								clip-rule="evenodd"
							/>
						</svg>
						<span class="truncate max-w-[20rem]">{message.modelUsed.id}</span>
						{#if message.modelUsed.provider}
							<span class="text-gray-400 dark:text-gray-500">· {message.modelUsed.provider}</span>
						{/if}
					</div>
				{/if}

				{#if !edit}
					<div
						bind:this={buttonsContainerElement}
						class="flex justify-start overflow-x-auto buttons text-gray-600 dark:text-gray-500 mt-0.5"
					>
						{#if message.done || siblings.length > 1}
							{#if siblings.length > 1}
								<div class="flex self-center min-w-fit" dir="ltr">
									<button
										aria-label={$i18n.t('Previous message')}
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showPreviousMessage(message);
										}}
									>
										<svg
											aria-hidden="true"
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
										aria-label={$i18n.t('Next message')}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											aria-hidden="true"
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

							{#if message.done}
								<Tooltip content={$i18n.t('Copy')} placement="bottom">
									<button
										aria-label={$i18n.t('Copy')}
										class="{isLastMessage || ($settings?.highContrastMode ?? false)
											? 'visible'
											: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition copy-response-button"
										on:click={() => {
											copyToClipboard(message.content);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											aria-hidden="true"
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

								{#if message.usage}
									<Tooltip
										content={message.usage
											? `<pre>${sanitizeResponseContent(
													JSON.stringify(message.usage, null, 2)
														.replace(/"([^(")"]+)":/g, '$1:')
														.slice(1, -1)
														.split('\n')
														.map((line) => line.slice(2))
														.map((line) => (line.endsWith(',') ? line.slice(0, -1) : line))
														.join('\n')
												)}</pre>`
											: ''}
										placement="bottom"
									>
										<button
											aria-hidden="true"
											class=" {isLastMessage || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition whitespace-pre-wrap"
											on:click={() => {
												console.log(message);
											}}
											id="info-{message.id}"
										>
											<svg
												aria-hidden="true"
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
													d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
												/>
											</svg>
										</button>
									</Tooltip>
								{/if}

								{#if !readOnly}
									{#if !$temporaryChatEnabled && ($config?.features.enable_message_rating ?? true) && ($user?.role === 'admin' || ($user?.permissions?.chat?.rate_response ?? true))}
										<Tooltip content={$i18n.t('Good Response')} placement="bottom">
											<button
												aria-label={$i18n.t('Good Response')}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg {(
													message?.annotation?.rating ?? ''
												).toString() === '1'
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition {thumbsUpShaking
													? 'thumbs-up-shake'
													: ''}"
												on:click={async () => {
													await feedbackHandler(1);
												}}
											>
												<svg
													aria-hidden="true"
													stroke="currentColor"
													fill="none"
													stroke-width="2.3"
													viewBox="0 0 24 24"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="w-4 h-4"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
													/>
												</svg>
											</button>
										</Tooltip>

										<Tooltip content={$i18n.t('Bad Response')} placement="bottom">
											<button
												aria-label={$i18n.t('Bad Response')}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg {(
													message?.annotation?.rating ?? ''
												).toString() === '-1'
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition disabled:cursor-progress disabled:hover:bg-transparent"
												disabled={feedbackLoading}
												on:click={async () => {
													await feedbackHandler(-1);
												}}
											>
												<svg
													aria-hidden="true"
													stroke="currentColor"
													fill="none"
													stroke-width="2.3"
													viewBox="0 0 24 24"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="w-4 h-4"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"
													/>
												</svg>
											</button>
										</Tooltip>
									{/if}


									{#each model?.actions ?? [] as action}
										<Tooltip content={action.name} placement="bottom">
											<button
												type="button"
												aria-label={action.name}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
												on:click={() => {
													actionMessage(action.id, message);
												}}
											>
												{#if action?.icon}
													<div class="size-4">
														<img
															src={action.icon}
															class="w-4 h-4 {action.icon.includes('data:image/svg')
																? 'dark:invert-[80%]'
																: ''}"
															style="fill: currentColor;"
															alt={action.name}
														/>
													</div>
												{:else}
													<Sparkles strokeWidth="2.1" className="size-4" />
												{/if}
											</button>
										</Tooltip>
									{/each}
								{/if}
							{/if}
						{/if}
					</div>



					{#if (isLastMessage || ($settings?.keepFollowUpPrompts ?? false)) && message.done && !readOnly && (message?.followUps ?? []).length > 0}
						<div class="mt-2.5" in:fade={{ duration: 100 }}>
							<FollowUps
								followUps={message?.followUps}
								onClick={(prompt) => {
									if ($settings?.insertFollowUpPrompt ?? false) {
										// Insert the follow-up prompt into the input box
										setInputText(prompt);
									} else {
										// Submit the follow-up prompt directly
										submitMessage(message?.id, prompt);
									}
								}}
							/>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/key}

<style>
	.buttons::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.buttons {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	@keyframes thumbs-up-shake {
		0%, 100% { transform: rotate(0deg); }
		20% { transform: rotate(-18deg) translateY(-2px); }
		40% { transform: rotate(14deg) translateY(-3px); }
		60% { transform: rotate(-10deg) translateY(-1px); }
		80% { transform: rotate(8deg) translateY(-2px); }
	}

	:global(.thumbs-up-shake) {
		animation: thumbs-up-shake 0.5s ease-in-out;
	}
</style>
