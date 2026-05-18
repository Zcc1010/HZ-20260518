const ensureLeadingSlash = (value: string) => (value.startsWith("/") ? value : `/${value}`);

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

function normalizeBasePath(value: string) {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "/") return "/";
  return `${ensureLeadingSlash(trimTrailingSlash(trimmed))}/`;
}

function inferBasePathFromModuleUrl(moduleUrl: string) {
  try {
    const pathname = new URL(moduleUrl, window.location.href).pathname;
    for (const marker of ["/assets/", "/src/", "/@fs/"]) {
      const markerIndex = pathname.indexOf(marker);
      if (markerIndex >= 0) {
        return normalizeBasePath(pathname.slice(0, markerIndex));
      }
    }
  } catch {
    // Ignore malformed URLs and fall back below.
  }

  return "/";
}

export const appBase: string = inferBasePathFromModuleUrl(import.meta.url);

export const routerBasename = appBase === "/" ? undefined : trimTrailingSlash(appBase);

export function withBasePath(path: string) {
  const normalizedPath = ensureLeadingSlash(path);
  if (appBase === "/") return normalizedPath;
  return `${trimTrailingSlash(appBase)}${normalizedPath}`;
}
