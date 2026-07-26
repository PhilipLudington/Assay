export interface Page<T> {
  items: T[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface PageRequest {
  limit: number;
  cursor: string | null;
}

export const MAX_LIMIT = 200;
export const DEFAULT_LIMIT = 50;

export function parsePageRequest(query: URLSearchParams): PageRequest {
  const rawLimit = Number(query.get('limit') ?? DEFAULT_LIMIT);
  const limit = Number.isFinite(rawLimit)
    ? Math.min(MAX_LIMIT, Math.max(1, Math.trunc(rawLimit)))
    : DEFAULT_LIMIT;
  return { limit, cursor: query.get('cursor') };
}

export function paginate<T>(all: T[], request: PageRequest, keyOf: (item: T) => string): Page<T> {
  const start = request.cursor === null ? 0 : all.findIndex((item) => keyOf(item) === request.cursor) + 1;
  const slice = all.slice(start, start + request.limit);
  const last = slice[slice.length - 1];
  const hasMore = start + request.limit < all.length;
  return {
    items: slice,
    nextCursor: hasMore && last ? keyOf(last) : null,
    hasMore,
  };
}
