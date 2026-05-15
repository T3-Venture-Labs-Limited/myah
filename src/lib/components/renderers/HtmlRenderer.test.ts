import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import HtmlRenderer from './HtmlRenderer.svelte';

describe('HtmlRenderer', () => {
	it('uses direct iframe src when file_id is provided', () => {
		const { container } = render(HtmlRenderer, {
			props: {
				filename: 'foo.html',
				file_id: 'abc-123',
				editable: false
			}
		});
		const iframe = container.querySelector('iframe');
		expect(iframe?.getAttribute('src')).toContain('/files/abc-123/content');
	});

	it('uses Hermes media proxy when path is provided', () => {
		const { container } = render(HtmlRenderer, {
			props: {
				filename: 'foo.html',
				path: '/tmp/foo.html',
				editable: false
			}
		});
		const iframe = container.querySelector('iframe');
		expect(iframe?.getAttribute('src')).toContain('/hermes/media');
		expect(iframe?.getAttribute('src')).toContain(encodeURIComponent('/tmp/foo.html'));
	});

	it('iframe sandbox excludes allow-same-origin', () => {
		const { container } = render(HtmlRenderer, {
			props: { filename: 'foo.html', file_id: 'abc', editable: false }
		});
		const sandbox = container.querySelector('iframe')?.getAttribute('sandbox') ?? '';
		expect(sandbox).not.toContain('allow-same-origin');
		expect(sandbox).toContain('allow-scripts');
		expect(sandbox).toContain('allow-forms');
		expect(sandbox).toContain('allow-popups');
	});

	it('iframe fills container height (h-full, not 60vh)', () => {
		const { container } = render(HtmlRenderer, {
			props: { filename: 'foo.html', file_id: 'abc', editable: false }
		});
		const iframe = container.querySelector('iframe');
		expect(iframe?.className).toContain('h-full');
		expect(iframe?.getAttribute('style') ?? '').not.toContain('60vh');
	});

	it('renders ArtifactFallback when neither file_id nor path is provided', () => {
		const { container } = render(HtmlRenderer, {
			props: { filename: 'foo.html', editable: false }
		});
		expect(container.querySelector('iframe')).toBeNull();
	});
});
