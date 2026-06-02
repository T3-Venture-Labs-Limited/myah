export type ReturnGoto = (url: string) => void | Promise<void>;
export type ReturnAssign = (url: string) => void;

type ReturnNavigation = {
	kind: 'internal';
	url: string;
};

const LOCAL_SKILLS_RETURN_URL = '/agent/skills';

const isMarketplaceReturnUrl = (url: URL) => {
	const hostname = url.hostname.toLowerCase();
	return (
		(hostname === 'myah.dev' || hostname === 'www.myah.dev' || hostname === 'app.myah.dev') &&
		(url.pathname === '/marketplace' || url.pathname.startsWith('/marketplace/'))
	);
};

const browserOrigin = () => {
	if (typeof window !== 'undefined' && window.location?.origin) {
		return window.location.origin;
	}
	return 'http://localhost';
};

export const resolveReturnNavigation = (
	returnUrl: string | null | undefined,
	origin = browserOrigin()
): ReturnNavigation => {
	const target = returnUrl || '/';

	try {
		const url = new URL(target, origin);
		if (isMarketplaceReturnUrl(url)) {
			return { kind: 'internal', url: LOCAL_SKILLS_RETURN_URL };
		}
		if (url.origin === origin) {
			return { kind: 'internal', url: `${url.pathname}${url.search}${url.hash}` };
		}
		return { kind: 'internal', url: '/' };
	} catch {
		return { kind: 'internal', url: '/' };
	}
};

export const navigateToReturnUrl = (
	returnUrl: string | null | undefined,
	goto: ReturnGoto,
	assign: ReturnAssign = (url) => window.location.assign(url),
	origin = browserOrigin()
) => {
	const target = resolveReturnNavigation(returnUrl, origin);
	void assign;
	return goto(target.url);
};
