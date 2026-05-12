// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />
/// <reference types="cypress" />

// ARTIFACT-PANE-CY — Phase 1 of artifact-pane-redesign.
//
// Replaces the deleted artifact-viewer.cy.ts (which depended on the removed
// __myahArtifactFired flag and the auto-open-on-hermes:artifact behavior).
//
// Verifies the inverse of the old behavior:
//   1. The artifact pane stays closed by default — no auto-open on hermes:artifact.
//   2. Clicking the Files button (data-testid="chat-files-button") opens the
//      pane into the explorer view.
//
// Full agent-loop coverage (sending a message, watching the agent write a file,
// then opening it in a tab) is provided by the agent-browser based phase
// milestone E2E, not by Cypress. The Cypress harness here doesn't run the
// per-user agent container, so we restrict assertions to UI-only state.

describe('Artifact pane (Phase 1)', () => {
	beforeEach(() => {
		cy.loginAdmin();
		cy.visit('/');
	});

	it('artifact pane is closed by default — no auto-open', () => {
		// The pane should not exist on a fresh chat page. No agent message,
		// no hermes:artifact event, no user click on the Files button.
		cy.get('[data-testid="artifact-pane"]').should('not.exist');
	});

	it('Files button opens the artifact pane into explorer view', () => {
		// Pane closed initially.
		cy.get('[data-testid="artifact-pane"]').should('not.exist');

		// Click the Files button in the navbar.
		cy.get('[data-testid="chat-files-button"]').click();

		// Pane is now visible and shows the explorer (default tab).
		cy.get('[data-testid="artifact-pane"]').should('be.visible');
		cy.get('[data-testid="artifact-explorer"]').should('exist');
	});
});
