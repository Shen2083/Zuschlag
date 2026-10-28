/**
 * Static demo build (GitHub Pages): `NEXT_PUBLIC_DEMO=1 next build`.
 * The UI is the real app; only the API transport is replaced by an in-browser
 * simulation (src/lib/demo/api.ts). Both values are inlined at build time.
 */
export const DEMO = process.env.NEXT_PUBLIC_DEMO === "1";
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
