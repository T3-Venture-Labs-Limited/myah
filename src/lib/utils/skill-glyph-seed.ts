// Deterministic visual DNA for each skill — drives the generative glyph
// on skill cards and detail heroes. Same slug always produces the same
// glyph index (0–5) and rotation angle (0–359).
//
// Ported from the design canvas (shared.jsx skillSeed) — the hashing
// algorithm is identical so both produce the same output for a given slug.

export interface SkillSeed {
	glyph: number; // 0–5, selects one of six monochrome shapes
	angle: number; // 0–359, rotation in degrees
}

export function skillSeed(slug: string): SkillSeed {
	let h1 = 0;
	let h2 = 0;
	for (let i = 0; i < slug.length; i++) {
		h1 = ((h1 * 31 + slug.charCodeAt(i)) >>> 0);
		h2 = ((h2 * 17 + slug.charCodeAt(i) * 7) >>> 0);
	}
	return {
		glyph: h1 % 6,
		angle: h2 % 360
	};
}