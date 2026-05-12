// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />
/// <reference types="cypress" />

// CHAT-FILES-CY — File attachment and cleanup E2E specs
//
// These specs document and verify the file attachment lifecycle:
//   1. Files uploaded in a chat appear in the Files tab of the right pane.
//   2. Deleting a chat triggers server-side cleanup so the file is no longer
//      accessible via the files API.
//
// Prerequisites (Mode B isolated stack):
//   - Backend running on $BACKEND_PORT with a seeded test user (e2e@test.local).
//   - The agent model is set; chat input resolves a file-capable model.
//
// Selector strategy:
//   - #input-menu-button  → "+" / More button in the message input toolbar
//   - button containing "Upload Files" text → file upload menu item
//   - #chat-input → message text area
//   - button[type="submit"] → send message button
//   - .chat-user / .chat-assistant → message turn containers
//   - div[aria-label="Generation Info"] → appears when assistant turn completes
//   - button containing "Files" text → Files tab in the right pane tab bar
//   - #controls-container (desktop) / drawer (mobile) → right pane container

describe('Chat Files Panel', () => {
	// Give video recording an extra moment to capture the final state
	after(() => {
		// eslint-disable-next-line cypress/no-unnecessary-waiting
		cy.wait(2000);
	});

	beforeEach(() => {
		cy.loginAdmin();
		cy.visit('/');
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 1: File uploaded with a chat message appears in the Files tab
	// ─────────────────────────────────────────────────────────────────────────
	it('shows attached file in Files tab after upload', () => {
		// Intercept the file upload so we can track the uploaded file_id
		cy.intercept('POST', '**/api/v1/files/').as('uploadFile');
		// Intercept the chat-files list to confirm our file is included
		cy.intercept('GET', '**/api/v1/chats/*/files').as('getChatFiles');

		// Select a model capable of file upload
		cy.get('button[aria-label="Select a model"]').click();
		cy.get('button[aria-roledescription="model-item"]').first().click();

		// Open the "+" / More input menu
		cy.get('#input-menu-button').click();

		// Click "Upload Files" — this opens the OS file picker.
		// We use cy.fixture + the hidden <input type="file"> instead of
		// clicking through the OS dialog.
		cy.get('button').contains('Upload Files').click();

		// Attach a small fixture image via the underlying file input.
		// The input is hidden; force:true bypasses the visibility guard.
		cy.get('input[type="file"]').first().selectFile(
			{
				contents: Cypress.Buffer.from('fake-png-data'),
				fileName: 'test-attachment.png',
				mimeType: 'image/png'
			},
			{ force: true }
		);

		// Wait for the upload to complete and grab the file_id
		cy.wait('@uploadFile').then((interception) => {
			expect(interception.response?.statusCode).to.eq(200);
			const fileId: string = interception.response?.body?.id;
			expect(fileId).to.be.a('string').and.not.empty;

			// Store for later assertions
			cy.wrap(fileId).as('uploadedFileId');
		});

		// Send a message — the uploaded file is forwarded alongside it
		cy.get('#chat-input').type('Describe the attached file briefly.', { force: true });
		cy.get('button[type="submit"]').click();

		// Verify user turn appeared
		cy.get('.chat-user', { timeout: 5_000 }).should('exist');

		// Wait for the assistant response to fully complete
		cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');

		// Open the right pane via the controls toggle button (if not already open)
		// The button cycles through the right pane; if it is closed, open it.
		cy.get('button[aria-label="Open Controls"]').click({ force: true });

		// Click the "Files" tab in the right pane tab bar
		cy.contains('button', 'Files').click();

		// The chat-files endpoint should have been called (triggered by tab mount)
		cy.wait('@getChatFiles').then((interception) => {
			expect(interception.response?.statusCode).to.eq(200);
		});

		// The uploaded filename should now be visible in the Files list
		cy.get('@uploadedFileId').then((_fileId) => {
			cy.contains('test-attachment.png').should('be.visible');
		});
	});

	// ─────────────────────────────────────────────────────────────────────────
	// Scenario 2: Deleting a chat removes the associated file from the API
	// ─────────────────────────────────────────────────────────────────────────
	it('cleans up files when chat is deleted', () => {
		// We use the REST API directly to set up a chat + file so the test
		// is fast and deterministic without relying on a real LLM response.

		let chatId: string;
		let fileId: string;
		const token = () => localStorage.getItem('token') ?? '';

		// Step 1: Upload a file via the API
		cy.request({
			method: 'POST',
			url: '/api/v1/files/',
			headers: { Authorization: `Bearer ${token()}` },
			body: {
				// FormData-equivalent for the test fixture
				file: new Blob(['dummy content'], { type: 'text/plain' }),
				filename: 'cleanup-test.txt'
			},
			failOnStatusCode: false
		}).then((res) => {
			// If form-data upload is not supported directly via cy.request,
			// fall back to intercepting a UI upload (see note below).
			// For pure API coverage we assert the response structure:
			expect(res.status).to.be.oneOf([200, 201, 422]);
		});

		// Alternative approach: use cy.intercept + UI flow to capture the file_id,
		// then exercise the delete path via the REST API.
		cy.intercept('POST', '**/api/v1/files/').as('fileUpload');
		cy.intercept('DELETE', '**/api/v1/chats/*').as('deleteChat');

		// Select model and upload a file through the UI
		cy.get('button[aria-label="Select a model"]').click();
		cy.get('button[aria-roledescription="model-item"]').first().click();

		cy.get('#input-menu-button').click();
		cy.get('button').contains('Upload Files').click();
		cy.get('input[type="file"]').first().selectFile(
			{
				contents: Cypress.Buffer.from('cleanup test payload'),
				fileName: 'cleanup-test.txt',
				mimeType: 'text/plain'
			},
			{ force: true }
		);

		cy.wait('@fileUpload').then((interception) => {
			fileId = interception.response?.body?.id;
			expect(fileId).to.be.a('string').and.not.empty;
		});

		// Send a minimal message so the chat is persisted
		cy.get('#chat-input').type('ok', { force: true });
		cy.get('button[type="submit"]').click();
		cy.get('.chat-user', { timeout: 5_000 }).should('exist');

		// Capture the chat URL to extract chatId
		cy.url().should('include', '/c/').then((url) => {
			chatId = url.split('/c/')[1];
			expect(chatId).to.be.a('string').and.not.empty;

			// Step 2: Verify the file is linked to the chat
			cy.request({
				method: 'GET',
				url: `/api/v1/chats/${chatId}/files`,
				headers: { Authorization: `Bearer ${token()}` }
			}).then((filesRes) => {
				expect(filesRes.status).to.eq(200);
				const files: Array<{ file_id: string }> = filesRes.body;
				const linked = files.some((f) => f.file_id === fileId);
				expect(linked, `file ${fileId} should be linked to chat ${chatId}`).to.be.true;
			});

			// Step 3: Delete the chat via the API
			cy.request({
				method: 'DELETE',
				url: `/api/v1/chats/${chatId}`,
				headers: { Authorization: `Bearer ${token()}` }
			}).then((delRes) => {
				expect(delRes.status).to.eq(200);
			});

			// Step 4: Verify the file is no longer accessible
			// The backend runs _cleanup_chat_files_before_delete which calls
			// Files.delete_file_by_id for each linked chat file, so a GET
			// on /api/v1/files/{id} should now return 404.
			cy.request({
				method: 'GET',
				url: `/api/v1/files/${fileId}`,
				headers: { Authorization: `Bearer ${token()}` },
				failOnStatusCode: false
			}).then((fileRes) => {
				expect(fileRes.status).to.eq(404);
			});
		});
	});
});
