import { Link } from 'react-router-dom';
import { fetchSampleConversations } from '../api/client';
import type { SampleSummary } from '../types';
import { fmt, useBlock } from './adminShared';
import { AdminSection, AdminTable, AdminTabHeader, BlockBody } from './AdminUi';

const fetchSamples = (_days: number, signal: AbortSignal) => fetchSampleConversations(signal).then((data) => ({ data }));

function Samples({ samples }: { samples: SampleSummary[] }) {
  if (samples.length === 0) return <div className="admin-empty">공개 샘플이 없습니다.</div>;
  return (
    <AdminTable label="샘플 대화 표" headings={['slug', '제목', '기준일', '턴']}>
      {samples.map((sample) => (
        <tr key={sample.slug}>
          <th scope="row"><Link to={`/samples/${sample.slug}`}><code>{sample.slug}</code></Link></th>
          <td className="admin-cell-title">{sample.title}</td>
          <td>{sample.asof}</td>
          <td>{fmt(sample.turn_count)}</td>
        </tr>
      ))}
    </AdminTable>
  );
}

/** Public conversations available for readers to try. */
export default function AdminContentTab() {
  const samples = useBlock(fetchSamples, 7);
  return (
    <article className="admin-dashboard visits-report admin-tabview" aria-labelledby="admin-content-title">
      <AdminTabHeader id="admin-content-title" title="콘텐츠" range="누적 기준" />
      <AdminSection title="샘플 대화" aside={samples.data ? `${fmt(samples.data.length)}개 공개` : undefined}>
        <BlockBody block={samples} label="샘플 목록">{(list) => <Samples samples={list} />}</BlockBody>
      </AdminSection>
    </article>
  );
}
