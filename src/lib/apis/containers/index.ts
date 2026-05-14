import { MYAH_BASE_URL } from '$lib/constants';

export const restartContainer = async (token: string) => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/containers/restart`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
