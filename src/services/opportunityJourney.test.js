import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildPersonalizedGuidanceActions,
  buildApplicationPathway,
  getOpportunityDocumentChecklist,
  getOpportunityDocumentRequirements,
  getOpportunityTimelineTasks,
} from './opportunityJourney.js';

test('saved scholarship snapshots use original document wording when their list is empty', () => {
  const documents = getOpportunityDocumentRequirements({
    id: 'sch-db-14',
    sourceStatus: 'official-verified',
    requiredDocuments: [],
    requiredDocumentsText: 'CV; Academic transcripts',
  });
  assert.deepEqual(documents, [
    { id: 'cv', name: 'CV', sourceStatus: 'official-verified' },
    { id: 'academic-transcripts', name: 'Academic transcripts', sourceStatus: 'official-verified' },
  ]);
});

test('saved scholarship snapshots keep structured document requirements', () => {
  const documents = getOpportunityDocumentRequirements({
    requiredDocuments: [{ id: 'cv', name: 'CV', sourceStatus: 'unverified' }],
    requiredDocumentsText: 'Legacy wording',
  });
  assert.deepEqual(documents.map(({ name }) => name), ['CV']);
});

test('deadline journey task is unverified when the record has no verification status', () => {
  const tasks = getOpportunityTimelineTasks({}, {
    id: 'program-1',
    kind: 'program',
    program: 'MSc',
    deadline: '2027-01-01',
  });
  assert.equal(tasks.find((task) => task.kind === 'deadline')?.source, 'unverified');
});

test('application pathway uses only recorded provider instructions, documents, links, and deadlines', () => {
  const opportunity = {
    id: 'sch-db-12',
    kind: 'scholarship',
    name: 'Official Scholarship',
    sourceStatus: 'official-verified',
    deadlineDate: '2027-01-02',
    deadlineStatus: 'official-verified',
    applicationPathwayText: 'Submit a separate scholarship application.',
    applicationChannel: 'direct',
    applicationUrl: 'https://example.org/apply',
    applicationUrlStatus: 'official-verified',
    requiredDocuments: [{ id: 'cv', name: 'CV', sourceStatus: 'official-verified' }],
  };
  const pathway = buildApplicationPathway(opportunity, { today: new Date('2027-01-01T00:00:00Z') });
  assert.equal(pathway.opportunityId, opportunity.id);
  assert.equal(pathway.steps.find((step) => step.id === 'provider-instructions').description,
    'Submit a separate scholarship application. Application channel recorded: direct.');
  assert.equal(pathway.steps.find((step) => step.id === 'deadline').dueDate, '2027-01-02');
  assert.equal(pathway.steps.find((step) => step.id === 'submission-route').url, 'https://example.org/apply');
  assert.equal(pathway.documentChecklist[0].status, 'missing');
});

test('pathway flags missing and expired deadlines rather than inventing dates', () => {
  const noDeadline = buildApplicationPathway({
    id: 'program-1',
    kind: 'program',
    program: 'MSc',
  }, { today: new Date('2027-01-01T00:00:00Z') });
  const deadlineStep = noDeadline.steps.find((step) => step.id === 'deadline');
  assert.equal(deadlineStep.dueDate, undefined);
  assert.match(deadlineStep.description, /No application deadline is recorded/);
  assert.equal(deadlineStep.sourceStatus, 'needs-review');

  const expired = buildApplicationPathway({
    id: 'sch-db-13',
    kind: 'scholarship',
    name: 'Expired Scholarship',
    sourceStatus: 'official-verified',
    deadlineDate: '2026-12-31',
    deadlineStatus: 'official-verified',
  }, { today: new Date('2027-01-01T00:00:00Z') });
  const expiredStep = expired.steps.find((step) => step.id === 'deadline');
  assert.match(expiredStep.description, /has passed/);
  assert.equal(expiredStep.sourceStatus, 'expired');
});

test('timeline uses the pathway deadline once and prefers its structured date', () => {
  const opportunity = {
    id: 'sch-db-15',
    kind: 'scholarship',
    name: 'Award',
    deadlineDate: '2027-01-02',
    deadline: 'Legacy wording',
    deadlineStatus: 'unverified',
    requiredDocuments: [],
  };
  const pathway = buildApplicationPathway(opportunity, { today: new Date('2027-01-01T00:00:00Z') });
  const deadlineTasks = getOpportunityTimelineTasks({}, opportunity, pathway)
    .filter((task) => task.kind === 'deadline' || task.id.endsWith(':deadline'));
  assert.equal(deadlineTasks.length, 1);
  assert.equal(deadlineTasks[0].dueDate, '2027-01-02');
});

test('document checklist never marks an unverified requirement missing or metadata available', () => {
  const opportunity = {
    id: 'sch-db-14',
    requiredDocuments: [
      { id: 'transcript', name: 'Transcript', sourceStatus: 'official-verified' },
      { id: 'passport', name: 'Passport', sourceStatus: 'unverified' },
      { id: 'cv', name: 'CV', sourceStatus: 'official-verified' },
    ],
  };
  const checklist = getOpportunityDocumentChecklist(opportunity, {
    transcript: { status: 'awaiting-verification' },
    passport: { status: 'uploaded' },
    cv: { status: 'uploaded' },
  });
  assert.deepEqual(checklist.map(({ status }) => status), ['needs-review', 'needs-review', 'available']);
});

test('personalized actions prioritize eligibility, verified deadlines, documents, then finances', () => {
  const actions = buildPersonalizedGuidanceActions({
    recommendations: [
      { id: 'optional-skills', result_type: 'optional', priority: 'Low', title: 'Add skills' },
      { id: 'missing-english', result_type: 'missing_information', priority: 'High', title: 'Add English result' },
      { id: 'unmet-cgpa', result_type: 'unmet', priority: 'High', title: 'Review CGPA gap' },
      { id: 'optional-budget', result_type: 'optional', priority: 'Low', title: 'Add budget' },
    ],
    opportunities: [{
      kind: 'scholarship',
      id: 8,
      name: 'Verified Award',
      deadline: { status: 'open', date: '2027-01-15', days_left: 4 },
      source_url: 'https://example.org/award',
    }],
  }, {
    opportunity: {
      id: 'program-2',
      kind: 'program',
      program: 'MSc Example',
      requiredDocuments: [{ id: 'transcript', name: 'Transcript', sourceStatus: 'official-verified' }],
    },
    financialResult: {
      status: 'insufficient_data',
      missing_data: ['Living costs'],
      explanation: [],
    },
  });

  assert.deepEqual(actions.map(({ id }) => id), [
    'unmet-cgpa',
    'missing-english',
    'deadline-8',
    'program-deadline-program-2',
    'document-program-2-transcript',
    'financial-feasibility',
    'optional-skills',
  ]);
  assert.equal(actions[2].priority, 'High');
  assert.equal(actions[2].dueDate, '2027-01-15');
  assert.match(actions[4].explanation, /no verified document is available/);
  assert.match(actions[5].explanation, /Living costs/);
});

test('personalized actions do not infer unverified deadlines and flag missing or expired dates', () => {
  const actions = buildPersonalizedGuidanceActions({
    recommendations: [],
    opportunities: [
      { kind: 'scholarship', id: 1, name: 'No Date Award', deadline: null },
      { kind: 'scholarship', id: 2, name: 'Unknown Date Award',
        deadline: { status: 'unknown', date: null } },
      { kind: 'scholarship', id: 3, name: 'Expired Award',
        deadline: { status: 'closed', date: '2026-01-15' } },
      { kind: 'scholarship', id: 4, name: 'Ineligible Award', status: 'not_eligible',
        deadline: { status: 'open', date: '2027-01-15', days_left: 2 } },
    ],
  });

  assert.deepEqual(actions.map(({ id }) => id), ['deadline-verify-2', 'deadline-expired-3']);
  assert.match(actions[0].explanation, /No exact deadline is available/);
  assert.match(actions[1].explanation, /has passed/);
  assert.equal(actions[1].dueDate, null);
});

test('selected pathway data takes precedence over stale opportunity deadlines and documents', () => {
  const opportunity = {
    id: 'program-10',
    kind: 'program',
    program: 'MSc Example',
    deadline: '2027-01-15',
    sourceUrl: 'https://stale.example.edu',
    requiredDocuments: [{ id: 'old', name: 'Old document', sourceStatus: 'official-verified' }],
  };
  const pathway = {
    opportunityId: opportunity.id,
    sourceUrl: 'https://current.example.edu',
    steps: [{
      id: 'deadline',
      title: 'Confirm the application deadline',
      description: 'No application deadline is recorded.',
      sourceStatus: 'needs-review',
    }],
    documentChecklist: [],
  };
  const actions = buildPersonalizedGuidanceActions({ recommendations: [], opportunities: [] }, {
    opportunity,
    pathway,
  });

  const deadlineAction = actions.find(({ kind }) => kind === 'deadline');
  const documentAction = actions.find(({ kind }) => kind === 'document');
  assert.match(deadlineAction.explanation, /No application deadline is recorded/);
  assert.equal(deadlineAction.dueDate, null);
  assert.equal(deadlineAction.sourceUrl, 'https://current.example.edu');
  assert.match(documentAction.explanation, /No provider-specific document list/);
  assert.equal(documentAction.sourceUrl, 'https://current.example.edu');
});

test('a past but unverified program date is not reported as an expired opportunity', () => {
  const opportunity = {
    id: 'program-11',
    kind: 'program',
    program: 'MSc Example',
    deadline: '2020-01-15',
  };
  const actions = buildPersonalizedGuidanceActions({ recommendations: [], opportunities: [] }, {
    opportunity,
    pathway: {
      opportunityId: opportunity.id,
      sourceUrl: null,
      steps: [{
        id: 'deadline',
        title: 'Confirm the application deadline',
        description: 'The recorded deadline was 2020-01-15 and has passed; verify the next cycle.',
        sourceStatus: 'expired',
        dueDate: '2020-01-15',
      }],
      documentChecklist: [],
    },
  });
  const action = actions.find(({ kind }) => kind === 'deadline');
  assert.match(action.title, /Confirm the recorded admission deadline/);
  assert.match(action.explanation, /not confirmed/);
  assert.equal(action.dueDate, null);
});

test('selected program deadlines are routed for official confirmation, never treated as verified dates', () => {
  const actions = buildPersonalizedGuidanceActions({ recommendations: [], opportunities: [] }, {
    opportunity: {
      id: 'program-9',
      kind: 'program',
      program: 'MSc Example',
      deadline: '2027-01-15',
      sourceUrl: 'https://example.edu/admissions',
    },
  });
  const action = actions.find(({ kind }) => kind === 'deadline');
  assert.match(action.title, /Confirm the recorded admission deadline/);
  assert.match(action.explanation, /not confirmed/);
  assert.equal(action.dueDate, null);
  assert.equal(action.sourceUrl, 'https://example.edu/admissions');
});

test('personalized action plan deduplicates recommendations and does not overstate document status', () => {
  const actions = buildPersonalizedGuidanceActions({
    recommendations: [
      { id: 'missing-field', result_type: 'missing_information', priority: 'High', title: 'Add field' },
      { id: 'missing-field', result_type: 'missing_information', priority: 'High', title: 'Duplicate field' },
    ],
    opportunities: [],
  }, {
    opportunity: {
      id: 'sch-db-4',
      kind: 'scholarship',
      name: 'Award',
      requiredDocuments: [
        { id: 'passport', name: 'Passport', sourceStatus: 'unverified' },
        { id: 'transcript', name: 'Transcript', sourceStatus: 'official-verified' },
      ],
    },
    documentRecords: {
      passport: { status: 'uploaded' },
      transcript: { status: 'awaiting-verification' },
    },
  });

  assert.equal(actions.filter(({ id }) => id === 'missing-field').length, 1);
  assert.ok(actions.some(({ title, explanation }) =>
    title === 'Verify whether Passport is required' && /not been verified/.test(explanation)));
  assert.ok(actions.some(({ title, explanation }) =>
    title === 'Review the Transcript record' && /not been verified as available/.test(explanation)));
});
