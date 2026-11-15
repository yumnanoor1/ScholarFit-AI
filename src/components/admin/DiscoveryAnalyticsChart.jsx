import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import './DiscoveryAnalyticsChart.css';

const STAGES = [
  {
    key: 'found',
    label: 'Candidates found',
    countKey: 'candidatesFound',
    color: '#3974d8',
    description: 'Candidates discovered by this run. This count can overlap the other measures.',
  },
  {
    key: 'accepted',
    label: 'Passed extraction checks',
    countKey: 'candidatesAccepted',
    color: '#32a36a',
    description: 'Candidates accepted by extraction validation; this is not a student-specific eligibility decision.',
  },
  {
    key: 'rejected',
    label: 'Rejected by checks',
    countKey: 'candidatesRejected',
    color: '#df6464',
    description: 'Candidates rejected by the automatic extraction checks for this run.',
  },
  {
    key: 'review',
    label: 'Awaiting review',
    countKey: 'awaitingReview',
    color: '#e69a36',
    description: 'Candidates currently pending in the review queue across all runs.',
  },
];

const formatCount = (value) => (
  typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—'
);

function StageTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const stage = payload[0]?.payload;
  if (!stage) return null;

  return (
    <div className="admin-discovery-chart-tooltip">
      <strong>{stage.label}</strong>
      <span>{formatCount(stage.count)} candidates</span>
      <p>{stage.description}</p>
    </div>
  );
}

function LoadingChart() {
  return (
    <div className="admin-discovery-chart-loading" role="status" aria-label="Loading discovery analytics">
      {STAGES.map((stage) => (
        <div className="admin-discovery-chart-skeleton-row" key={stage.key}>
          <span />
          <i />
        </div>
      ))}
    </div>
  );
}

export default function DiscoveryAnalyticsChart({
  counts,
  hasRun,
  loading = false,
  error = '',
}) {
  if (error) {
    return (
      <p className="admin-discovery-chart-error" role="alert">
        Analytics are unavailable. {error}
      </p>
    );
  }
  if (loading) return <LoadingChart />;
  if (!hasRun) {
    return (
      <p className="admin-discovery-chart-empty" role="status">
        No discovery run has been recorded yet. Run Discovery to see analytics here.
      </p>
    );
  }

  const data = STAGES.map((stage) => {
    const count = counts[stage.countKey];
    return {
      ...stage,
      count,
      countLabel: formatCount(count),
      value: count ?? 0,
    };
  });
  const maxCount = Math.max(1, ...data.map((stage) => stage.value));

  return (
    <div className="admin-discovery-chart">
      <ResponsiveContainer width="100%" height={236} minWidth={0}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 8, right: 56, bottom: 8, left: 0 }}
          barCategoryGap="28%"
        >
          <CartesianGrid horizontal={false} stroke="#edf1f7" />
          <XAxis type="number" domain={[0, maxCount]} hide />
          <YAxis
            type="category"
            dataKey="label"
            width={148}
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#52627a', fontSize: 12 }}
            interval={0}
          />
          <Tooltip
            content={<StageTooltip />}
            cursor={{ fill: 'rgba(57, 116, 216, 0.06)' }}
            wrapperStyle={{ outline: 'none' }}
          />
          <Bar
            dataKey="value"
            background={{ fill: '#f1f4f8', radius: 5 }}
            radius={[0, 6, 6, 0]}
            maxBarSize={24}
            isAnimationActive
            animationDuration={650}
            animationEasing="ease-out"
          >
            {data.map((stage) => <Cell key={stage.key} fill={stage.color} />)}
            <LabelList
              dataKey="countLabel"
              position="right"
              fill="#24344d"
              fontSize={12}
              fontWeight={600}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="admin-discovery-chart-note">
        Bars compare independent backend counts, not sequential funnel stages. The review queue includes candidates from earlier runs.
      </p>
    </div>
  );
}
