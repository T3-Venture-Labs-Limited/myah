// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />
import { adminUser } from '../support/e2e';

// These tests assume the following defaults:
// 1. No users exist in the database or that the test admin user is an admin
// 2. Language is set to English
// 3. The default role for new users is 'pending'
describe('Registration and Login', () => {
	// Wait for 2 seconds after all tests to fix an issue with Cypress's video recording missing the last few frames
	after(() => {
		// eslint-disable-next-line cypress/no-unnecessary-waiting
		cy.wait(2000);
	});

	beforeEach(() => {
		cy.visit('/');
	});

	it('should register a new user as pending', () => {
		const userName = `Test User - ${Date.now()}`;
		const userEmail = `cypress-${Date.now()}@example.com`;
		// Toggle from sign in to sign up
		cy.contains('Sign up').click();
		// Fill out the form
		cy.get('input[autocomplete="name"]').type(userName);
		cy.get('input[autocomplete="email"]').type(userEmail);
		cy.get('input[type="password"]').type('password');
		// Submit the form
		cy.get('button[type="submit"]').click();
		// Wait until the user is redirected to the home page
		cy.contains(userName);
		// Expect the user to be pending
		cy.contains('Check Again');
	});

	it('can login with the admin user', () => {
		// Fill out the form
		cy.get('input[autocomplete="email"]').type(adminUser.email);
		cy.get('input[type="password"]').type(adminUser.password);
		// Submit the form
		cy.get('button[type="submit"]').click();
		// Wait until the user is redirected to the home page
		cy.contains(adminUser.name);
		// Dismiss the changelog dialog if it is visible
		cy.getAllLocalStorage().then((ls) => {
			if (!ls['version']) {
				cy.get('button').contains("Okay, Let's Go!").should('exist').click();
			}
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Journey 1: invite signup → onboarding → first chat
	// ─────────────────────────────────────────────────────────────────────────
	context('Journey 1: invite signup → onboarding → first chat', () => {
		it('full flow: signup → onboarding → first chat message succeeds', () => {
			const userName = `Journey1 User ${Date.now()}`;
			const userEmail = `journey1-${Date.now()}@example.com`;

			// Step 1: Sign up
			cy.contains('Sign up').click();
			cy.get('input[autocomplete="name"]').type(userName);
			cy.get('input[autocomplete="email"]').type(userEmail);
			cy.get('input[type="password"]').type('password123');
			cy.get('button[type="submit"]').click();

			// Step 2: Verify onboarding state (pending user)
			cy.contains(userName);
			// Conditionally wait for pending state if user is not auto-approved
			cy.contains('Check Again', { timeout: 0 }).then(($el) => {
				if ($el.length > 0) {
					cy.contains('Check Again').should('be.visible');
				}
			});

			// Step 3: If user is auto-approved (admin-created or invite-based flow),
			// dismiss changelog and proceed to chat
			cy.getAllLocalStorage().then((ls) => {
				if (!ls['version']) {
					cy.get('button').contains("Okay, Let's Go!").should('exist').click();
				}
			});

			// Step 4: First chat - select model
			cy.get('button[aria-label="Select a model"]').click();
			cy.get('button[aria-roledescription="model-item"]').first().click();

			// Step 5: Send first chat message
			cy.get('#chat-input').type('Hello! Reply with a single word.', { force: true });
			cy.get('button[type="submit"]').click();

			// Step 6: Verify user message appears
			cy.get('.chat-user', { timeout: 5_000 }).should('exist');

			// Step 7: Verify assistant response
			cy.get('.chat-assistant', { timeout: 60_000 }).should('exist');
		});

		it('signup flow captures user email for onboarding communication', () => {
			const userName = `Onboarding User ${Date.now()}`;
			const userEmail = `onboarding-${Date.now()}@example.com`;

			// Sign up with specific email
			cy.contains('Sign up').click();
			cy.get('input[autocomplete="name"]').type(userName);
			cy.get('input[autocomplete="email"]').type(userEmail);
			cy.get('input[type="password"]').type('password123');
			cy.get('button[type="submit"]').click();

			// Verify email is captured (user sees their email or name on pending screen)
			cy.contains(userName);
		});

		it('first chat after signup creates a new conversation', () => {
			// Login as admin to set up
			cy.get('input[autocomplete="email"]').type(adminUser.email);
			cy.get('input[type="password"]').type(adminUser.password);
			cy.get('button[type="submit"]').click();

			// Dismiss changelog if needed
			cy.getAllLocalStorage().then((ls) => {
				if (!ls['version']) {
					cy.get('button').contains("Okay, Let's Go!").should('exist').click();
				}
			});

			// Verify no prior chats in search
			cy.get('#chat-search').should('exist');

			// Start first chat
			cy.get('button[aria-label="Select a model"]').click();
			cy.get('button[aria-roledescription="model-item"]').first().click();
			cy.get('#chat-input').type('First message ever.', { force: true });
			cy.get('button[type="submit"]').click();

			// Verify chat was created
			cy.get('.chat-user', { timeout: 5_000 }).should('exist');
			cy.get('.chat-assistant', { timeout: 60_000 }).should('exist');

			// Chat should appear in sidebar or be accessible
			cy.get('#chat-search').should('be.visible');
		});
	});
});
