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
      aria-label="사용 통계 수집 동의"
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
        개인정보를 보내지 않는 사용 통계
      </strong>
      <span>
        집현전을 개선하는 데 쓰이는 사용 통계를 수집합니다. 검색어, 논문 제목, 비공개 URL,
        토큰, 계정 식별자는 보내지 않습니다.
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
          동의 안 함
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
          수집 허용
        </button>
      </div>
    </aside>
  );
}
