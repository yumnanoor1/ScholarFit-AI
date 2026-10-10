export const TASK_STATUSES = ['todo', 'in-progress', 'done'];

function getProfileSection(profile, name) {
  const verified = profile.verifiedProfile || profile.profileDraft || profile;
  return verified[name] || profile[name] || {};
}

export function getOpportunityKind(opportunity) {
  if (opportunity.kind) return opportunity.kind;
  if (opportunity.id?.startsWith('sch-')) return 'scholarship';
  return 'program';
}

export function getOpportunityTitle(opportunity) {
  return opportunity.kind === 'scholarship' || opportunity.name
    ? opportunity.name || opportunity.title
    : opportunity.program || opportunity.title;
}

export function getOpportunityOrganization(opportunity) {
  return opportunity.kind === 'scholarship' || opportunity.provider
    ? opportunity.provider || opportunity.organization
    : opportunity.university || opportunity.organization;
}

function profileField(profile, field) {
  const academic = getProfileSection(profile, 'academicBackground');
  const english = getProfileSection(profile, 'englishProficiency');
  if (field === 'cgpa') return academic.cgpa || profile.cgpa;
  if (field === 'englishScore') return english.overallScore || profile.englishScore;
  if (field === 'englishTest') {
    const test = english.testType || profile.englishTest;
    return test === 'TOEFL iBT' ? 'TOEFL' : test;
  }
  return profile[field];
}

function profileFieldIsVerified(profile, field) {
  if (profile.profileComplete && profile.verifiedProfile) return true;
  const statuses = profile.fieldStatuses || profile.extractionFieldStatuses || {};
  const status = statuses[field] || statuses[field === 'cgpa' ? 'academicBackground.cgpa' : field];
  return status === 'verified' || status === 'confirmed';
}

function getRequirements(opportunity) {
  if (Array.isArray(opportunity.requirements)) return opportunity.requirements;
  if (getOpportunityKind(opportunity) === 'scholarship') return [];

  const requirements = [];
  if (opportunity.cgpaReq) {
    requirements.push({
      id: 'minimum-cgpa',
      category: 'academic',
      label: 'Minimum CGPA',
      field: 'cgpa',
      operator: 'minimum',
      value: opportunity.cgpaReq,
      sourceStatus: opportunity.sourceStatus || 'unverified-sample',
      required: true,
    });
  }
  if (opportunity.englishReq) {
    requirements.push({
      id: 'language-test',
      category: 'language',
      label: 'Language proficiency',
      field: 'englishScore',
      acceptedTests: ['IELTS', 'TOEFL', 'Duolingo'],
      displayRequirement: opportunity.englishReq,
      sourceStatus: opportunity.sourceStatus || 'unverified-sample',
      required: true,
    });
  }
  return requirements;
}

function evaluateRequirement(requirement, profile) {
  if (requirement.sourceStatus !== 'official-verified') return 'awaiting-verification';
  const value = profileField(profile, requirement.field);
  if (value === undefined || value === null || value === '') return 'missing-information';
  if (!profileFieldIsVerified(profile, requirement.field)) return 'awaiting-verification';

  if (requirement.field === 'englishScore' && requirement.acceptedTests?.length) {
    const test = profileField(profile, 'englishTest');
    if (!test || !requirement.acceptedTests.some((accepted) => accepted.toLowerCase() === test.toLowerCase())) {
      return 'not-satisfied';
    }
  }

  if (requirement.operator === 'minimum') {
    const actual = Number.parseFloat(value);
    const minimum = Number.parseFloat(requirement.value);
    if (!Number.isFinite(actual) || !Number.isFinite(minimum)) return 'missing-information';
    if (actual < minimum) return 'not-satisfied';
  }

  return 'satisfied';
}

export function evaluateOpportunityEligibility(profile, opportunity) {
  const requirements = getRequirements(opportunity);
  if (requirements.length === 0) {
    return {
      status: 'awaiting-verification',
      requirements: [],
      message: 'Structured requirements are not available for this opportunity.',
    };
  }

  const evaluated = requirements.map((requirement) => ({
    ...requirement,
    status: evaluateRequirement(requirement, profile),
  }));
  const statuses = evaluated.map((requirement) => requirement.status);
  const status = statuses.includes('not-satisfied')
    ? 'not-satisfied'
    : statuses.includes('missing-information')
      ? 'missing-information'
      : statuses.includes('awaiting-verification')
        ? 'awaiting-verification'
        : 'satisfied';
  return { status, requirements: evaluated };
}

export function getOpportunityDocumentRequirements(opportunity) {
  return Array.isArray(opportunity.requiredDocuments) ? opportunity.requiredDocuments : [];
}

// A document with no record is missing. Uploads are awaiting verification until a backend marks them 'uploaded'.
export function getDocumentStatus(record) {
  if (!record) return 'missing';
  return record.status === 'uploaded' ? 'uploaded' : 'awaiting-verification';
}

// One entry per document ID across all selected opportunities, so the same record is reused everywhere.
export function aggregateRequiredDocuments(opportunities) {
  const byId = new Map();
  opportunities.forEach((opportunity) => {
    getOpportunityDocumentRequirements(opportunity).forEach((document) => {
      if (!document.id || !document.name) return;
      const entry = byId.get(document.id) || { id: document.id, name: document.name, sourceStatus: document.sourceStatus, requiredBy: [] };
      if (!entry.requiredBy.some((item) => item.id === opportunity.id)) {
        entry.requiredBy.push({ id: opportunity.id, title: getOpportunityTitle(opportunity) });
      }
      byId.set(document.id, entry);
    });
  });
  return [...byId.values()];
}

export function getOpportunityTimelineTasks(profile, opportunity, pathway) {
  if (!opportunity) return [];
  const evaluation = evaluateOpportunityEligibility(profile, opportunity);
  const tasks = evaluation.requirements
    .filter((requirement) => requirement.status !== 'satisfied')
    .map((requirement) => ({
      id: `requirement:${opportunity.id}:${requirement.id}`,
      opportunityId: opportunity.id,
      kind: 'requirement',
      title: `${requirement.status === 'missing-information' ? 'Provide' : 'Review'} ${requirement.label.toLowerCase()}`,
      status: 'todo',
      dueDate: null,
      source: requirement.sourceStatus,
      reason: requirement.status,
      requirement,
    }));

  getOpportunityDocumentRequirements(opportunity).forEach((document) => {
    if (!document.id || !document.name) return;
    tasks.push({
      id: `document:${opportunity.id}:${document.id}`,
      opportunityId: opportunity.id,
      kind: 'document',
      title: `Prepare ${document.name}`,
      status: 'todo',
      dueDate: null,
      source: document.sourceStatus || 'opportunity-data',
      reason: document.reason || 'Required by the selected opportunity.',
      document,
      documentId: document.id,
    });
  });

  const pathwaySteps = pathway?.opportunityId === opportunity.id && Array.isArray(pathway.steps)
    ? pathway.steps
    : [];
  const submissionStepIndex = pathwaySteps.findIndex((step) => (
    /\b(submit|application|apply)\b/i.test(step.title || '') &&
    /\b(university|graduate|admission)\b/i.test(step.title || '')
  ));

  if (opportunity.deadline && submissionStepIndex < 0) {
    tasks.push({
      id: `deadline:${opportunity.id}`,
      opportunityId: opportunity.id,
      kind: 'deadline',
      title: `Submit ${getOpportunityTitle(opportunity)} application`,
      status: 'todo',
      dueDate: opportunity.deadline,
      source: opportunity.deadlineStatus || 'unverified-sample',
      reason: 'Application closing date available in opportunity data.',
    });
  }

  if (pathwaySteps.length) {
    pathwaySteps.forEach((step, index) => {
      if (!step.id || !step.title) return;
      const carriesDeadline = index === submissionStepIndex && Boolean(opportunity.deadline);
      tasks.push({
        id: `pathway:${opportunity.id}:${step.id}`,
        opportunityId: opportunity.id,
        kind: 'pathway',
        title: step.title,
        status: 'todo',
        dueDate: step.dueDate || (carriesDeadline ? opportunity.deadline : null),
        source: carriesDeadline
          ? opportunity.deadlineStatus || 'unverified-sample'
          : step.sourceStatus || 'pathway-sample',
        reason: carriesDeadline
          ? `Listed application date. ${step.description || 'Application pathway step.'}`
          : step.description || 'Application pathway step.',
      });
    });
  }
  return tasks;
}

export function getOpportunityProgress(opportunity, taskStatuses = {}, pathway = null, profile = {}) {
  const tasks = getOpportunityTimelineTasks(profile, opportunity, pathway);
  if (tasks.length === 0) return { tasks, percentage: 0, completed: 0, nextTask: null };
  const completed = tasks.filter((task) => (
    (taskStatuses[task.id] || task.status) === 'done'
  )).length;
  const nextTask = tasks.find((task) => (taskStatuses[task.id] || task.status) !== 'done') || null;
  return { tasks, percentage: Math.round((completed / tasks.length) * 100), completed, nextTask };
}
