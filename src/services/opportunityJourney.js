export const TASK_STATUSES = ['todo', 'in-progress', 'done'];

function getProfileSection(profile, name) {
  const verified = profile.verifiedProfile || profile.profileDraft || profile;
  return verified[name] || profile[name] || {};
}

// Plain-language explanation shown on each requirement task
const REQUIREMENT_TASK_REASONS = {
  'missing-information': 'Your profile is missing the information needed to check this.',
  'not-satisfied': 'Your profile does not meet this requirement yet.',
  'awaiting-verification': 'Check this against the official program requirements.',
};

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
  if (field === 'cgpa') return academic.cgpa ?? profile.cgpa;
  if (field === 'englishScore') return english.overallScore ?? profile.englishScore;
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
      sourceStatus: opportunity.sourceStatus || 'unverified',
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
      sourceStatus: opportunity.sourceStatus || 'unverified',
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
  if (Array.isArray(opportunity.requiredDocuments) && opportunity.requiredDocuments.length > 0) {
    return opportunity.requiredDocuments;
  }
  return mapRequiredDocumentNames(
    [],
    opportunity.requiredDocumentsText,
    opportunity.sourceStatus === 'official-verified',
  );
}

export function getOpportunityDocumentChecklist(opportunity, documentRecords = {}) {
  return getOpportunityDocumentRequirements(opportunity).map((document) => {
    const requirementVerified = document.sourceStatus === 'official-verified';
    const record = documentRecords[document.id];
    const fileStatus = getDocumentStatus(record);
    return {
      ...document,
      requirementStatus: requirementVerified ? 'confirmed' : 'needs-review',
      status: !requirementVerified
        ? 'needs-review'
        : fileStatus === 'uploaded'
          ? 'available'
          : fileStatus === 'awaiting-verification'
            ? 'needs-review'
            : 'missing',
    };
  });
}

export function buildPersonalizedGuidanceActions(guidance, {
  opportunity = null,
  pathway = null,
  documentRecords = {},
  financialResult = null,
} = {}) {
  const actions = [];
  const seen = new Set();
  let sequence = 0;

  const add = (action, rank, order = 0) => {
    if (!action.id || seen.has(action.id)) return;
    seen.add(action.id);
    actions.push({ ...action, rank, order, sequence: sequence++ });
  };

  (guidance?.recommendations || []).forEach((item) => {
    if (item.id === 'optional-budget' && financialResult) return;
    const rank = item.result_type === 'unmet'
      ? 0
      : item.result_type === 'optional'
        ? 5
        : 1;
    const completionCondition = item.result_type === 'missing_information'
      ? 'Save the missing information in your profile, then re-check this requirement.'
      : item.result_type === 'optional'
        ? 'Save the information to your profile.'
        : item.result_type === 'unmet' && item.actionability !== 'not_changeable'
          ? 'Re-check eligibility after any relevant profile update.'
          : null;
    add({
      id: item.id,
      kind: 'eligibility',
      priority: item.priority,
      title: item.title,
      explanation: item.gap,
      reason: item.why_it_matters,
      nextStep: item.suggested_action,
      requirement: item.requirement,
      related: item.related || [],
      route: item.action_route,
      completionCondition,
    }, rank, PRIORITY_ORDER_FOR_ACTION[item.priority] ?? 2);
  });

  (guidance?.opportunities || []).forEach((item) => {
    if (item.kind !== 'scholarship' || !item.deadline || item.status === 'not_eligible') return;
    const deadline = item.deadline;
    if (deadline.status === 'open' && deadline.date) {
      const daysLeft = Number.isFinite(deadline.days_left) ? deadline.days_left : null;
      const priority = daysLeft !== null && daysLeft <= 14
        ? 'High'
        : daysLeft !== null && daysLeft <= 45 ? 'Medium' : 'Low';
      add({
        id: `deadline-${item.id}`,
        kind: 'deadline',
        priority,
        title: `Review ${item.name} before its deadline`,
        explanation: `Verified deadline: ${deadline.date}${daysLeft === null ? '' : ` (${daysLeft} days left)`}.`,
        reason: 'The current official record lists this closing date.',
        nextStep: 'Check the official call and requirements before submitting.',
        requirement: 'Application deadline',
        related: [{ kind: 'scholarship', id: item.id, name: item.name, organization: item.organization,
          result: deadline.date, source_url: item.source_url }],
        route: `/scholarships/sch-db-${item.id}`,
        sourceUrl: item.source_url,
        dueDate: deadline.date,
        completionCondition: 'Confirm the official call and submit by the listed deadline if you apply.',
      }, 2, daysLeft ?? Number.MAX_SAFE_INTEGER);
    } else if (deadline.status === 'upcoming' && deadline.opens_on) {
      add({
        id: `opening-${item.id}`,
        kind: 'deadline',
        priority: 'Low',
        title: `Review ${item.name} when applications open`,
        explanation: `The verified record lists an opening date of ${deadline.opens_on}.`,
        reason: 'The application window has not opened yet.',
        nextStep: 'Confirm the current call and its closing date on the official page when it opens.',
        requirement: 'Application opening date',
        related: [{ kind: 'scholarship', id: item.id, name: item.name, organization: item.organization,
          result: deadline.opens_on, source_url: item.source_url }],
        route: `/scholarships/sch-db-${item.id}`,
        sourceUrl: item.source_url,
        dueDate: deadline.opens_on,
        completionCondition: null,
      }, 2, deadline.days_left ?? Number.MAX_SAFE_INTEGER);
    } else if (deadline.status === 'unknown') {
      add({
        id: `deadline-verify-${item.id}`,
        kind: 'deadline',
        priority: 'Medium',
        title: `Verify the current deadline for ${item.name}`,
        explanation: 'No exact deadline is available in the verified record.',
        reason: 'A deadline should not be assumed when the source has no current date.',
        nextStep: 'Check the scholarship provider’s official page for the current application deadline.',
        requirement: 'Application deadline',
        related: [{ kind: 'scholarship', id: item.id, name: item.name, organization: item.organization,
          result: 'Deadline not specified', source_url: item.source_url }],
        route: `/scholarships/sch-db-${item.id}`,
        sourceUrl: item.source_url,
        completionCondition: 'Confirm the current deadline on the official provider page.',
      }, 2, Number.MAX_SAFE_INTEGER);
    } else if (deadline.status === 'closed' && deadline.date) {
      add({
        id: `deadline-expired-${item.id}`,
        kind: 'deadline',
        priority: 'Low',
        title: `Check the next application cycle for ${item.name}`,
        explanation: `The last verified deadline, ${deadline.date}, has passed.`,
        reason: 'This listed date is historical and does not indicate that applications are currently open.',
        nextStep: 'Check the official page for a future cycle before planning an application.',
        requirement: 'Next application cycle',
        related: [{ kind: 'scholarship', id: item.id, name: item.name, organization: item.organization,
          result: `Expired: ${deadline.date}`, source_url: item.source_url }],
        route: `/scholarships/sch-db-${item.id}`,
        sourceUrl: item.source_url,
        dueDate: null,
        completionCondition: null,
      }, 3, 0);
    }
  });

  if (opportunity) {
    if (getOpportunityKind(opportunity) === 'program') {
      const currentPathway = pathway?.opportunityId === opportunity.id;
      const deadlineStep = currentPathway
        ? pathway.steps?.find((step) => step.id === 'deadline')
        : null;
      const recordedDeadline = currentPathway
        ? deadlineStep?.dueDate || null
        : opportunity.deadlineDate || opportunity.deadline || null;
      const confirmed = deadlineStep?.sourceStatus === 'official-verified' && recordedDeadline;
      const expired = deadlineStep?.sourceStatus === 'expired'
        && opportunity.deadlineStatus === 'official-verified';
      add({
        id: `program-deadline-${opportunity.id}`,
        kind: 'deadline',
        priority: expired ? 'Low' : 'Medium',
        title: expired
          ? `Check the next admission cycle for ${getOpportunityTitle(opportunity)}`
          : confirmed
            ? `Review ${getOpportunityTitle(opportunity)} before its deadline`
            : recordedDeadline
              ? `Confirm the recorded admission deadline for ${getOpportunityTitle(opportunity)}`
              : `Verify the admission deadline for ${getOpportunityTitle(opportunity)}`,
        explanation: expired
          ? deadlineStep.description
          : confirmed
            ? `Confirmed admission deadline: ${recordedDeadline}.`
            : recordedDeadline
              ? `The program record lists “${recordedDeadline}”; this date is not confirmed for the current application cycle.`
              : deadlineStep?.description || 'No admission deadline is recorded for this program.',
        reason: 'Confirm the current admission timeline before planning a submission.',
        nextStep: confirmed
          ? 'Review the university’s official instructions and submit before the listed date if you apply.'
          : 'Check the university’s official admissions page and follow its current application instructions.',
        requirement: 'Admission deadline',
        related: [],
        route: '/pathway',
        sourceUrl: pathway?.sourceUrl || opportunity.sourceUrl || opportunity.source_url || null,
        dueDate: confirmed ? recordedDeadline : null,
        completionCondition: confirmed
          ? 'Confirm the official instructions and submit by the listed deadline if you apply.'
          : 'Confirm the current admission deadline on the official university page.',
      }, 2, confirmed ? 100 : Number.MAX_SAFE_INTEGER - 1);
    }

    const documents = pathway?.opportunityId === opportunity.id && Array.isArray(pathway.documentChecklist)
      ? pathway.documentChecklist
      : getOpportunityDocumentChecklist(opportunity, documentRecords);
    if (documents.length === 0) {
      add({
        id: `documents-verify-${opportunity.id}`,
        kind: 'document',
        priority: 'Medium',
        title: `Confirm required documents for ${getOpportunityTitle(opportunity)}`,
        explanation: 'No provider-specific document list is recorded for this opportunity.',
        reason: 'Common preparation materials are not confirmed requirements unless the provider says so.',
        nextStep: 'Check the official provider checklist; use Documents to review or prepare confirmed items.',
        requirement: 'Document checklist',
        related: [],
        route: '/documents',
        sourceUrl: pathway?.sourceUrl || opportunity.sourceUrl || opportunity.officialUrl || null,
        completionCondition: 'Confirm the provider’s current document checklist.',
      }, 3);
    }
    documents.forEach((document) => {
      if (document.status === 'available') return;
      const requirementNeedsReview = document.requirementStatus !== 'confirmed';
      const uploadNeedsReview = !requirementNeedsReview && document.status === 'needs-review';
      add({
        id: `document-${opportunity.id}-${document.id}`,
        kind: 'document',
        priority: 'Medium',
        title: requirementNeedsReview
          ? `Verify whether ${document.name} is required`
          : uploadNeedsReview ? `Review the ${document.name} record` : `Prepare ${document.name}`,
        explanation: requirementNeedsReview
          ? `${document.name} is listed, but its requirement has not been verified from the official source.`
          : uploadNeedsReview
            ? `${document.name} is recorded but has not been verified as available.`
            : `${document.name} is a confirmed requirement and no verified document is available.`,
        reason: 'Use only provider-confirmed requirements and documents verified as available.',
        nextStep: requirementNeedsReview
          ? 'Check the official checklist before treating this as a requirement.'
          : 'Open Documents to review or prepare this item.',
        requirement: document.name,
        related: [],
        route: '/documents',
        sourceUrl: pathway?.sourceUrl || opportunity.sourceUrl || opportunity.officialUrl || null,
        completionCondition: uploadNeedsReview ? null : 'Review the source or document status in Documents.',
      }, 3);
    });
  }

  if (financialResult && financialResult.status !== 'feasible') {
    const missing = financialResult.missing_data || [];
    const explanations = financialResult.explanation || [];
    const insufficient = financialResult.status === 'insufficient_data';
    add({
      id: 'financial-feasibility',
      kind: 'financial',
      priority: financialResult.status === 'not_feasible' ? 'High' : 'Medium',
      title: insufficient ? 'Add the missing financial information' : 'Review the financial feasibility result',
      explanation: insufficient
        ? `Feasibility cannot be determined${missing.length ? `: ${missing.join('; ')}` : ' from the available data'}.`
        : explanations.join(' ') || `The current result is ${financialResult.status.replaceAll('_', ' ')}.`,
      reason: 'The selected program needs a reliable cost and budget comparison before affordability can be assessed.',
      nextStep: 'Review the saved budget, known expenses, and confirmed funding in the Financial Planner.',
      requirement: 'Financial feasibility',
      related: [],
      route: '/financial',
      completionCondition: insufficient
        ? 'Provide the missing cost or budget information listed by the Financial Planner and recalculate.'
        : null,
    }, 4);
  }

  return actions
    .sort((first, second) => first.rank - second.rank
      || first.order - second.order
      || first.sequence - second.sequence)
    .map((action) => {
      const result = { ...action };
      delete result.rank;
      delete result.order;
      delete result.sequence;
      return result;
    });
}

const PRIORITY_ORDER_FOR_ACTION = { High: 0, Medium: 1, Low: 2 };

export function mapRequiredDocumentNames(names, fallbackText, verified) {
  const mapName = (name) => ({
    id: name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
    name: name.trim(),
    sourceStatus: verified ? 'official-verified' : 'unverified',
  });
  const structured = (Array.isArray(names) ? names : [])
    .filter((name) => typeof name === 'string' && name.trim())
    .map(mapName);
  if (structured.length > 0 || typeof fallbackText !== 'string') return structured;

  return fallbackText
    .split(/\r?\n|;|[\u2022\u25cf\u25aa]/)
    .flatMap((line) => line.split(','))
    .map((name) => name.trim().replace(/^(?:[-*]\s*|\d+[.)]\s*)+/, '').replace(/[.,;]+$/, '').trim())
    .filter(Boolean)
    .map(mapName);
}

// A document with no record is missing. Uploads are awaiting verification until a backend marks them 'uploaded'.
export function getDocumentStatus(record) {
  if (!record) return 'missing';
  return record.status === 'uploaded' ? 'uploaded' : 'awaiting-verification';
}

function dateOnly(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value ? null : parsed;
}

function createPathwayStep(id, title, description, sourceStatus, details = {}) {
  return { id, title, description, sourceStatus, ...details };
}

export function buildApplicationPathway(opportunity, { documentRecords = {}, today = new Date() } = {}) {
  if (!opportunity?.id) return null;

  const kind = getOpportunityKind(opportunity);
  const title = getOpportunityTitle(opportunity);
  const sourceStatus = opportunity.sourceStatus === 'official-verified'
    ? 'official-verified'
    : 'needs-review';
  const steps = [
    createPathwayStep(
      'review-requirements',
      kind === 'scholarship' ? 'Review scholarship eligibility' : 'Review admission requirements',
      'Check the requirements recorded for this opportunity against your saved profile. Confirm any unverified details with the provider.',
      sourceStatus,
    ),
  ];

  const providerInstructions = [
    opportunity.applicationPathwayText,
    opportunity.applicationMethod,
    opportunity.applicationChannel ? `Application channel recorded: ${opportunity.applicationChannel}.` : null,
    opportunity.admissionRequired ? `Admission requirement recorded: ${opportunity.admissionRequired}` : null,
    opportunity.nominationRequired ? `Nomination requirement recorded: ${opportunity.nominationRequired}` : null,
  ].filter((value) => typeof value === 'string' && value.trim());

  if (providerInstructions.length) {
    steps.push(createPathwayStep(
      'provider-instructions',
      'Review provider application instructions',
      providerInstructions.join(' '),
      sourceStatus,
    ));
  } else {
    steps.push(createPathwayStep(
      'provider-instructions',
      'Confirm the application process',
      'No provider-specific application instructions are recorded. Check the official opportunity page before applying.',
      'needs-review',
    ));
  }

  const documents = getOpportunityDocumentRequirements(opportunity);
  steps.push(createPathwayStep(
    'prepare-documents',
    documents.some((document) => document.sourceStatus === 'official-verified')
      ? 'Prepare confirmed required documents'
      : 'Confirm the required document checklist',
    documents.length
      ? 'Use the checklist to distinguish confirmed requirements from details that still need verification.'
      : 'No provider-specific document list is recorded. Confirm the official checklist; common preparation materials are not requirements unless the provider says so.',
    documents.length && documents.every((document) => document.sourceStatus === 'official-verified')
      ? 'official-verified'
      : 'needs-review',
  ));

  const rawDeadline = opportunity.deadlineDate || opportunity.deadline || null;
  const parsedDeadline = dateOnly(rawDeadline);
  const deadlineVerified = opportunity.deadlineStatus === 'official-verified';
  const expired = parsedDeadline && parsedDeadline < new Date(Date.UTC(
    today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate(),
  ));
  const deadlineDescription = parsedDeadline
    ? expired
      ? `The recorded deadline for ${title} was ${rawDeadline} and has passed. Verify the next cycle with the provider.`
      : deadlineVerified
        ? `Confirmed application deadline: ${rawDeadline}.`
        : `A deadline of ${rawDeadline} is recorded, but its source needs verification before you rely on it.`
    : rawDeadline
      ? `Recorded deadline wording: ${rawDeadline}. Confirm the applicable date with the official provider.`
      : 'No application deadline is recorded. Check the official provider page for the current deadline.';
  steps.push(createPathwayStep(
    'deadline',
    expired ? 'Verify the next application cycle' : 'Confirm the application deadline',
    deadlineDescription,
    expired ? 'expired' : deadlineVerified ? 'official-verified' : 'needs-review',
    parsedDeadline ? { dueDate: rawDeadline } : {},
  ));

  const applicationUrlVerified = opportunity.applicationUrl
    && opportunity.applicationUrlStatus === 'official-verified';
  steps.push(createPathwayStep(
    'submission-route',
    applicationUrlVerified ? 'Review the official application portal' : 'Confirm the official submission route',
    applicationUrlVerified
      ? 'The opportunity record includes an official application link. Review the provider instructions before submitting.'
      : 'No verified application link is recorded. Do not infer a submission URL; confirm the route with the provider.',
    applicationUrlVerified ? 'official-verified' : 'needs-review',
    applicationUrlVerified ? { url: opportunity.applicationUrl } : {},
  ));

  return {
    opportunityId: opportunity.id,
    opportunityTitle: title,
    sourceStatus,
    sourceUrl: opportunity.sourceUrl || opportunity.officialUrl || null,
    steps,
    documentChecklist: getOpportunityDocumentChecklist(opportunity, documentRecords),
    preparationNote: 'General preparation can include academic records, a CV, a statement of purpose, recommendation letters, or language evidence. These are suggestions only, not confirmed requirements.',
  };
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
      // Lower-case only the first letter so acronyms such as CGPA stay readable
      title: `${requirement.status === 'missing-information' ? 'Provide' : 'Review'} ${requirement.label.charAt(0).toLowerCase()}${requirement.label.slice(1)}`,
      status: 'todo',
      dueDate: null,
      source: requirement.sourceStatus,
      reason: REQUIREMENT_TASK_REASONS[requirement.status] || REQUIREMENT_TASK_REASONS['awaiting-verification'],
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
  const hasDeadlineStep = pathwaySteps.some((step) => (
    step.id === 'deadline' || /\bdeadline\b/i.test(step.title || '')
  ));

  if (opportunity.deadline && submissionStepIndex < 0 && !hasDeadlineStep) {
    tasks.push({
      id: `deadline:${opportunity.id}`,
      opportunityId: opportunity.id,
      kind: 'deadline',
      title: `Submit ${getOpportunityTitle(opportunity)} application`,
      status: 'todo',
      dueDate: opportunity.deadline,
      source: opportunity.deadlineStatus || 'unverified',
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
          ? opportunity.deadlineStatus || 'unverified'
          : step.sourceStatus || 'unverified',
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
