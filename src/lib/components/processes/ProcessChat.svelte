<script lang="ts">
	import { onMount, onDestroy, tick, getContext } from 'svelte';
	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';
	import { fade } from 'svelte/transition';

	import { socket, user, models } from '$lib/stores';
	import { createNewChat, getChatById, updateChatById, getChatList } from '$lib/apis/chats';
	import { MYAH_BASE_URL, MYAH_API_BASE_URL } from '$lib/constants';
	import { createOpenAITextStream } from '$lib/apis/streaming';
	import type { Process, ProcessRun } from '$lib/apis/processes';

	const i18n = getContext('i18n');

	export let process: Process;
	export let latestRun: ProcessRun | null = null;
	export let runCount = 0;

	type Message = {
		id: string;
		role: 'user' | 'assistant' | 'system';
		content: string;
		streaming?: boolean;
		local?: boolean;
	};

	let chatId: string | null = null;
	let messages: Message[] = [];
	let input = '';
	let isGenerating = false;
	let loadingChat = true;
	let messagesEl: HTMLElement;
	let inputEl: HTMLTextAreaElement;
	let abortController: AbortController | null = null;

	const suggestionChips = ['Summarize recent runs', "What's the success rate?", 'Any issues?'];

	$: welcomeMessage =
		messages.length === 0 && latestRun
			? {
					id: '__welcome__',
					role: 'assistant' as const,
					content: buildWelcomeMessage(),
					local: true
				}
			: null;

	function buildWelcomeMessage(): string {
		if (!latestRun || !process) return '';
		const name = process.name;
		const runs = runCount;
		let timeAgo = '';
		try {
			const diff = Date.now() - new Date(latestRun.ran_at).getTime();
			const mins = Math.floor(diff / 60000);
			if (mins < 1) timeAgo = 'just now';
			else if (mins < 60) timeAgo = `${mins}m ago`;
			else if (mins < 1440) timeAgo = `${Math.floor(mins / 60)}h ago`;
			else timeAgo = `${Math.floor(mins / 1440)}d ago`;
		} catch {
			timeAgo = 'recently';
		}
		const excerpt = (latestRun.response ?? '')
			.replace(/\[PENDING_INPUT:[\s\S]*?\]/g, '')
			.trim()
			.slice(0, 200);
		let msg = `${name} has been running ${runs} time${runs !== 1 ? 's' : ''}. Last run: ${timeAgo}.`;
		if (excerpt)
			msg += `\n\n${excerpt}${(latestRun.response ?? '').replace(/\[PENDING_INPUT:[\s\S]*?\]/g, '').trim().length > 200 ? '…' : ''}`;
		return msg;
	}

	async function loadOrCreateChat() {
		loadingChat = true;
		try {
			const chats = await getChatList(localStorage.token, 1);
			const title = `Process: ${process.name}`;
			const existing = (chats || []).find((c: { title: string; id: string }) => c.title === title);

			if (existing) {
				chatId = existing.id;
				const full = await getChatById(localStorage.token, chatId!);
				const savedMessages = full?.chat?.messages ?? [];
				messages = savedMessages
					.map((m: { id: string; role: string; content: string }) => ({
						id: m.id,
						role: m.role as 'user' | 'assistant',
						content: typeof m.content === 'string' ? m.content : ''
					}))
					.filter((m: Message) => m.role === 'user' || m.role === 'assistant');
			} else {
				const systemPrompt = buildSystemPrompt();
				const newChatId = uuidv4();
				const res = await createNewChat(
					localStorage.token,
					{
						id: newChatId,
						title: `Process: ${process.name}`,
						models: ['myah'],
						system: systemPrompt,
						messages: [],
						history: { messages: {}, currentId: null },
						timestamp: Date.now()
					},
					null
				);
				chatId = res?.id ?? newChatId;
				messages = [];
			}
		} catch (err) {
			console.error('Failed to load/create process chat:', err);
		} finally {
			loadingChat = false;
		}
		await scrollToBottom();
	}

	function buildSystemPrompt(): string {
		const schedule =
			typeof process.schedule === 'object' ? process.schedule.display : process.schedule;

		let ctx = `You are Myah, the user's AI agent. The user is asking about their automated process "${process.name}".
Schedule: ${schedule}
Process prompt: ${process.prompt}

You can help the user manage this process:
- Change schedule: "change to every 30 minutes" → tell them to use the ⚙️ settings
- Update prompt: describe what to change
- Pause/resume: acknowledge and confirm
- Review output: summarize recent runs, analyze trends

Be concise and action-oriented. If the user asks you to change the process configuration, acknowledge their request and remind them they can also use the ⚙️ settings panel for precise control.`;

		if (latestRun) {
			ctx += `\n\nLatest run output (${latestRun.ran_at?.slice(0, 16) ?? 'unknown time'}):
${latestRun.response}`;
		}

		return ctx;
	}

	function statusBadge(): { label: string; cls: string } {
		if (process.state === 'running')
			return { label: 'Running', cls: 'bg-blue-500/20 text-blue-400' };
		if (process.has_pending_input)
			return { label: 'Needs input', cls: 'bg-amber-500/20 text-amber-400' };
		if (process.enabled && process.state !== 'paused')
			return { label: 'Active', cls: 'bg-emerald-500/20 text-emerald-400' };
		return { label: 'Paused', cls: 'bg-gray-500/20 text-gray-400' };
	}

	async function sendMessage() {
		if (!input.trim() || isGenerating || !chatId) return;

		const userText = input.trim();
		input = '';
		await tick();
		if (inputEl) inputEl.style.height = 'auto';

		const userMsg: Message = { id: uuidv4(), role: 'user', content: userText };
		const assistantMsgId = uuidv4();
		const assistantMsg: Message = {
			id: assistantMsgId,
			role: 'assistant',
			content: '',
			streaming: true
		};

		messages = [...messages, userMsg, assistantMsg];
		await scrollToBottom();
		isGenerating = true;
		abortController = new AbortController();

		try {
			const systemPrompt = buildSystemPrompt();
			const apiMessages = [
				{ role: 'system', content: systemPrompt },
				...messages
					.filter((m) => m.role === 'user' || (m.role === 'assistant' && !m.streaming && !m.local))
					.slice(-20)
					.map((m) => ({ role: m.role, content: m.content }))
			];

			const response = await fetch(`${MYAH_BASE_URL}/api/chat/completions`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				signal: abortController.signal,
				body: JSON.stringify({
					model: 'myah',
					messages: apiMessages,
					stream: true
				})
			});

			if (!response.ok) throw new Error(`API error ${response.status}`);
			if (!response.body) throw new Error('No response body');

			const stream = await createOpenAITextStream(response.body, true);
			let fullContent = '';

			for await (const chunk of stream) {
				if (chunk.done) break;
				fullContent += chunk.value;

				messages = messages.map((m) =>
					m.id === assistantMsgId ? { ...m, content: fullContent, streaming: true } : m
				);
				await scrollToBottom();
			}

			messages = messages.map((m) =>
				m.id === assistantMsgId ? { ...m, content: fullContent, streaming: false } : m
			);

			await persistChat();
			await scrollToBottom();
		} catch (err) {
			if ((err as Error).name === 'AbortError') {
				messages = messages.map((m) => (m.id === assistantMsgId ? { ...m, streaming: false } : m));
			} else {
				toast.error('Failed to get response');
				console.error(err);
				messages = messages.filter((m) => m.id !== assistantMsgId);
			}
		} finally {
			isGenerating = false;
			abortController = null;
		}
	}

	async function persistChat() {
		if (!chatId) return;
		try {
			const history: Record<string, unknown> = { messages: {}, currentId: null };
			const msgList: unknown[] = [];
			let prevId: string | null = null;

			for (const m of messages.filter((msg) => !msg.streaming && !msg.local)) {
				const node = {
					id: m.id,
					role: m.role,
					content: m.content,
					timestamp: Date.now(),
					parentId: prevId,
					childrenIds: [] as string[]
				};
				(history.messages as Record<string, unknown>)[m.id] = node;
				msgList.push(node);
				history.currentId = m.id;
				prevId = m.id;
			}

			await updateChatById(localStorage.token, chatId, {
				messages: msgList,
				history,
				models: ['myah']
			});
		} catch (err) {
			console.error('Failed to persist chat:', err);
		}
	}

	function stopGeneration() {
		abortController?.abort();
	}

	async function scrollToBottom() {
		await tick();
		if (messagesEl) {
			messagesEl.scrollTop = messagesEl.scrollHeight;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	function autoResize(e: Event) {
		const el = e.target as HTMLTextAreaElement;
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 120) + 'px';
	}

	function applySuggestion(chip: string) {
		input = chip;
		if (inputEl) {
			inputEl.focus();
		}
	}

	function renderSimpleMarkdown(text: string): string {
		return text
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(
				/`([^`]+)`/g,
				'<code class="px-1 py-0.5 rounded bg-gray-800 text-gray-200 text-xs font-mono">$1</code>'
			)
			.replace(
				/\[([^\]]+)\]\(([^)]+)\)/g,
				'<a href="$2" target="_blank" rel="noopener" class="text-blue-400 hover:underline">$1</a>'
			);
	}

	onMount(() => {
		loadOrCreateChat();
	});

	onDestroy(() => {
		abortController?.abort();
	});
</script>

<div class="flex flex-col h-full bg-gray-900">
	<div
		class="flex items-center justify-between px-4 py-3 flex-shrink-0 border-b border-neutral-800"
	>
		<span class="text-xs font-medium text-gray-400">Chat</span>
		{#if process}
			<span class="text-xs font-medium px-2 py-0.5 rounded-full {statusBadge().cls}">
				{statusBadge().label}
			</span>
		{/if}
	</div>

	<div bind:this={messagesEl} class="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
		{#if loadingChat}
			<div class="flex justify-center py-8">
				<div
					class="size-5 border-2 border-gray-700 border-t-transparent rounded-full animate-spin"
				></div>
			</div>
		{:else if messages.length === 0}
			<div class="flex flex-col items-center justify-center py-8 text-center">
				{#if welcomeMessage}
					<div class="flex gap-2 w-full max-w-lg mb-6" in:fade={{ duration: 200 }}>
						<div
							class="flex-shrink-0 mt-0.5 size-6 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-3 text-gray-400"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z"
								/>
							</svg>
						</div>
						<div
							class="flex-1 min-w-0 text-sm text-gray-300 whitespace-pre-wrap break-words leading-relaxed"
						>
							{welcomeMessage.content}
						</div>
					</div>
				{:else}
					<div class="text-xs text-gray-600 mb-4">
						Ask Myah about this process, its output, or what to do next.
					</div>
				{/if}

				<div class="flex flex-wrap justify-center gap-2">
					{#each suggestionChips as chip}
						<button
							class="text-xs text-gray-400 hover:text-gray-200 transition px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 border border-neutral-700"
							on:click={() => applySuggestion(chip)}
						>
							{chip}
						</button>
					{/each}
				</div>
			</div>
		{:else}
			{#each messages as msg (msg.id)}
				{#if msg.role === 'user'}
					<div class="flex justify-end" in:fade={{ duration: 100 }}>
						<div
							class="max-w-[85%] rounded-2xl rounded-tr-sm bg-gray-700 px-3 py-2 text-sm text-gray-100 whitespace-pre-wrap break-words"
						>
							{msg.content}
						</div>
					</div>
				{:else if msg.role === 'assistant'}
					<div class="flex gap-2" in:fade={{ duration: 100 }}>
						<div
							class="flex-shrink-0 mt-0.5 size-6 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-3 text-gray-400"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z"
								/>
							</svg>
						</div>
						<div class="flex-1 min-w-0">
							{#if msg.streaming}
								<div class="text-sm text-gray-200 whitespace-pre-wrap break-words leading-relaxed">
									{msg.content}
									<span class="inline-block w-1.5 h-4 bg-gray-500 animate-pulse ml-0.5 rounded-sm"
									></span>
								</div>
							{:else}
								<div class="text-sm text-gray-200 whitespace-pre-wrap break-words leading-relaxed">
									{@html renderSimpleMarkdown(msg.content)}
								</div>
							{/if}
						</div>
					</div>
				{/if}
			{/each}
		{/if}
	</div>

	<div class="flex-shrink-0 px-4 pb-4 pt-2 border-t border-neutral-800">
		<div class="flex items-end gap-2">
			<textarea
				bind:this={inputEl}
				bind:value={input}
				placeholder="Ask about this process…"
				rows={1}
				class="flex-1 rounded-2xl bg-neutral-800 border border-neutral-700 px-3 py-2.5 text-sm text-gray-100 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-600 transition min-h-[40px] max-h-[120px]"
				disabled={loadingChat}
				on:keydown={handleKeydown}
				on:input={autoResize}
			></textarea>

			{#if isGenerating}
				<button
					class="flex-shrink-0 p-2 rounded-xl bg-red-900/30 text-red-400 hover:bg-red-900/50 transition"
					on:click={stopGeneration}
					title="Stop"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="currentColor"
						viewBox="0 0 24 24"
						class="size-4"
					>
						<path
							d="M5.25 7.5A2.25 2.25 0 0 1 7.5 5.25h9a2.25 2.25 0 0 1 2.25 2.25v9a2.25 2.25 0 0 1-2.25 2.25h-9a2.25 2.25 0 0 1-2.25-2.25v-9Z"
						/>
					</svg>
				</button>
			{:else}
				<button
					class="flex-shrink-0 p-2 rounded-xl bg-gray-100 text-gray-900 hover:bg-white transition disabled:opacity-40"
					disabled={!input.trim() || loadingChat}
					on:click={sendMessage}
					title="Send"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="size-4"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18"
						/>
					</svg>
				</button>
			{/if}
		</div>
	</div>
</div>
