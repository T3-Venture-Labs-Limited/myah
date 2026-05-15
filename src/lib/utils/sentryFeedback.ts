import * as Sentry from '@sentry/sveltekit';

let activeObserver: MutationObserver | null = null;

type FeedbackForm = {
	appendToDom(): void;
	open(): void;
	close(): void;
	removeFromDom?(): void;
};

let activeReportForm: FeedbackForm | null = null;
let activeMessageForm: FeedbackForm | null = null;
let messageFormCleanup: (() => void) | null = null;
let reportFormResizeCleanup: (() => void) | null = null;

const MOBILE_BREAKPOINT = 768;

function setAll(shadowRoot: ShadowRoot, selector: string, styles: Record<string, string>): void {
	shadowRoot.querySelectorAll(selector).forEach((el) => {
		const node = el as HTMLElement;
		Object.keys(styles).forEach((prop) => {
			node.style.setProperty(prop, styles[prop], 'important');
		});
	});
}

function applyLayout(shadowRoot: ShadowRoot): void {
	if (window.innerWidth < MOBILE_BREAKPOINT) {
		applyCenteredLayout(shadowRoot);
		return;
	}
	setAll(shadowRoot, '.dialog__position', {
		inset: 'auto auto 16px 60px',
		width: 'min(520px, calc(100vw - 96px))',
		'max-height': 'calc(100vh - 32px)',
		padding: '0'
	});

	setAll(shadowRoot, '.dialog__content', {
		width: '100%',
		padding: '16px'
	});

	setAll(shadowRoot, 'form', {
		'flex-direction': 'column'
	});

	setAll(shadowRoot, '.form__right', {
		width: '100%'
	});

	setAll(shadowRoot, '.editor__image-container', {
		padding: '8px',
		'min-height': '260px',
		'max-height': 'min(360px, 40vh)'
	});

	setAll(shadowRoot, '.editor__canvas-container canvas', {
		'max-width': '100%',
		width: 'auto',
		height: 'auto',
		'max-height': 'min(340px, 38vh)'
	});
}

function applyCenteredLayout(shadowRoot: ShadowRoot): void {
	setAll(shadowRoot, '.dialog__position', {
		position: 'fixed',
		top: '50%',
		right: 'auto',
		bottom: 'auto',
		left: '50%',
		transform: 'translate(-50%, -50%)',
		width: 'min(480px, calc(100vw - 48px))',
		'max-height': 'min(600px, calc(100vh - 48px))',
		padding: '0',
		'margin-top': '0'
	});

	setAll(shadowRoot, '.dialog__content', {
		width: '100%',
		padding: '20px'
	});

	setAll(shadowRoot, 'form', {
		'flex-direction': 'column'
	});

	setAll(shadowRoot, '.form__right', {
		width: '100%'
	});
}

function startLayoutObserver(): void {
	const host = document.getElementById('sentry-feedback');
	if (!host?.shadowRoot) return;
	const root = host.shadowRoot;

	applyLayout(root);

	activeObserver?.disconnect();
	activeObserver = new MutationObserver(() => applyLayout(root));
	activeObserver.observe(root, {
		childList: true,
		subtree: true,
		attributes: true,
		attributeFilter: ['style', 'class']
	});

	reportFormResizeCleanup?.();
	const resizeHandler = () => {
		const h = document.getElementById('sentry-feedback');
		if (h?.shadowRoot) applyLayout(h.shadowRoot);
	};
	window.addEventListener('resize', resizeHandler);
	reportFormResizeCleanup = () => window.removeEventListener('resize', resizeHandler);
}

function reparentToBody(): void {
	const host = document.getElementById('sentry-feedback');
	if (host && host.parentElement !== document.body) {
		document.body.appendChild(host);
	}
}

function runMessageFormCleanup(): void {
	if (messageFormCleanup) {
		messageFormCleanup();
		messageFormCleanup = null;
	}
	activeMessageForm = null;
}

export async function openSentryFeedback(): Promise<void> {
	const feedback = Sentry.getFeedback();
	if (!feedback) {
		console.warn('[sentry-feedback] integration not available');
		return;
	}

	if (activeReportForm) {
		try {
			activeReportForm.close();
		} catch {}
		try {
			activeReportForm.removeFromDom?.();
		} catch {}
		activeReportForm = null;
		activeObserver?.disconnect();
		activeObserver = null;
		reportFormResizeCleanup?.();
		reportFormResizeCleanup = null;
		return;
	}

	const form = (await feedback.createForm({
		formTitle: 'Report a bug',
		messagePlaceholder: 'What happened? What did you expect?',
		submitButtonLabel: 'Send report',
		successMessageText: 'Thanks — your report is on the way.',
		onFormClose: () => {
			activeReportForm = null;
			activeObserver?.disconnect();
			activeObserver = null;
			reportFormResizeCleanup?.();
			reportFormResizeCleanup = null;
		},
		onSubmitSuccess: (_data: unknown, eventId: string) => {
			console.info('[sentry-feedback] submitted successfully', { eventId });
			activeReportForm = null;
		},
		onSubmitError: (error: Error) => {
			console.error('[sentry-feedback] submission failed', error);
		}
	})) as FeedbackForm;

	activeReportForm = form;
	form.appendToDom();
	reparentToBody();
	form.open();

	requestAnimationFrame(startLayoutObserver);
}

export interface MessageFeedbackContext {
	rating: number;
	chatId: string;
	messageId: string;
	messageContent: string;
	model?: string;
}

export async function openMessageFeedback(context: MessageFeedbackContext): Promise<void> {
	const feedback = Sentry.getFeedback();
	if (!feedback) {
		console.warn('[sentry-feedback] integration not available');
		return;
	}

	runMessageFormCleanup();
	if (activeMessageForm) {
		try {
			activeMessageForm.close();
		} catch {}
		try {
			activeMessageForm.removeFromDom?.();
		} catch {}
		activeMessageForm = null;
	}

	const truncatedContent =
		context.messageContent.length > 500
			? context.messageContent.slice(0, 500) + '...'
			: context.messageContent;

	Sentry.getCurrentScope().setContext('message_feedback', {
		chat_id: context.chatId,
		message_id: context.messageId,
		message_content: truncatedContent,
		model: context.model || 'unknown',
		rating: context.rating
	});

	const clearMessageContext = () => {
		Sentry.getCurrentScope().setContext('message_feedback', null);
	};

	const form = (await feedback.createForm({
		formTitle: 'What went wrong?',
		messagePlaceholder: 'Tell us more about this response...',
		submitButtonLabel: 'Send feedback',
		successMessageText: 'Thanks for your feedback!',
		enableScreenshot: false,
		tags: {
			feedback_type: 'message_rating',
			rating: context.rating.toString(),
			chat_id: context.chatId,
			message_id: context.messageId,
			model: context.model || 'unknown'
		},
		onFormClose: () => {
			clearMessageContext();
			runMessageFormCleanup();
		},
		onSubmitSuccess: (_data: unknown, eventId: string) => {
			console.info('[sentry-feedback] message feedback submitted', { eventId });
			clearMessageContext();
			runMessageFormCleanup();
		},
		onSubmitError: (error: Error) => {
			console.error('[sentry-feedback] message feedback submission failed', error);
		}
	})) as FeedbackForm;

	activeMessageForm = form;
	form.appendToDom();
	reparentToBody();
	form.open();

	requestAnimationFrame(() => {
		const host = document.getElementById('sentry-feedback');
		if (!host?.shadowRoot) return;
		const root = host.shadowRoot;

		applyCenteredLayout(root);

		let applyingNow = false;
		const openingObs = new MutationObserver(() => {
			if (applyingNow) return;
			applyingNow = true;
			applyCenteredLayout(root);
			requestAnimationFrame(() => {
				applyingNow = false;
			});
		});
		openingObs.observe(root, {
			childList: true,
			subtree: true,
			attributes: true,
			attributeFilter: ['style', 'class']
		});
		setTimeout(() => openingObs.disconnect(), 400);

		const resizeHandler = () => {
			const h = document.getElementById('sentry-feedback');
			if (h?.shadowRoot) applyCenteredLayout(h.shadowRoot);
		};
		window.addEventListener('resize', resizeHandler);

		const clickAwayHandler = (e: MouseEvent) => {
			const h = document.getElementById('sentry-feedback');
			if (!h || !h.contains(e.target as Node)) {
				try {
					form.close();
				} catch {}
				cleanup();
			}
		};

		const cleanup = () => {
			window.removeEventListener('resize', resizeHandler);
			document.removeEventListener('click', clickAwayHandler, true);
		};
		messageFormCleanup = cleanup;

		setTimeout(() => {
			document.addEventListener('click', clickAwayHandler, true);
		}, 100);
	});
}
