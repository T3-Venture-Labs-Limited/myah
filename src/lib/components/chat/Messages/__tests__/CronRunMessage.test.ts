import { render, screen } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

// ResponseMessage transitively imports @sentry/sveltekit (via sentryFeedback),
// whose build references the `$app` package that does not resolve under the
// jsdom vitest project. Stub the util so mounting the real component works.
vi.mock('$lib/utils/sentryFeedback', () => ({
	openMessageFeedback: vi.fn(),
	openSentryFeedback: vi.fn()
}));

import ResponseMessage from '../ResponseMessage.svelte';

// Propagation-level test: CronRunMessage already renders `linkedProcess?.name`,
// but ResponseMessage — its immediate parent in the
// Chat -> Messages -> Message -> ResponseMessage -> CronRunMessage chain —
// must actually forward `linkedProcess` down. This test renders ResponseMessage
// with a cron-run message plus a linkedProcess and asserts the linked job name
// surfaces instead of the generic "Scheduled task" default.
//
// RED before the fix: ResponseMessage renders `<CronRunMessage {message}
// output={message.output} />` without `linkedProcess`, so the pill reads
// "Scheduled task: Scheduled task".

function renderCronResponse() {
	const message = {
		id: 'cron_abc123_2026-06-03T01-08-00',
		model: 'cron',
		role: 'assistant',
		content: '**Cron run** (2026-06-03T01:08:00+00:00)\n\nUpdated upstream wiki notes',
		timestamp: 0,
		done: true,
		output: null
	};

	return render(ResponseMessage, {
		props: {
			chatId: 'chat-cron',
			history: { messages: { [message.id]: message }, currentId: message.id },
			messageId: message.id,
			message,
			siblings: [message.id],
			selectedModels: ['cron'],
			isLastMessage: true,
			readOnly: true,
			linkedProcess: { id: 'abc123def456', name: 'wiki-hermes-upstream-sync' },
			showPreviousMessage: () => {},
			showNextMessage: () => {},
			updateChat: () => {},
			saveMessage: () => {},
			rateMessage: () => {},
			actionMessage: () => {},
			submitMessage: () => {},
			addMessages: () => {}
		},
		context: new Map([['i18n', writable({ t: (k: string) => k })]])
	});
}

describe('ResponseMessage cron run linkedProcess propagation', () => {
	it('forwards linkedProcess so the linked job name replaces the generic label', () => {
		renderCronResponse();

		expect(screen.getByText(/Scheduled task: wiki-hermes-upstream-sync/)).toBeInTheDocument();
		expect(screen.queryByText(/Scheduled task: Scheduled task/)).not.toBeInTheDocument();
	});
});
