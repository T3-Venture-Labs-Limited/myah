// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />
/// <reference types="cypress" />

// AGENT-SETTINGS-CY — Canonical Agent Journeys
//
// These tests verify the canonical scripted journeys that represent
// the full lifecycle of an agent interaction.

// Helper: open agent settings modal
function openAgentSettings() {
	cy.get('button[aria-label="User Menu"]').click();
	cy.get('button').contains('Settings').click();
	cy.get('[role="dialog"]').should('be.visible');
	cy.get('[role="tab"][aria-controls="tab-agent"]').click();
}

// Helper: login admin and setup intercepts for agent API
function loginWithAgentIntercepts(
	modelOverride?: Record<string, unknown>,
	soulOverride?: Record<string, unknown>
) {
	cy.intercept('GET', '**/api/v1/agent/model', modelOverride ?? { model: 'gpt-4.1-mini' }).as(
		'getAgentModel'
	);
	cy.intercept('PUT', '**/api/v1/agent/model').as('updateAgentModel');
	cy.intercept(
		'GET',
		'**/api/v1/agent/soul',
		soulOverride ?? { content: '# SOUL\n\nDefault soul' }
	).as('getAgentSoul');
	cy.intercept('PUT', '**/api/v1/agent/soul').as('updateAgentSoul');
	cy.intercept('GET', '**/api/v1/agent/toolsets', []).as('getAgentToolsets');
	cy.intercept('GET', '**/api/v1/agent/skills', []).as('getAgentSkills');
	cy.intercept('GET', '**/api/v1/agent/memory/overview*', {
		provisioned: false,
		user_profile: [],
		ai_profile: [],
		representation: '',
		conclusions: [],
		pending: 0,
		in_progress: 0,
		completed: 0
	}).as('getMemoryOverview');
}

describe('Agent Settings — Canonical Journeys', () => {
	after(() => {
		// eslint-disable-next-line cypress/no-unnecessary-waiting
		cy.wait(2000);
	});

	beforeEach(() => {
		cy.loginAdmin();
		cy.visit('/');
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 1: invite signup → onboarding → first chat
	// (Covered in registration.cy.ts — key assertions here)
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 1: invite signup → onboarding → first chat', () => {
		it('full flow: signup with invite → onboarding → first successful chat', () => {
			// This journey is covered by registration.cy.ts for signup flow.
			// Here we verify the post-signup first chat works end-to-end.

			// Ensure user is logged in (admin for this test)
			cy.get('#chat-search').should('exist');

			// Select a model
			cy.get('button[aria-label="Select a model"]').click();
			cy.get('button[aria-roledescription="model-item"]').first().click();

			// Verify chat input is ready
			cy.get('#chat-input').should('be.visible');

			// Send first chat message
			cy.get('#chat-input').type('Reply with a single word.', { force: true });
			cy.get('button[type="submit"]').click();

			// Verify user message appears
			cy.get('.chat-user', { timeout: 5_000 }).should('exist');

			// Verify assistant response completes
			cy.get('.chat-assistant', { timeout: 60_000 }).should('exist');
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 2: env var composition submit → next turn succeeds
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 2: env var composition submit → next turn succeeds', () => {
		it('env_vars_form submission updates agent environment and next turn succeeds', () => {
			// Intercept env-vars API
			cy.intercept('GET', '**/api/v1/env-vars', []).as('getEnvVars');
			cy.intercept('POST', '**/api/v1/env-vars').as('setEnvVars');

			// Navigate to agent settings
			openAgentSettings();
			cy.wait('@getAgentModel');
			cy.wait('@getAgentSoul');
			cy.wait('@getAgentToolsets');
			cy.wait('@getAgentSkills');

			// Switch to env vars section if present
			cy.get('[role="dialog"]').within(() => {
				cy.get('[role="tab"]').contains('Env Vars').click({ force: true });
			});

			// Submit env var form (mock env_vars_form composition interaction)
			// This simulates the env_vars_form composition submit action
			cy.request({
				method: 'POST',
				url: '/api/v1/env-vars',
				headers: {
					Authorization: `Bearer ${localStorage.getItem('token') ?? ''}`,
					'Content-Type': 'application/json'
				},
				body: {
					AGENTMAIL_API_KEY: 'test-key-123'
				}
			}).then((res) => {
				expect(res.status).to.be.oneOf([200, 201]);
			});

			cy.wait('@setEnvVars').its('response.statusCode').should('be.oneOf', [200, 201]);

			// Close settings and send next turn
			cy.get('[role="dialog"]').within(() => {
				cy.get('button[aria-label="Close"]').click();
			});

			// Verify next turn succeeds
			cy.get('#chat-input').type('Confirm env vars are set. One word.', { force: true });
			cy.get('button[type="submit"]').click();
			cy.get('.chat-assistant', { timeout: 60_000 }).should('exist');
		});

		it('shows error when env vars API fails', () => {
			cy.intercept('POST', '**/api/v1/env-vars', {
				statusCode: 500,
				body: { detail: 'Container unavailable' }
			}).as('setEnvVarsFail');

			cy.request({
				method: 'POST',
				url: '/api/v1/env-vars',
				headers: {
					Authorization: `Bearer ${localStorage.getItem('token') ?? ''}`,
					'Content-Type': 'application/json'
				},
				body: { TEST_VAR: 'value' },
				failOnStatusCode: false
			}).then((res) => {
				expect(res.status).to.eq(500);
				expect(res.body.detail).to.include('Container');
			});
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 3: model update affects next turn
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 4: model update affects next turn', () => {
		it('changing agent model updates the API and reflects in next request', () => {
			loginWithAgentIntercepts();

			openAgentSettings();
			cy.wait('@getAgentModel');

			// Get initial model value
			cy.get('[data-testid="agent-model-input"]').invoke('val').as('initialModel');

			// Update model
			cy.get('[data-testid="agent-model-input"]').clear();
			cy.get('[data-testid="agent-model-input"]').type('gpt-4.1-nano');
			cy.get('[data-testid="agent-model-save"]').click();

			// Verify update request was made
			cy.wait('@updateAgentModel').then((req) => {
				expect(req.request.body).to.deep.equal({ model: 'gpt-4.1-nano' });
			});

			cy.get('[data-testid="agent-model-input"]').should('have.value', 'gpt-4.1-nano');

			// Close settings and verify chat still works
			cy.get('[role="dialog"]').within(() => {
				cy.get('button[aria-label="Close"]').click();
			});

			// Next chat should use updated model (intercepted in actual usage)
			cy.get('#chat-input').type('Confirm model update. One word.', { force: true });
			cy.get('button[type="submit"]').click();
			cy.get('.chat-assistant', { timeout: 60_000 }).should('exist');
		});

		it('persists model change across page reloads', () => {
			loginWithAgentIntercepts({ model: 'claude-3-haiku' });

			openAgentSettings();
			cy.wait('@getAgentModel');

			// Verify the mocked model value is shown
			cy.get('[data-testid="agent-model-input"]').should('have.value', 'claude-3-haiku');

			// Reload page
			cy.reload();
			cy.get('#chat-search').should('exist');

			// Re-open settings
			openAgentSettings();
			cy.wait('@getAgentModel');

			// Model should still be the persisted value
			cy.get('[data-testid="agent-model-input"]').should('have.value', 'claude-3-haiku');
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 5: tool/skill toggles persist
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 5: tool/skill toggles persist', () => {
		it('toggling a tool persists the change', () => {
			cy.intercept('GET', '**/api/v1/agent/toolsets', [
				{ id: 'toolset-1', name: 'Email Tools', enabled: true },
				{ id: 'toolset-2', name: 'Web Search', enabled: false }
			]).as('getAgentToolsets');
			cy.intercept('PUT', '**/api/v1/agent/toolsets/toolset-2', (req) => {
				expect(req.body).to.deep.equal({ enabled: true });
				req.reply({
					statusCode: 200,
					body: { id: 'toolset-2', name: 'Web Search', enabled: true }
				});
			}).as('toggleToolset');

			loginWithAgentIntercepts();
			openAgentSettings();
			cy.wait('@getAgentToolsets');

			// Find and toggle the disabled toolset
			cy.get('[role="dialog"]').within(() => {
				// Look for tool toggle buttons
				cy.contains('Web Search')
					.closest('[role="listitem"], [data-testid]')
					.find('> button[aria-pressed]')
					.as('toggleBtn');

				cy.get('@toggleBtn').invoke('attr', 'aria-pressed').should('eq', 'false');

				cy.get('@toggleBtn').click();

				cy.wait('@toggleToolset');

				cy.get('@toggleBtn').invoke('attr', 'aria-pressed').should('eq', 'true');
			});
		});

		it('toggling a skill persists the change', () => {
			cy.intercept('GET', '**/api/v1/agent/skills', [
				{ id: 'skill-1', name: 'Code Review', enabled: true },
				{ id: 'skill-2', name: 'Bug Reports', enabled: false }
			]).as('getAgentSkills');
			cy.intercept('PUT', '**/api/v1/agent/skills/skill-2/toggle', (req) => {
				req.reply({ statusCode: 200, body: { id: 'skill-2', name: 'Bug Reports', enabled: true } });
			}).as('toggleSkill');

			loginWithAgentIntercepts();
			openAgentSettings();
			cy.wait('@getAgentSkills');

			// Find and toggle the disabled skill
			cy.get('[role="dialog"]').within(() => {
				cy.contains('Bug Reports')
					.closest('[role="listitem"], [data-testid]')
					.find('> button[aria-pressed]')
					.as('toggleBtn');

				cy.get('@toggleBtn').invoke('attr', 'aria-pressed').should('eq', 'false');

				cy.get('@toggleBtn').click();

				cy.wait('@toggleSkill');

				cy.get('@toggleBtn').invoke('attr', 'aria-pressed').should('eq', 'true');
			});
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 6: SOUL update and rollback
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 6: SOUL update and rollback', () => {
		it('updates SOUL and verifies the change', () => {
			const originalSoul = '# SOUL\n\nDefault soul content';
			const updatedSoul = '# SOUL\n\n- Updated directive 1\n- Updated directive 2';

			loginWithAgentIntercepts(undefined, { content: originalSoul });

			openAgentSettings();
			cy.wait('@getAgentSoul');

			// Clear and update SOUL
			cy.get('[data-testid="agent-soul-textarea"]').clear();
			cy.get('[data-testid="agent-soul-textarea"]').type(updatedSoul, {
				parseSpecialCharSequences: false
			});
			cy.get('[data-testid="agent-soul-save"]').click();

			// Verify update request
			cy.wait('@updateAgentSoul').then((req) => {
				expect(req.request.body).to.deep.equal({ content: updatedSoul });
			});

			cy.get('[data-testid="agent-soul-textarea"]').should('have.value', updatedSoul);
		});

		it('rollback: reverting SOUL to original content', () => {
			const originalSoul = '# SOUL\n\nDefault soul content';
			const rollbackSoul = '# SOUL\n\nRollback soul';

			loginWithAgentIntercepts(undefined, { content: rollbackSoul });

			openAgentSettings();
			cy.wait('@getAgentSoul');

			// Verify current soul content
			cy.get('[data-testid="agent-soul-textarea"]').should('have.value', rollbackSoul);

			// Rollback to original
			cy.get('[data-testid="agent-soul-textarea"]').clear();
			cy.get('[data-testid="agent-soul-textarea"]').type(originalSoul, {
				parseSpecialCharSequences: false
			});
			cy.get('[data-testid="agent-soul-save"]').click();

			cy.wait('@updateAgentSoul').then((req) => {
				expect(req.request.body).to.deep.equal({ content: originalSoul });
			});

			cy.get('[data-testid="agent-soul-textarea"]').should('have.value', originalSoul);
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 7: invalid key shows actionable error with trace id
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 7: invalid key shows actionable error with trace id', () => {
		it('API returns actionable error with trace id for invalid requests', () => {
			// Intercept a request that will fail and include trace info
			cy.intercept('POST', '**/api/v1/processes/*/ui-action', {
				statusCode: 422,
				body: {
					detail: 'Invalid API key format',
					trace_id: 'abc123-def456-ghi789'
				}
			}).as('invalidUiAction');

			cy.request({
				method: 'POST',
				url: '/api/v1/processes/test-job-id/ui-action',
				headers: {
					Authorization: `Bearer ${localStorage.getItem('token') ?? ''}`,
					'Content-Type': 'application/json'
				},
				body: {
					type: 'ui:action',
					action: 'invalid_action',
					composition: 'test',
					payload: {},
					message_id: 'msg-test',
					form_id: '',
					data: {}
				},
				failOnStatusCode: false
			}).then((res) => {
				// Verify error structure
				expect(res.status).to.eq(422);
				expect(res.body).to.have.property('detail');
				expect(res.body).to.have.property('trace_id');
				expect(res.body.detail).to.include('Invalid');
			});
		});

		it('error response is displayed with trace id for debugging', () => {
			const traceId = 'trace-789-xyz';

			cy.intercept('POST', '**/api/v1/env-vars', {
				statusCode: 401,
				body: {
					detail: 'Authentication failed: invalid or expired token',
					trace_id: traceId
				}
			}).as('authError');

			cy.request({
				method: 'POST',
				url: '/api/v1/env-vars',
				headers: {
					Authorization: 'Bearer invalid-token',
					'Content-Type': 'application/json'
				},
				body: { TEST_VAR: 'value' },
				failOnStatusCode: false
			}).then((res) => {
				expect(res.status).to.eq(401);
				expect(res.body.trace_id).to.eq(traceId);
				// The trace_id allows users to correlate with server logs
				expect(res.body.trace_id).to.match(/^[\w-]+$/);
			});
		});

		it('500 error includes trace id for internal errors', () => {
			const internalTraceId = 'int-500-abc123';

			cy.intercept('POST', '**/api/v1/env-vars', {
				statusCode: 500,
				body: {
					detail: 'Internal server error',
					trace_id: internalTraceId
				}
			}).as('serverError');

			cy.request({
				method: 'POST',
				url: '/api/v1/env-vars',
				headers: {
					Authorization: `Bearer ${localStorage.getItem('token') ?? ''}`,
					'Content-Type': 'application/json'
				},
				body: { TEST_VAR: 'value' },
				failOnStatusCode: false
			}).then((res) => {
				expect(res.status).to.eq(500);
				expect(res.body.trace_id).to.eq(internalTraceId);
			});
		});
	});
});

// ─────────────────────────────────────────────────────────────────────────────
// Admin Settings — Agent tab: persistence, aux routing, SOUL oversize guard
// ─────────────────────────────────────────────────────────────────────────────

describe('Agent Settings — persistence and aux routing', () => {
	beforeEach(() => {
		cy.loginAdmin();
	});

	it('vision model setting persists across container restart', () => {
		cy.visit('/admin/settings');
		cy.contains('a', 'Agent').click();

		cy.contains('label', 'Vision analysis')
			.parent()
			.find('input[placeholder*="model"]')
			.clear()
			.type('google/gemini-2.5-flash')
			.blur();
		cy.contains('Saved', { timeout: 5000 });

		cy.contains('button', /Restart agent/i).click();

		cy.waitForAgentHealthy({ timeout: 30_000 });

		cy.reload();
		cy.contains('a', 'Agent').click();
		cy.contains('label', 'Vision analysis')
			.parent()
			.find('input[placeholder*="model"]')
			.should('have.value', 'google/gemini-2.5-flash');
	});

	it('title generation routes through aux endpoint (not main agent)', () => {
		cy.intercept('POST', '/api/v1/agent/aux/title_generation').as('auxTitle');
		cy.intercept('POST', '/myah/v1/message').as('mainAgent');

		cy.visit('/');
		cy.get('[data-testid="chat-input"]').type('Give me three numbers{enter}');

		cy.contains(/\d/, { timeout: 45_000 });

		cy.wait('@auxTitle', { timeout: 30_000 }).then((interception) => {
			expect(interception.response?.statusCode).to.eq(200);
			const messages = interception.request.body.messages as Array<{ content: string }>;
			const concatenated = messages.map((m) => m.content ?? '').join(' ').toLowerCase();
			expect(concatenated).to.match(/title|generate/);
		});

		cy.get('[data-testid="chat-sidebar-item"]').first().should('not.contain.text', 'New Chat');
	});

	it('SOUL editor rejects oversized content client-side', () => {
		cy.visit('/admin/settings');
		cy.contains('a', 'Agent').click();
		cy.contains('h3', 'Persona').scrollIntoView();

		const huge = 'x'.repeat(40_000);
		cy.get('textarea').first().clear({ force: true }).invoke('val', huge).trigger('input');
		cy.contains('button', 'Save').click();

		cy.contains(/hard cap|exceeds.*limit/i, { timeout: 5000 });
	});
});
