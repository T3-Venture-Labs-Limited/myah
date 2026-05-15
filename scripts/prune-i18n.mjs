#!/usr/bin/env node
// platform/scripts/prune-i18n.mjs
//
// Prune orphaned i18n keys from all locale translation.json files.
// Keeps only keys that are referenced in platform/src/**/*.{svelte,ts,js}.
//
// Usage (from repo root or platform/):
//   node platform/scripts/prune-i18n.mjs
//   node platform/scripts/prune-i18n.mjs --dry-run   # report only, no writes

import { readFileSync, writeFileSync, globSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const platformRoot = resolve(__dirname, '..');
const srcDir = resolve(platformRoot, 'src');
const localesDir = resolve(platformRoot, 'src/lib/i18n/locales');

const dryRun = process.argv.includes('--dry-run');

// ---------------------------------------------------------------------------
// 1. Collect all i18n keys statically referenced in src/
// ---------------------------------------------------------------------------

// Pattern 1: i18n.t('key') or i18n.t("key") or i18n.t(`key`)
// Captures the string literal argument (static only — no interpolations).
const staticRe = /[.$]i18n\.t\(\s*(['"`])([^'"`\n${}]+?)\1/g;

// Walk all .svelte, .ts, .js files under src/
const sourceFiles = globSync(`${srcDir}/**/*.{svelte,ts,js}`, {
	ignore: [`${srcDir}/**/*.test.ts`, `${srcDir}/**/*.spec.ts`, `${srcDir}/**/*.d.ts`]
});

const usedKeys = new Set();

for (const filePath of sourceFiles) {
	const content = readFileSync(filePath, 'utf-8');
	let m;
	staticRe.lastIndex = 0;
	while ((m = staticRe.exec(content)) !== null) {
		usedKeys.add(m[2]);
	}
}

// ---------------------------------------------------------------------------
// 2. Allowlist: keys used through dynamic variables (cannot be statically
//    detected). These are documented inline in the source with comments like
//    "localisation keys for time_range to be recognized".
// ---------------------------------------------------------------------------
const allowlist = new Set([
	// time_range values (produced by getTimeRange() in apis/chats/index.ts)
	'Today',
	'Yesterday',
	'Previous 7 days',
	'Previous 30 days',
	'January',
	'February',
	'March',
	'April',
	'May',
	'June',
	'July',
	'August',
	'September',
	'October',
	'November',
	'December',

	// user.role values (admin/Users/UserList.svelte)
	'admin',
	'user',
	'pending',

	// message.role (notes/NoteEditor/Chat/Message.svelte)
	'a user',
	'an assistant',
	'assistant',

	// admin settings tab titles (admin/Settings.svelte)
	'General',
	'Connections',
	'Integrations',
	'Interface',
	'Database',

	// shortcut names, categories, tooltips (src/lib/shortcuts.ts + ShortcutItem.svelte)
	'New Chat',
	'New Temporary Chat',
	'Delete Chat',
	'Open Model Selector',
	'Toggle Dictation',
	'Search',
	'Open Settings',
	'Show Shortcuts',
	'Toggle Sidebar',
	'Close Modal',
	'Focus Chat Input',
	'Accept Autocomplete Generation\nJump to Prompt Variable',
	'Prevent File Creation',
	'Navigate Prompt History Up',
	'Attach File From Knowledge',
	'Add Custom Prompt',
	'Talk to Model',
	'Generate Message Pair',
	'Regenerate Response',
	'Copy Last Code Block',
	'Copy Last Response',
	'Stop Generating',
	'Edit Last Message',
	'Chat',
	'Global',
	'Input',
	'Message',
	// shortcut tooltip overrides
	"Only active when the chat input is in focus.",
	"Only active when the chat input is in focus and an LLM is generating a response.",
	"Only active when \"Paste Large Text as File\" setting is toggled on.",
	"Only can be triggered when the chat input is in focus.",

	// SkillEditor ternary: $i18n.t(edit ? 'Save' : 'Save & Create')
	// 'Save' is captured statically; 'Save & Create' is not due to ternary syntax
	'Save & Create',

	// StatusItem dynamic description — documented by comment in StatusItem.svelte
	'Searching "{{searchQuery}}"',

	// formatDate() return keys — used via $i18n.t(formatDate(...)) in UserMessage + NoteEditor/Chat/Message
	// (commented-out hint calls in UserMessage.svelte document these)
	'Today at {{LOCALIZED_TIME}}',
	'Yesterday at {{LOCALIZED_TIME}}',
	'{{LOCALIZED_DATE}} at {{LOCALIZED_TIME}}',

	// TaskFilters option labels (tasks/TaskFilters.svelte)
	'Active',
	'Needs Input',
	'Scheduled',
	'Completed',

	// ChatList emptyMessage prop (common/ChatList.svelte)
	'No chats found.',
	'No results found.',
	'No notes found.',

	// Connection tooltips — backtick-template strings with {{url}} placeholder
	// are skipped by staticRe (template-literal interpolation filter).
	// Used in AddTerminalServerModal / AddToolServerModal / OpenAIConnection /
	// chat Settings/Connection.svelte. Only the latter two survive the cleanup.
	'Myah will make requests to "{{url}}"',
	'Myah will make requests to "{{url}}/chat/completions"',
]);

// Merge allowlist into usedKeys
for (const k of allowlist) {
	usedKeys.add(k);
}

console.log(`Found ${usedKeys.size} keys in use (${usedKeys.size - allowlist.size} static + ${allowlist.size} allowlisted)`);

// ---------------------------------------------------------------------------
// 3. Detect dynamic-key call sites not covered by allowlist (warning only)
// ---------------------------------------------------------------------------
const dynamicRe = /[.$]i18n\.t\(\s*(?!['"`])([^\s(,)]+)/g;
const dynamicFiles = new Set();
for (const filePath of sourceFiles) {
	const content = readFileSync(filePath, 'utf-8');
	dynamicRe.lastIndex = 0;
	if (dynamicRe.test(content)) {
		dynamicFiles.add(filePath.replace(srcDir + '/', '').replace(srcDir + '\\', ''));
	}
}
if (dynamicFiles.size > 0) {
	console.warn('\nDynamic i18n.t(...) calls detected in:');
	for (const f of [...dynamicFiles].sort()) {
		console.warn(`  ${f}`);
	}
	console.warn('Review these files — their keys should be in the allowlist above.\n');
}

// ---------------------------------------------------------------------------
// 4. Prune each locale file
// ---------------------------------------------------------------------------
const localeFiles = globSync(`${localesDir}/*/translation.json`);

let totalBefore = 0;
let totalPruned = 0;

for (const file of localeFiles.sort()) {
	const data = JSON.parse(readFileSync(file, 'utf-8'));
	const before = Object.keys(data).length;
	const pruned = Object.fromEntries(Object.entries(data).filter(([k]) => usedKeys.has(k)));
	const after = Object.keys(pruned).length;
	const removed = before - after;

	totalBefore += before;
	totalPruned += removed;

	const label = file.replace(localesDir + '/', '').replace(localesDir + '\\', '');
	console.log(`${label}: ${before} → ${after} keys (${removed} pruned)`);

	if (!dryRun) {
		writeFileSync(file, JSON.stringify(pruned, null, '\t') + '\n');
	}
}

console.log(`\nTotal: ${totalBefore} → ${totalBefore - totalPruned} keys (${totalPruned} pruned across all locales)`);
if (dryRun) {
	console.log('\nDry-run mode — no files written.');
}
