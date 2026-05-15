/// <reference types="cypress" />
// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />

export const adminUser = {
	name: 'Admin User',
	email: 'admin@example.com',
	password: 'password'
};

const login = (email: string, password: string) => {
	return cy.session(
		email,
		() => {
			// Make sure to test against us english to have stable tests,
			// regardless on local language preferences
			localStorage.setItem('locale', 'en-US');
			// Visit auth page
			cy.visit('/auth');
			// Fill out the form
			cy.get('input[autocomplete="email"]').type(email);
			cy.get('input[type="password"]').type(password);
			// Submit the form
			cy.get('button[type="submit"]').click();
			// Wait until the user is redirected to the home page
			cy.get('#chat-search').should('exist');
			// Get the current version to skip the changelog dialog
			if (localStorage.getItem('version') === null) {
				cy.get('button').contains("Okay, Let's Go!").click();
			}
		},
		{
			validate: () => {
				cy.request({
					method: 'GET',
					url: '/api/v1/auths/',
					headers: {
						Authorization: 'Bearer ' + localStorage.getItem('token')
					}
				});
			}
		}
	);
};

const register = (name: string, email: string, password: string) => {
	return cy
		.request({
			method: 'POST',
			url: '/api/v1/auths/signup',
			body: {
				name: name,
				email: email,
				password: password
			},
			failOnStatusCode: false
		})
		.then((response) => {
			expect(response.status).to.be.oneOf([200, 400]);
		});
};

const registerAdmin = () => {
	return register(adminUser.name, adminUser.email, adminUser.password);
};

const loginAdmin = () => {
	return login(adminUser.email, adminUser.password);
};

Cypress.Commands.add('login', (email, password) => login(email, password));
Cypress.Commands.add('register', (name, email, password) => register(name, email, password));
Cypress.Commands.add('registerAdmin', () => registerAdmin());
Cypress.Commands.add('loginAdmin', () => loginAdmin());

before(() => {
	cy.registerAdmin();
});

// Polls /api/v1/agent/config until it returns 200, or times out.
const waitForAgentHealthy = (opts: { timeout?: number } = {}): void => {
	const timeout = opts.timeout ?? 20_000;
	const started = Date.now();
	const attempt = (): void => {
		cy.request({
			method: 'GET',
			url: '/api/v1/agent/config',
			failOnStatusCode: false
		}).then((resp) => {
			if (resp.status === 200) return;
			if (Date.now() - started > timeout) {
				throw new Error(
					`Agent did not become healthy within ${timeout}ms (last status=${resp.status})`
				);
			}
			cy.wait(500);
			attempt();
		});
	};
	attempt();
};

Cypress.Commands.add('waitForAgentHealthy', (opts?: { timeout?: number }) =>
	waitForAgentHealthy(opts)
);
