/** Only the keys the curriculum page owns; anything else in the query string is carried through. */
export function paramsWithSelection(
  prev: URLSearchParams,
  selection: { course: string | null; module: string | null; paper: string | null },
): URLSearchParams {
  const next = new URLSearchParams(prev);
  for (const [key, value] of Object.entries(selection)) {
    if (value) next.set(key, value);
    else next.delete(key);
  }
  return next;
}
