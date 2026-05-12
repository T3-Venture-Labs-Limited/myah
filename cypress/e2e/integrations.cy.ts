// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />
/// <reference types="cypress" />

// INTEGRATIONS-CY — Smoke tests for the Integrations tab

describe('Integrations tab', () => {
	beforeEach(() => {
		cy.loginAdmin();
	});

	it('shows Integrations tab in agent nav', () => {
		cy.visit('/agent/integrations');
		cy.get('a[href="/agent/integrations"]').should('exist');
	});

	it('loads /agent/integrations without 500 error', () => {
		cy.intercept('GET', '/api/v1/integrations*').as('integrations');
		cy.visit('/agent/integrations');
		cy.wait('@integrations').its('response.statusCode').should('not.equal', 500);
	});

	it('renders the integrations page content', () => {
		cy.visit('/agent/integrations');
		// Page should load (not blank, not error page)
		cy.get('body').should('not.be.empty');
		// Should not show a 500 error
		cy.contains('Internal Server Error').should('not.exist');
	});
});
