import React from 'react';
import TimelineItem from '../components/timeline/TimelineItem';

export default function Timeline() {
  return (
    <div className="page-container">
      <h1 className="page-title">Application Timeline & Roadmaps</h1>
      <p className="page-subtitle">Chronological milestone schedule for tests, applications, and scholarship deadlines.</p>

      <div className="card">
        <TimelineItem 
          date="OCT 31, 2025" 
          title="DAAD EPOS Application Close" 
          description="Final deadline for scholarship portal submissions including research proposal."
        />
        <TimelineItem 
          date="DEC 15, 2025" 
          title="Canadian University Admission Deadline" 
          description="Deadline for fall graduate admissions at University of Toronto."
        />
        <TimelineItem 
          date="MAY 31, 2026" 
          title="Uni-Assist Document Verification" 
          description="Verification processing window closes for German Master's programs."
        />
      </div>
    </div>
  );
}