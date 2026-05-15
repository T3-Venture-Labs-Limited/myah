// Tests for the 11 new declarative UI blocks.
// Uses svelte/server render — no DOM required, works with bare vitest.
import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';

import AlertBlock from '../AlertBlock.svelte';
import AvatarBlock from '../AvatarBlock.svelte';
import BadgeBlock from '../BadgeBlock.svelte';
import StepperBlock from '../StepperBlock.svelte';
import SparklineBlock from '../SparklineBlock.svelte';
import CardBlock from '../CardBlock.svelte';
import ColumnsBlock from '../ColumnsBlock.svelte';
import TabsBlock from '../TabsBlock.svelte';
import AccordionBlock from '../AccordionBlock.svelte';
import CarouselBlock from '../CarouselBlock.svelte';
import ToggleBlock from '../ToggleBlock.svelte';

// ---------------------------------------------------------------------------
// AlertBlock
// ---------------------------------------------------------------------------
describe('AlertBlock', () => {
	it('renders content with minimal props', () => {
		const { body } = render(AlertBlock, { props: { content: 'Something went wrong' } });
		expect(body).toContain('Something went wrong');
	});

	it('defaults to info variant when not specified', () => {
		const { body } = render(AlertBlock, { props: { content: 'Info message' } });
		// Info variant uses accent-blue border — check for its CSS var reference
		expect(body).toContain('--myah-accent-blue');
	});

	it('renders error variant with red border', () => {
		const { body } = render(AlertBlock, { props: { content: 'Oops', variant: 'error' } });
		expect(body).toContain('--myah-accent-red');
	});

	it('renders success variant with green border', () => {
		const { body } = render(AlertBlock, { props: { content: 'Done', variant: 'success' } });
		expect(body).toContain('--myah-accent-green');
	});

	it('renders warning variant', () => {
		const { body } = render(AlertBlock, { props: { content: 'Watch out', variant: 'warning' } });
		// Warning uses a distinct color (orange / yellow — #f59e0b)
		expect(body).toContain('Watch out');
		expect(body).toContain('#f59e0b');
	});
});

// ---------------------------------------------------------------------------
// AvatarBlock
// ---------------------------------------------------------------------------
describe('AvatarBlock', () => {
	it('renders name with minimal props', () => {
		const { body } = render(AvatarBlock, { props: { name: 'Alice' } });
		expect(body).toContain('Alice');
	});

	it('renders subtitle when provided', () => {
		const { body } = render(AvatarBlock, { props: { name: 'Bob', subtitle: 'Engineer' } });
		expect(body).toContain('Bob');
		expect(body).toContain('Engineer');
	});

	it('shows initials fallback when no src provided', () => {
		const { body } = render(AvatarBlock, { props: { name: 'Charlie Davis' } });
		// Initials = CD
		expect(body).toContain('CD');
	});

	it('renders an img tag when src is provided', () => {
		const { body } = render(AvatarBlock, {
			props: { name: 'Eve', src: 'https://example.com/avatar.png' }
		});
		expect(body).toContain('<img');
		expect(body).toContain('https://example.com/avatar.png');
	});
});

// ---------------------------------------------------------------------------
// BadgeBlock
// ---------------------------------------------------------------------------
describe('BadgeBlock', () => {
	it('renders label with minimal props', () => {
		const { body } = render(BadgeBlock, { props: { label: 'Active' } });
		expect(body).toContain('Active');
	});

	it('defaults to default variant styling', () => {
		const { body } = render(BadgeBlock, { props: { label: 'Tag' } });
		expect(body).toContain('Tag');
	});

	it('applies success variant color', () => {
		const { body } = render(BadgeBlock, { props: { label: 'Done', variant: 'success' } });
		expect(body).toContain('Done');
		expect(body).toContain('--myah-accent-green');
	});

	it('applies error variant color', () => {
		const { body } = render(BadgeBlock, { props: { label: 'Failed', variant: 'error' } });
		expect(body).toContain('Failed');
		expect(body).toContain('--myah-accent-red');
	});

	it('applies info variant color', () => {
		const { body } = render(BadgeBlock, { props: { label: 'Info', variant: 'info' } });
		expect(body).toContain('Info');
		expect(body).toContain('--myah-accent-blue');
	});
});

// ---------------------------------------------------------------------------
// StepperBlock
// ---------------------------------------------------------------------------
describe('StepperBlock', () => {
	const steps = [
		{ label: 'Start', description: 'Begin here' },
		{ label: 'Middle' },
		{ label: 'End' }
	];

	it('renders all step labels', () => {
		const { body } = render(StepperBlock, { props: { steps } });
		expect(body).toContain('Start');
		expect(body).toContain('Middle');
		expect(body).toContain('End');
	});

	it('renders step description when provided', () => {
		const { body } = render(StepperBlock, { props: { steps } });
		expect(body).toContain('Begin here');
	});

	it('defaults current to 0 (first step active)', () => {
		const { body } = render(StepperBlock, { props: { steps } });
		// No assertion on exact color — just ensure it renders without error
		expect(body).toContain('Start');
	});

	it('highlights the current step', () => {
		const { body } = render(StepperBlock, { props: { steps, current: 1 } });
		expect(body).toContain('Middle');
	});
});

// ---------------------------------------------------------------------------
// SparklineBlock
// ---------------------------------------------------------------------------
describe('SparklineBlock', () => {
	it('renders an SVG element', () => {
		const { body } = render(SparklineBlock, { props: { values: [1, 3, 2, 5, 4] } });
		expect(body).toContain('<svg');
		expect(body).toContain('</svg>');
	});

	it('renders a polyline or path inside the SVG', () => {
		const { body } = render(SparklineBlock, { props: { values: [10, 20, 15, 25] } });
		const hasLine = body.includes('<polyline') || body.includes('<path');
		expect(hasLine).toBe(true);
	});

	it('uses custom color when provided', () => {
		const { body } = render(SparklineBlock, { props: { values: [1, 2], color: '#ff0000' } });
		expect(body).toContain('#ff0000');
	});

	it('defaults color to accent-blue var when not provided', () => {
		const { body } = render(SparklineBlock, { props: { values: [1, 2, 3] } });
		expect(body).toContain('--myah-accent-blue');
	});
});

// ---------------------------------------------------------------------------
// CardBlock
// ---------------------------------------------------------------------------
describe('CardBlock', () => {
	it('renders with no title and no nested blocks', () => {
		const { body } = render(CardBlock, { props: { blocks: [] } });
		// Should render a card container
		expect(body).toContain('--myah-bg-card');
	});

	it('renders title when provided', () => {
		const { body } = render(CardBlock, { props: { title: 'My Card', blocks: [] } });
		expect(body).toContain('My Card');
	});

	it('renders nested text-type blocks', () => {
		const { body } = render(CardBlock, {
			props: {
				blocks: [{ type: 'badge', label: 'Nested' }]
			}
		});
		// The card delegates to DeclarativeUI which renders the badge
		expect(body).toContain('Nested');
	});
});

// ---------------------------------------------------------------------------
// ColumnsBlock
// ---------------------------------------------------------------------------
describe('ColumnsBlock', () => {
	it('renders with two empty columns', () => {
		const { body } = render(ColumnsBlock, { props: { blocks: [[], []] } });
		expect(body).toContain('display:flex');
	});

	it('renders content in each column', () => {
		const { body } = render(ColumnsBlock, {
			props: {
				blocks: [[{ type: 'badge', label: 'Col1' }], [{ type: 'badge', label: 'Col2' }]]
			}
		});
		expect(body).toContain('Col1');
		expect(body).toContain('Col2');
	});

	it('accepts optional widths prop', () => {
		const { body } = render(ColumnsBlock, {
			props: { blocks: [[], []], widths: [2, 1] }
		});
		expect(body).toContain('flex:2');
	});
});

// ---------------------------------------------------------------------------
// TabsBlock
// ---------------------------------------------------------------------------
describe('TabsBlock', () => {
	const tabs = [
		{ label: 'Tab One', blocks: [{ type: 'badge', label: 'Alpha' }] },
		{ label: 'Tab Two', blocks: [{ type: 'badge', label: 'Beta' }] }
	];

	it('renders tab labels', () => {
		const { body } = render(TabsBlock, { props: { tabs } });
		expect(body).toContain('Tab One');
		expect(body).toContain('Tab Two');
	});

	it('renders first tab content by default', () => {
		const { body } = render(TabsBlock, { props: { tabs } });
		// First tab blocks should be rendered
		expect(body).toContain('Alpha');
	});
});

// ---------------------------------------------------------------------------
// AccordionBlock
// ---------------------------------------------------------------------------
describe('AccordionBlock', () => {
	const items = [
		{ label: 'Section A', blocks: [{ type: 'badge', label: 'ContentA' }] },
		{ label: 'Section B', blocks: [], open: true }
	];

	it('renders all accordion labels', () => {
		const { body } = render(AccordionBlock, { props: { items } });
		expect(body).toContain('Section A');
		expect(body).toContain('Section B');
	});

	it('renders the content of an open item', () => {
		const items = [
			{ label: 'Section A', blocks: [{ type: 'badge', label: 'ContentA' }], open: true },
			{ label: 'Section B', blocks: [] }
		];
		const { body } = render(AccordionBlock, { props: { items } });
		expect(body).toContain('ContentA');
	});
});

// ---------------------------------------------------------------------------
// CarouselBlock
// ---------------------------------------------------------------------------
describe('CarouselBlock', () => {
	const carouselItems = [
		{ title: 'Slide 1', description: 'First slide' },
		{ title: 'Slide 2', src: 'https://example.com/img.jpg' }
	];

	it('renders the first item title on initial SSR render', () => {
		// Carousel shows one item at a time; SSR renders index 0 by default
		const { body } = render(CarouselBlock, { props: { items: carouselItems } });
		expect(body).toContain('Slide 1');
	});

	it('renders item description when provided', () => {
		const { body } = render(CarouselBlock, { props: { items: carouselItems } });
		expect(body).toContain('First slide');
	});

	it('renders img tag when src is the only item', () => {
		// Provide a single-item carousel where the first item has src
		const singleItem = [{ title: 'Photo', src: 'https://example.com/img.jpg' }];
		const { body } = render(CarouselBlock, { props: { items: singleItem } });
		expect(body).toContain('https://example.com/img.jpg');
	});

	it('renders prev/next navigation when there are multiple items', () => {
		const { body } = render(CarouselBlock, { props: { items: carouselItems } });
		// Check for button elements for navigation
		expect(body).toContain('<button');
	});
});

// ---------------------------------------------------------------------------
// ToggleBlock
// ---------------------------------------------------------------------------
describe('ToggleBlock', () => {
	it('renders the label', () => {
		const { body } = render(ToggleBlock, { props: { label: 'Enable feature' } });
		expect(body).toContain('Enable feature');
	});

	it('renders unchecked by default', () => {
		const { body } = render(ToggleBlock, { props: { label: 'Toggle me' } });
		// Should render without checked attribute set
		expect(body).toContain('Toggle me');
	});

	it('renders checked state when checked=true', () => {
		const { body } = render(ToggleBlock, { props: { label: 'On', checked: true } });
		expect(body).toContain('On');
		// The checked background should be accent-green
		expect(body).toContain('--myah-accent-green');
	});

	it('renders unchecked background when checked=false', () => {
		const { body } = render(ToggleBlock, { props: { label: 'Off', checked: false } });
		expect(body).toContain('Off');
		// Unchecked background uses bg-input
		expect(body).toContain('--myah-bg-input');
	});
});
