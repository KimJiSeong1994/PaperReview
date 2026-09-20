import { useMemo } from 'react';
import type { HighlightItem } from '../../api/client';

const CATEGORY_GROUPS: { key: string; label: string; color: string; categories: string[] }[] = [
  { key: 'findings', label: '발견', color: '#a5b4fc', categories: ['finding', 'evidence', 'contribution'] },
  { key: 'analysis', label: '분석', color: '#93c5fd', categories: ['methodology', 'insight', 'reproducibility'] },
  { key: 'critique', label: '비판', color: '#fda4af', categories: ['limitation', 'gap', 'assumption'] },
];

interface ConsensusMeterProps {
  highlights: HighlightItem[];
}

export default function ConsensusMeter({ highlights }: ConsensusMeterProps) {
  const stats = useMemo(() => {
    const rated = highlights.filter(h => h.strength_or_weakness);
    if (rated.length === 0) return null;

    let strengthWeight = 0;
    let weaknessWeight = 0;
    let strengthCount = 0;
    let weaknessCount = 0;

    for (const h of rated) {
      const w = (h.confidence_level ?? 3) * (h.significance ?? 3);
      if (h.strength_or_weakness === 'strength') {
        strengthWeight += w;
        strengthCount++;
      } else {
        weaknessWeight += w;
        weaknessCount++;
      }
    }

    const total = strengthWeight + weaknessWeight;
    const ratio = total > 0 ? strengthWeight / total : 0.5;
    const score = Math.round(ratio * 100);

    // Per-group breakdown
    const groups = CATEGORY_GROUPS.map(g => {
      const inGroup = rated.filter(h => h.category && g.categories.includes(h.category));
      const s = inGroup.filter(h => h.strength_or_weakness === 'strength').length;
      const w = inGroup.filter(h => h.strength_or_weakness === 'weakness').length;
      const groupTotal = s + w;
      return {
        ...g,
        strengthCount: s,
        weaknessCount: w,
        total: groupTotal,
        ratio: groupTotal > 0 ? s / groupTotal : 0.5,
      };
    });

    return { strengthCount, weaknessCount, ratio, score, groups };
  }, [highlights]);

  if (!stats) return null;

  return (
    <div className="mypage-consensus-meter">
      <div className="mypage-consensus-header">
        {/* One report's strength-weighted share of its tagged sentences — nothing
            agrees with anything here, so it is not called a consensus. */}
        <span className="mypage-consensus-title">강점/약점 비중</span>
        <span className="mypage-consensus-score">{stats.score}</span>
      </div>

      {/* Main gauge */}
      <div className="mypage-consensus-gauge">
        <div
          className="mypage-consensus-gauge-fill"
          style={{ width: `${stats.ratio * 100}%` }}
        />
      </div>
      <div className="mypage-consensus-labels">
        <span className="mypage-consensus-label-strength">
          강점 {stats.strengthCount}
        </span>
        <span className="mypage-consensus-label-weakness">
          약점 {stats.weaknessCount}
        </span>
      </div>

      {/* Category breakdown */}
      <div className="mypage-consensus-groups">
        {stats.groups.map(g => (
          <div key={g.key} className="mypage-consensus-group">
            <span className="mypage-consensus-group-label">{g.label}</span>
            <div className="mypage-consensus-group-bar">
              {g.total > 0 ? (
                <>
                  <div
                    className="mypage-consensus-group-fill-s"
                    style={{ width: `${g.ratio * 100}%`, background: g.color }}
                  />
                  <div
                    className="mypage-consensus-group-fill-w"
                    style={{ width: `${(1 - g.ratio) * 100}%` }}
                  />
                </>
              ) : (
                <div className="mypage-consensus-group-fill-empty" />
              )}
            </div>
            <span className="mypage-consensus-group-count">
              강 {g.strengthCount} / 약 {g.weaknessCount}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
