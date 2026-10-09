import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarDays, CheckCircle2, Circle, GraduationCap, LockKeyhole } from 'lucide-react';
import { ChevronSmallRightIcon } from '../components/ui/ChevronSmallRightIcon';
import { GlowCard } from '../components/ui/spotlight-card';
import { mockApplicationPathways, mockUniversities } from '../data/mockData';

const CHECKLIST_STORAGE_KEY = 'fitscholar.pathwayDocuments.v1';

const documentChecklists = {
  university: {
    title: 'University document checklist',
    items: [
      { id: 'transcript', label: 'Official academic transcript' },
      { id: 'statement', label: 'Statement of purpose' },
      { id: 'recommendations', label: 'Letters of recommendation' },
      { id: 'english-test', label: 'English proficiency certificate (IELTS / TOEFL)' },
    ],
  },
  scholarship: {
    title: 'Scholarship document checklist',
    items: [
      { id: 'offer-letter', label: 'University offer letter' },
      { id: 'scholarship-essay', label: 'Scholarship essay' },
      { id: 'resume', label: 'CV / resume' },
      { id: 'financial-need', label: 'Proof of financial need' },
    ],
  },
};

function readPreparedDocuments() {
  try {
    const stored = window.localStorage.getItem(CHECKLIST_STORAGE_KEY);
    const parsed = stored ? JSON.parse(stored) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export default function ApplicationPathway() {
  const navigate = useNavigate();
  const [preparedDocuments, setPreparedDocuments] = useState(readPreparedDocuments);
  const pathway = mockApplicationPathways.find((item) => item.type === 'University First') || mockApplicationPathways[0];
  const university = mockUniversities.find((item) => item.id === pathway?.universityId);
  const nextStepIndex = pathway?.steps.findIndex((step) => step.status !== 'completed') ?? -1;

  if (!pathway) return null;

  const headline = pathway.type === 'University First'
    ? 'Apply to the university first. Scholarship second.'
    : 'Apply to the university and funding together.';
  const description = pathway.type === 'University First'
    ? 'This route uses an admission offer as the starting point for your funding application.'
    : 'Admission and funding are handled together through one application process.';

  const togglePreparedDocument = (checklist, itemId) => {
    const storageId = `${checklist}:${itemId}`;
    setPreparedDocuments((current) => {
      const next = { ...current, [storageId]: !current[storageId] };
      try {
        window.localStorage.setItem(CHECKLIST_STORAGE_KEY, JSON.stringify(next));
      } catch {
        return next;
      }
      return next;
    });
  };

  return (
    <div className="page-container application-pathway-page">
      <header className="application-pathway-header">
        <div>
          <p className="application-pathway-eyebrow">APPLICATION PATHWAY · 2026–2027</p>
          <h1>{headline}</h1>
          <p className="application-pathway-description">{description}</p>
        </div>
        {university && (
          <button type="button" className="application-pathway-view-button" onClick={() => navigate(`/universities/${university.id}`)}>
            <GraduationCap size={17} aria-hidden="true" /> View program <ChevronSmallRightIcon size={15} aria-hidden="true" />
          </button>
        )}
      </header>

      {university && (
        <div className="application-pathway-program">
          <GraduationCap size={17} aria-hidden="true" />
          <span>{university.program}</span>
          <span aria-hidden="true">·</span>
          <span>{university.university}</span>
          <span aria-hidden="true">·</span>
          <span>{university.country}</span>
        </div>
      )}

      <div className="application-pathway-steps">
        {pathway.steps.map((step, index) => {
          const isComplete = step.status === 'completed';
          const isNext = index === nextStepIndex;
          const StatusIcon = isComplete ? CheckCircle2 : isNext ? Circle : LockKeyhole;
          const statusLabel = isComplete ? 'Completed' : isNext ? 'Next step' : 'Upcoming';

          return (
            <div className="application-pathway-step" key={`${pathway.universityId}-${step.title}`}>
              <div className={`application-pathway-step-number${isComplete ? ' is-complete' : isNext ? ' is-next' : ''}`} aria-hidden="true">
                {isComplete ? <CheckCircle2 size={18} /> : String(index + 1)}
              </div>
              <GlowCard as="section" customSize className={`application-pathway-step-card${isNext ? ' is-next' : ''}`}>
                <div className="application-pathway-step-heading">
                  <div>
                    <p className="application-pathway-step-label">STEP {String(index + 1).padStart(2, '0')}</p>
                    <h2>{step.title}</h2>
                    <p className="application-pathway-step-description">{step.description}</p>
                  </div>
                  <span className={`application-pathway-status${isComplete ? ' is-complete' : isNext ? ' is-next' : ''}`}>
                    <StatusIcon size={14} aria-hidden="true" /> {statusLabel}
                  </span>
                </div>
                {index === 0 && university?.deadline && (
                  <div className="application-pathway-deadline">
                    <CalendarDays size={15} aria-hidden="true" /> Application deadline: {university.deadline}
                  </div>
                )}
                {(index === 0 || index === 2) && (() => {
                  const checklistKey = index === 0 ? 'university' : 'scholarship';
                  const checklist = documentChecklists[checklistKey];
                  const preparedCount = checklist.items.filter((item) => preparedDocuments[`${checklistKey}:${item.id}`]).length;

                  return (
                    <div className="pathway-document-checklist">
                      <div className="pathway-checklist-heading">
                        <h3>{checklist.title}</h3>
                        <span>{preparedCount} of {checklist.items.length} prepared</span>
                      </div>
                      <div className="pathway-checklist-items">
                        {checklist.items.map((item) => {
                          const itemKey = `${checklistKey}:${item.id}`;
                          const isPrepared = Boolean(preparedDocuments[itemKey]);

                          return (
                            <label className={`pathway-checklist-item${isPrepared ? ' is-prepared' : ''}`} key={item.id}>
                              <input
                                type="checkbox"
                                checked={isPrepared}
                                onChange={() => togglePreparedDocument(checklistKey, item.id)}
                              />
                              <span>{item.label}</span>
                              <span className="pathway-checklist-status">{isPrepared ? 'Prepared' : 'To prepare'}</span>
                            </label>
                          );
                        })}
                      </div>
                      <p className="pathway-checklist-note">Typical documents; confirm the exact requirements with the university or scholarship provider.</p>
                    </div>
                  );
                })()}
              </GlowCard>
            </div>
          );
        })}
      </div>
    </div>
  );
}