<script lang="ts">
	import { MYAH_BASE_URL } from '$lib/constants';

	export let className = 'size-8';
	export let src = `${MYAH_BASE_URL}/static/favicon.png`;
</script>

<img
	aria-hidden="true"
	src={src === ''
		? `${MYAH_BASE_URL}/static/favicon.png`
		: src.startsWith(MYAH_BASE_URL) ||
			  src.startsWith('https://www.gravatar.com/avatar/') ||
			  src.startsWith('data:') ||
			  src.startsWith('/')
			? src
			: `${MYAH_BASE_URL}/user.png`}
	class=" {className} object-cover rounded-full"
	alt="profile"
	draggable="false"
/>
