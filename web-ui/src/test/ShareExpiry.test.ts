import { describe, it, expect } from 'vitest';
import { isShareExpired } from '../components/mypage/ReportViewer';

const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

describe('isShareExpired', () => {
  it('calls a link past its expiry expired', () => {
    expect(isShareExpired({ expires_at: iso(-60_000) })).toBe(true);
  });

  it('leaves a link with time left alone', () => {
    expect(isShareExpired({ expires_at: iso(60_000) })).toBe(false);
  });

  it('treats no share and no expiry as nothing to hide', () => {
    expect(isShareExpired(null)).toBe(false);
    expect(isShareExpired({})).toBe(false);
  });

  it('treats an unparseable date as live, rather than hiding a working link', () => {
    // Guessing "expired" here would strip the URL and Copy from a link that
    // still works — the worse of the two failures.
    expect(isShareExpired({ expires_at: 'not a date' })).toBe(false);
  });

  it('is expired the moment it lapses, not a day later', () => {
    // A whole-day comparison would keep offering a link that died this morning.
    expect(isShareExpired({ expires_at: iso(-1_000) })).toBe(true);
  });
});
