// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />
import { adminUser } from '../support/e2e';

// These tests run through the various settings pages, ensuring that the user can interact with them as expected
describe('Settings', () => {
	// Wait for 2 seconds after all tests to fix an issue with Cypress's video recording missing the last few frames
	after(() => {
		// eslint-disable-next-line cypress/no-unnecessary-waiting
		cy.wait(2000);
	});

	beforeEach(() => {
		// Login as the admin user
		cy.loginAdmin();
		// Visit the home page
		cy.visit('/');
		// Click on the user menu
		cy.get('button[aria-label="User Menu"]').click();
		// Click on the settings link
		cy.get('button').contains('Settings').click();
	});

	context('General', () => {
		it('user can open the General modal and hit save', () => {
			cy.get('button').contains('General').click();
			cy.get('button').contains('Save').click();
		});
	});

	context('Interface', () => {
		it('user can open the Interface modal and hit save', () => {
			cy.get('button').contains('Interface').click();
			cy.get('button').contains('Save').click();
		});
	});

	context('Audio', () => {
		it('user can open the Audio modal and hit save', () => {
			cy.get('button').contains('Audio').click();
			cy.get('button').contains('Save').click();
		});
	});

	context('Chats', () => {
		it('user can open the Chats modal', () => {
			cy.get('button').contains('Chats').click();
		});
	});

	context('Agent', () => {
		it('saves Agent model from Agent settings', () => {
			cy.intercept('GET', '**/api/v1/agent/model', { model: 'gpt-4.1-mini' }).as('getAgentModel');
			cy.intercept('PUT', '**/api/v1/agent/model', (req) => {
				expect(req.body).to.deep.equal({ model: 'gpt-4.1' });
				req.reply({ statusCode: 200, body: { model: 'gpt-4.1' } });
			}).as('updateAgentModel');

			cy.intercept('GET', '**/api/v1/agent/soul', {
				content: '# SOUL\n\nDefault soul'
			}).as('getAgentSoul');
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

			cy.get('[role="dialog"]')
				.should('be.visible')
				.within(() => {
					cy.get('[role="tab"][aria-controls="tab-agent"]').click();
				});

			cy.wait('@getAgentModel');
			cy.get('[data-testid="agent-model-input"]').clear();
			cy.get('[data-testid="agent-model-input"]').type('gpt-4.1');
			cy.get('[data-testid="agent-model-save"]').click();

			cy.wait('@updateAgentModel').its('response.statusCode').should('eq', 200);
			cy.get('[data-testid="agent-model-input"]').should('have.value', 'gpt-4.1');
		});

		it('saves Agent SOUL from Agent settings', () => {
			const updatedSoul = '# SOUL\n\n- Keep context\n- Ask precise follow-ups';

			cy.intercept('GET', '**/api/v1/agent/model', { model: 'gpt-4.1-mini' }).as('getAgentModel');
			cy.intercept('GET', '**/api/v1/agent/soul', {
				content: '# SOUL\n\n- Original'
			}).as('getAgentSoul');
			cy.intercept('PUT', '**/api/v1/agent/soul', (req) => {
				expect(req.body).to.deep.equal({ content: updatedSoul });
				req.reply({ statusCode: 200, body: { content: updatedSoul } });
			}).as('updateAgentSoul');

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

			cy.get('[role="dialog"]')
				.should('be.visible')
				.within(() => {
					cy.get('[role="tab"][aria-controls="tab-agent"]').click();
				});

			cy.wait('@getAgentSoul');
			cy.get('[data-testid="agent-soul-textarea"]').clear();
			cy.get('[data-testid="agent-soul-textarea"]').type(updatedSoul, {
				parseSpecialCharSequences: false
			});
			cy.get('[data-testid="agent-soul-save"]').click();

			cy.wait('@updateAgentSoul').its('response.statusCode').should('eq', 200);
			cy.get('[data-testid="agent-soul-textarea"]').should('have.value', updatedSoul);
		});
	});

	context('Account', () => {
		it('user can open the Account modal and hit save', () => {
			cy.get('button').contains('Account').click();
			cy.get('button').contains('Save').click();
		});
	});

	context('About', () => {
		it('user can open the About modal', () => {
			cy.get('button').contains('About').click();
		});
	});

	context('Workspace Visibility', () => {
		it('admin user can see workspace sidebar button', () => {
			cy.get('#sidebar-workspace-button').should('be.visible');
		});

		it('admin user is redirected to workspace models page', () => {
			cy.visit('/workspace');
			cy.url().should('include', '/workspace/models');
		});

		it('admin user can see all workspace tabs including Skills and Memory', () => {
			cy.visit('/workspace');
			cy.get('nav').within(() => {
				cy.contains('a', 'Models').should('be.visible');
				cy.contains('a', 'Knowledge').should('be.visible');
				cy.contains('a', 'Prompts').should('be.visible');
				cy.contains('a', 'Skills').should('be.visible');
				cy.contains('a', 'Tools').should('be.visible');
				cy.contains('a', 'Memory').should('be.visible');
			});
		});

		it('user with only workspace.skills: true can see workspace sidebar button', () => {
			cy.intercept('GET', '**/api/v1/auths/*', {
				statusCode: 200,
				body: {
					user: {
						id: 'user-1',
						name: 'Skills User',
						email: 'skills@example.com',
						role: 'user',
						permissions: {
							workspace: {
								skills: true
							}
						}
					}
				}
			}).as('getUser');
			cy.reload();
			cy.wait('@getUser');
			cy.get('#sidebar-workspace-button').should('be.visible');
		});

		it('user with only features.memories: true can see workspace sidebar button', () => {
			cy.intercept('GET', '**/api/v1/auths/*', {
				statusCode: 200,
				body: {
					user: {
						id: 'user-2',
						name: 'Memories User',
						email: 'memories@example.com',
						role: 'user',
						permissions: {
							features: {
								memories: true
							}
						}
					}
				}
			}).as('getUser');
			cy.reload();
			cy.wait('@getUser');
			cy.get('#sidebar-workspace-button').should('be.visible');
		});
	});
});
