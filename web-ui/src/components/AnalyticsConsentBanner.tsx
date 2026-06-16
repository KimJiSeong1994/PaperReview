import { useState } from 'react';
import {
  getStoredAnalyticsConsentState,
  isGA4Configured,
  setAnalyticsConsent,
  type AnalyticsConsent,
} from '../analytics/ga4';

function readStoredConsent(): AnalyticsConsent | null {
  if (typeof window === 'undefined') return 'denied';
  return getStoredAnalyticsConsentState(window.localStorage);
}

export default function AnalyticsConsentBanner() {
  const [consent, setConsent] = useState<AnalyticsConsent | null>(() => {
    if (!isGA4Configured()) return 'denied';
    return readStoredConsent();
  });

  if (!isGA4Configured() || consent !== null) return null;

  const chooseConsent = (nextConsent: AnalyticsConsent) => {
    setAnalyticsConsent(nextConsent);
    setConsent(nextConsent);
  };

  return (
    <aside
      aria-label="Analytics consent"
      style={{
        position: 'fixed',
        right: '16px',
        bottom: '16px',
        zIndex: 1000,
        maxWidth: '360px',
        padding: '14px',
        borderRadius: '12px',
        border: '1px solid rgba(255,255,255,0.18)',
        background: 'rgba(15, 23, 42, 0.96)',
        color: '#e5e7eb',
        boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
        fontSize: '13px',
        lineHeight: 1.45,
      }}
    >
      <strong style={{ display: 'block', marginBottom: '6px', color: '#fff' }}>
        Privacy-safe analytics
      </strong>
      <span>
        Help us improve Jiphyeonjeon with privacy-safe usage metrics. We do not send search text,
        paper titles, private URLs, tokens, or account identifiers.
      </span>
      <div style={{ display: 'flex', gap: '8px', marginTop: '12px', justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={() => chooseConsent('denied')}
          style={{
            padding: '7px 10px',
            borderRadius: '8px',
            border: '1px solid rgba(255,255,255,0.2)',
            background: 'transparent',
            color: '#e5e7eb',
            cursor: 'pointer',
          }}
        >
          Decline
        </button>
        <button
          type="button"
          onClick={() => chooseConsent('granted')}
          style={{
            padding: '7px 10px',
            borderRadius: '8px',
            border: '1px solid #6366f1',
            background: '#6366f1',
            color: '#fff',
            cursor: 'pointer',
          }}
        >
          Allow analytics
        </button>
      </div>
    </aside>
  );
}
