import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ArtifactExplorer from './ArtifactExplorer.svelte';

// API shape: ChatFileItem from $lib/apis/chats — { file_id, filename, size, mime_type, created_at }.
vi.mock('$lib/apis/chats', () => ({
	getChatFiles: vi.fn(async () => [
		{
			file_id: 'f1',
			filename: 'foo.py',
			mime_type: 'text/x-python',
			size: 1234,
			created_at: 100
		},
		{
			file_id: 'f2',
			filename: 'bar.xlsx',
			mime_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
			size: 8888,
			created_at: 200
		}
	])
}));

describe('ArtifactExplorer', () => {
	it('renders a row per file from getChatFiles', async () => {
		render(ArtifactExplorer, { props: { chatId: 'chat-123', token: 't' } });
		expect(await screen.findByText('foo.py')).toBeInTheDocument();
		expect(await screen.findByText('bar.xlsx')).toBeInTheDocument();
	});

	it('shows empty state when chat has no files', async () => {
		const { getChatFiles } = await import('$lib/apis/chats');
		(getChatFiles as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
		render(ArtifactExplorer, { props: { chatId: 'chat-empty', token: 't' } });
		expect(await screen.findByText(/No files yet/)).toBeInTheDocument();
	});

	it('shows error state with retry on getChatFiles failure', async () => {
		const { getChatFiles } = await import('$lib/apis/chats');
		(getChatFiles as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'));
		render(ArtifactExplorer, { props: { chatId: 'chat-err', token: 't' } });
		expect(await screen.findByText(/Failed to load files/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
	});
});
