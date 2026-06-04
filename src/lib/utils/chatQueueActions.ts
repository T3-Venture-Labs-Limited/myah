export type ChatQueuedMessage = {
	id: string;
	prompt: string;
	files: any[];
};

export function removeQueuedMessage(queue: ChatQueuedMessage[], id: string): ChatQueuedMessage[] {
	return queue.filter((message) => message.id !== id);
}

export function toHermesQueueCommand(prompt: string): string | null {
	const trimmed = prompt.trim();
	if (!trimmed) return null;

	const singleLine = trimmed.replace(/\s+/g, ' ');
	return `/queue ${singleLine}`;
}

export function combineQueuedMessages(queue: ChatQueuedMessage[]): { prompt: string; files: any[] } {
	return {
		prompt: queue
			.map((message) => message.prompt)
			.filter(Boolean)
			.join('\n\n'),
		files: queue.flatMap((message) => message.files ?? [])
	};
}

export function queuedMessageHasFiles(message: ChatQueuedMessage): boolean {
	return (message.files ?? []).length > 0;
}
