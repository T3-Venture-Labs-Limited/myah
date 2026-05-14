<script lang="ts">
	// OSS variant has no login screen — the full multi-user signin /
	// signup / OAuth / LDAP page was moved to
	// platform-hosted/src/routes/auth/+page.svelte as part of the Phase 1B
	// anti-SaaS surgical removal (spec §6, plan B.4).
	//
	// Hosted overlay (platform-hosted/Dockerfile:39-42) drops the full
	// version on top of this stub at image-build time, so hosted production
	// still serves the full /auth flow.
	//
	// In OSS, any browser hitting /auth (bookmarked URL, follow-on redirect
	// from a stale link, etc.) is bounced to /. The single anonymous admin
	// user is auto-seeded by the oss_seed_user Alembic migration on first
	// boot (plan B.6), so no login is needed.
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => {
		goto('/');
	});
</script>
