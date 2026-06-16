import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ANALYTICS_CONSENT_CHANGED_EVENT, trackPageView } from '../analytics/ga4';
import { sanitizeRouteForPageView } from '../analytics/routeSanitizer';

type AnalyticsRouteTrackerProps = {
  origin?: string;
};

export default function AnalyticsRouteTracker({ origin }: AnalyticsRouteTrackerProps) {
  const location = useLocation();
  const lastTrackedPageRef = useRef<string | null>(null);
  const [consentChangeCount, setConsentChangeCount] = useState(0);

  useEffect(() => {
    const handleConsentChange = () => {
      lastTrackedPageRef.current = null;
      setConsentChangeCount((count) => count + 1);
    };

    window.addEventListener(ANALYTICS_CONSENT_CHANGED_EVENT, handleConsentChange);
    return () => window.removeEventListener(ANALYTICS_CONSENT_CHANGED_EVENT, handleConsentChange);
  }, []);

  useEffect(() => {
    const sanitized = sanitizeRouteForPageView(location, origin);
    if (!sanitized) return;

    const routeKey = `${sanitized.page_path}|${sanitized.page_location}`;
    if (lastTrackedPageRef.current === routeKey) return;

    if (trackPageView(sanitized)) {
      lastTrackedPageRef.current = routeKey;
    }
  }, [location, origin, consentChangeCount]);

  return null;
}
