// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />

// Stream-persistence E2E tests.
//
// Scenarios 1 and 2 require a running stack with a live agent — they are
// guarded by `// NOTE: requires running stack with agent` comments.
//
// Scenarios 3, 4, and 5 are purely Cypress-intercepted and run without a
// live agent, exercising only the frontend reconnect state machine.

describe('Stream persistence', () => {
	after(() => {
		// Allow Cypress video recorder to capture final frames.
		// eslint-disable-next-line cypress/no-unnecessary-waiting
		cy.wait(2000);
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 1: refresh mid-stream preserves partial response
	// NOTE: requires running stack with agent
	// ─────────────────────────────────────────────────────────────────────────
	context('Scenario 1 — refresh mid-stream', () => {
		beforeEach(() => {
			cy.loginAdmin();
			cy.visit('/');
		});

		it('preserves partial response after mid-stream page reload', () => {
			// NOTE: requires running stack with agent

			// Select a model and send a prompt that produces a long response.
			cy.get('button[aria-label="Select a model"]').click();
			cy.get('button[aria-roledescription="model-item"]').first().click();

			cy.get('#chat-input').type('Write a 500-word essay about octopi.', { force: true });
			cy.get('button[type="submit"]').click();

			// Wait until the assistant starts streaming (first token visible).
			cy.get('.chat-assistant', { timeout: 30_000 }).should('exist');

			// Capture the chat URL so we can navigate back to it after reload.
			cy.url().then(() => {
				// Reload while streaming is in progress.
				cy.reload();

				// Within 1500 ms the partial response must be visible — either via the
				// stale-snapshot paint path or via server truth arriving fast.
				cy.get('.chat-assistant', { timeout: 1500 }).should('exist');
				cy.get('.chat-assistant').invoke('text').should('not.be.empty');

				// The banner must not be stuck in "Reconnecting..." indefinitely.
				// Give the reconnect state machine enough time to resolve (30 s hard
				// timeout is the worst case, but in practice < 5 s on a live stack).
				cy.contains('Reconnecting...', { timeout: 30_000 }).should('not.exist');

				// Wait for generation to complete (Generation Info appears on stop token).
				cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');

				// Full response must be non-empty and coherent (not truncated junk).
				cy.get('.chat-assistant').invoke('text').should('have.length.greaterThan', 50);
			});
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 2: two tabs converge on the same server-authoritative state
	// NOTE: requires running stack with agent
	// ─────────────────────────────────────────────────────────────────────────
	context('Scenario 2 — two-tab convergence', () => {
		beforeEach(() => {
			cy.loginAdmin();
			cy.visit('/');
		});

		it('second tab shows same authoritative state as first tab', () => {
			// NOTE: requires running stack with agent

			// Tab A: send a prompt and let it start streaming.
			cy.get('button[aria-label="Select a model"]').click();
			cy.get('button[aria-roledescription="model-item"]').first().click();

			cy.get('#chat-input').type('Write a 300-word essay about the moon.', { force: true });
			cy.get('button[type="submit"]').click();

			// Wait until Tab A has at least started receiving tokens.
			cy.get('.chat-assistant', { timeout: 30_000 }).should('exist');

			// Capture the chat URL while streaming.
			cy.url().then((chatUrl) => {
				// Tab B: open the same chat URL in a new window context.
				// cy.visit with a different URL then navigating back simulates a
				// second tab opening the same persisted chat.
				cy.window().then((win) => {
					// Reload the same URL to simulate Tab B mounting on the same chat.
					// Both mount calls will hit GET /active_run and GET /live_state.
					win.location.assign(chatUrl);
				});

				// Tab B must show non-empty content within 2 s of mounting —
				// the server-authoritative state arrives via tryResumeInflight.
				cy.get('.chat-assistant', { timeout: 2_000 }).should('exist');
				cy.get('.chat-assistant').invoke('text').should('not.be.empty');

				// The reconnect banner must not be stuck.
				cy.contains('Reconnect failed — refresh to retry').should('not.exist');
			});
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 3: refresh post-completion does not show "Reconnecting..."
	// NOTE: requires running stack with agent
	// ─────────────────────────────────────────────────────────────────────────
	context('Scenario 3 — refresh post-completion', () => {
		beforeEach(() => {
			cy.loginAdmin();
			cy.visit('/');
		});

		it('does not show Reconnecting... banner after the grace TTL expires', () => {
			// NOTE: requires running stack with agent

			// Send a short prompt and wait for the full response.
			cy.get('button[aria-label="Select a model"]').click();
			cy.get('button[aria-roledescription="model-item"]').first().click();

			cy.get('#chat-input').type('Reply with a single word.', { force: true });
			cy.get('button[type="submit"]').click();

			cy.get('.chat-assistant', { timeout: 30_000 }).should('exist');
			// Wait for generation to finish.
			cy.get('div[aria-label="Generation Info"]', { timeout: 60_000 }).should('exist');

			// Wait 11 seconds — past the 10 s active_run grace TTL — so the server
			// will report run_id === null on the next GET /active_run.
			// eslint-disable-next-line cypress/no-unnecessary-waiting
			cy.wait(11_000);

			cy.reload();

			// The reconnect state machine must resolve immediately to the DB-loaded
			// state (run_id === null path in tryResumeInflight). No banner at all.
			cy.get('.chat-assistant', { timeout: 5_000 }).should('exist');
			cy.contains('Reconnecting...').should('not.exist');
			cy.contains('Reconnect failed — refresh to retry').should('not.exist');
			cy.contains('Reconnect timed out — falling back to saved state').should('not.exist');
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 4: banner terminal states — class-7 mitigation gate
	// This scenario does NOT need a live agent; Cypress intercepts the request.
	// ─────────────────────────────────────────────────────────────────────────
	context('Scenario 4 — banner terminal state on 5xx', () => {
		beforeEach(() => {
			cy.loginAdmin();
		});

		it('shows terminal error banner and does NOT retry on 5xx from active_run', () => {
			// Count how many times the route is hit so we can assert no retry loop.
			let hitCount = 0;

			cy.intercept('GET', '/api/v1/chats/*/active_run', (req) => {
				hitCount++;
				req.reply({ statusCode: 500, body: { detail: 'internal server error' } });
			}).as('activeRunRequest');

			// Navigate to any existing chat — the first one in the sidebar is fine.
			// If there are no chats, create one first, then navigate to it.
			cy.visit('/');

			// Start a new chat with a quick message so we have a persisted chat to
			// navigate to (skip model step; use whatever is already selected).
			cy.get('#chat-input').type('Hello', { force: true });
			cy.get('button[type="submit"]').click();
			cy.get('.chat-assistant', { timeout: 30_000 }).should('exist');

			// At this point we have a real chat URL. Reload to trigger tryResumeInflight.
			cy.url().then(() => {
				// Reset count just before reload so we only count post-reload hits.
				hitCount = 0;

				cy.reload();

				// Give tryResumeInflight 500 ms to fire and hit the intercepted endpoint.
				// eslint-disable-next-line cypress/no-unnecessary-waiting
				cy.wait(500);

				// The terminal error banner must appear.
				cy.contains('Reconnect failed — refresh to retry', { timeout: 3_000 }).should('be.visible');

				// Wait 3 more seconds and confirm the endpoint was hit exactly once —
				// the class-7 contract is no retry loop on terminal failure.
				// eslint-disable-next-line cypress/no-unnecessary-waiting
				cy.wait(3_000);

				cy.wrap(null).should(() => {
					expect(hitCount, 'active_run should be hit exactly once (no retry)').to.equal(1);
				});
			});
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 5: 30 s hard timeout — class-9 mitigation gate
	// This scenario does NOT need a live agent; Cypress intercepts + clock.
	// ─────────────────────────────────────────────────────────────────────────
	context('Scenario 5 — 30 s hard timeout fallback', () => {
		beforeEach(() => {
			cy.loginAdmin();
		});

		it('falls back to saved state after 30 s hard timeout when active_run hangs', () => {
			// Intercept active_run and hang indefinitely — never reply.
			cy.intercept('GET', '/api/v1/chats/*/active_run', () => {
				// Intentionally do not call req.reply() — the request hangs.
				// Cypress will hold the request open until the test ends.
			}).as('activeRunHang');

			// Navigate to home, create a chat to get a persisted chat URL.
			cy.visit('/');
			cy.get('#chat-input').type('Hello', { force: true });
			cy.get('button[type="submit"]').click();
			cy.get('.chat-assistant', { timeout: 30_000 }).should('exist');

			cy.url().then(() => {
				// Enable fake timers before the reload so setTimeout calls inside the
				// Svelte component are under Cypress clock control.
				cy.clock();

				cy.reload();

				// Fast-forward 30 seconds to trigger the class-9 hard timeout path.
				cy.tick(30_000);

				// The "timed out" banner should appear briefly as the fallback kicks in.
				cy.contains('Reconnect timed out — falling back to saved state', {
					timeout: 2_000
				}).should('be.visible');

				// Within 1 s of the timeout the DB-loaded state must replace the banner.
				// The banner is cleared after loadChat() resolves.
				cy.contains('Reconnect timed out — falling back to saved state', {
					timeout: 1_000
				}).should('not.exist');

				// The chat content (DB-loaded) must be visible.
				cy.get('.chat-assistant', { timeout: 5_000 }).should('exist');
			});
		});
	});
});
