import React from 'react';
import { DollarSign, MinusCircle, PlusCircle, Calculator } from 'lucide-react';

export default function CostBreakdown({ tuition = 12000, living = 10000, funding = 15000 }) {
  const totalCost = tuition + living;
  const remaining = totalCost - funding;

  return (
    <div className="card">
      <h3 style={{ fontSize: '1rem', color: 'var(--color-dark)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Calculator size={18} color="var(--color-primary)" />
        Financial Feasibility & Cost Breakdown
      </h3>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.9rem' }}>
        {/* Tuition */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <PlusCircle size={16} color="var(--color-text-muted)" /> Estimated Annual Tuition
          </span>
          <strong>${tuition.toLocaleString()}</strong>
        </div>

        {/* Living Cost */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <PlusCircle size={16} color="var(--color-text-muted)" /> Estimated Living Expenses
          </span>
          <strong>${living.toLocaleString()}</strong>
        </div>

        {/* Total Cost Before Funding */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#F1F5F9', padding: '8px 12px', borderRadius: '6px', fontWeight: '600' }}>
          <span>Total Estimated Annual Expense</span>
          <span>${totalCost.toLocaleString()}</span>
        </div>

        {/* Funding Subtraction */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: 'var(--color-success)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <MinusCircle size={16} color="var(--color-success)" /> Matched Scholarship / Funding
          </span>
          <strong>- ${funding.toLocaleString()}</strong>
        </div>

        <hr style={{ borderTop: '1px solid var(--color-border)', margin: '4px 0' }} />

        {/* Remaining Out of Pocket Burden */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '12px',
          borderRadius: '6px',
          backgroundColor: remaining > 0 ? '#FEF2F2' : '#DCFCE7',
          color: remaining > 0 ? 'var(--color-danger)' : 'var(--color-success)',
          fontWeight: 'bold',
          fontSize: '1rem'
        }}>
          <span>Estimated Remaining Burden</span>
          <span>${remaining > 0 ? remaining.toLocaleString() : '0 (Fully Covered)'}</span>
        </div>
      </div>

      <div style={{ marginTop: '14px', fontSize: '0.78rem', color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
        * Note: All cost metrics are estimates based on reported averages and official university tuition guidelines.
      </div>
    </div>
  );
}
