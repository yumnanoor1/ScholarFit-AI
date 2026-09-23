import React from 'react';
import StepItem from './StepItem';

export default function PathwaySteps({ steps = [] }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div style={{ marginTop: '16px' }}>
      {steps.map((step, idx) => (
        <StepItem
          key={idx}
          stepNumber={idx + 1}
          title={step.title}
          description={step.description}
          status={step.status || "pending"}
          isLast={idx === steps.length - 1}
        />
      ))}
    </div>
  );
}