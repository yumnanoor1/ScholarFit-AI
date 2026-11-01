// Loads the real JSX through Vite, because node --test can't read it directly.
import { after, before, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createElement as h } from 'react';
import { renderToString } from 'react-dom/server';
import { Route, Routes, StaticRouter } from 'react-router-dom';
import { createServer } from 'vite';

const READY = { status: 'ready', required: true, complete: false, percent: 40, missing: ['University'] };
const DONE = { ...READY, complete: true, percent: 100, missing: [] };
const ADMIN = { ...READY, required: false };

let vite;
let access;
let ProfileContext;
let ProfileGate;
let Sidebar;
let AuthProvider;
let wizard;
let profileApi;
let storage;
let profileModel;
let ProfileSetupChoice;
let ProfileCompleted;
let Settings;
let ProfileSavedNotice;

function fakeStorage() {
  const items = new Map();
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
  };
}

const withCompletion = (completion, child) => h(ProfileContext.Provider, { value: { completion } }, child);

const page = (completion, gate) => renderToString(withCompletion(completion,
  h(StaticRouter, { location: '/dashboard' }, h(Routes, null,
    h(Route, { element: h(ProfileGate, { gate }) },
      h(Route, { path: '/dashboard', element: h('main', null, 'Private page') }))))));

const sidebar = (completion) => renderToString(h(StaticRouter, { location: '/profile' },
  h(AuthProvider, null, withCompletion(completion, h(Sidebar)))));

function validProfile() {
  const values = profileModel.mergeProfile();
  Object.assign(values.personalInfo, { fullName: 'Student', email: 'student@example.com', citizenshipCountry: 'Pakistan', currentCountry: 'Pakistan' });
  Object.assign(values.academicBackground, {
    currentDegree: "Bachelor's", degreeTitle: 'BS Computer Science', institution: 'NUST', institutionCountry: 'Pakistan', academicStatus: 'studying',
    currentYear: '7th Semester', expectedGraduationDate: '2027-06', degreeStartDate: '2023-09', cgpa: '3.4', gradingScale: '4.00',
  });
  Object.assign(values.studyPreferences, {
    fields: ['Data Science'], countries: ['Germany'], intake: 'Fall', admissionYear: '2028', programPreference: 'Either', languageOfInstruction: 'English',
    fundingPreference: 'Not sure', maxTuitionBudget: '1000', maxLivingCostBudget: '500', fundingPreferences: ['Tuition waivers'],
  });
  Object.assign(values.englishProficiency, { willingToTest: 'Yes', testStatus: 'Not taken' });
  return values;
}

before(async () => {
  vite = await createServer({
    configFile: false, // the project's CSS plugins aren't needed here and take over a minute
    envDir: fileURLToPath(new URL('.', import.meta.url)), // not the project's .env: results mustn't depend on it
    resolve: { alias: { '@': fileURLToPath(new URL('..', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom',
    logLevel: 'silent',
  });
  access = await vite.ssrLoadModule('/src/services/profileAccess.js');
  ({ ProfileContext } = await vite.ssrLoadModule('/src/context/ProfileContext.jsx'));
  ({ AuthProvider } = await vite.ssrLoadModule('/src/context/AuthContext.jsx'));
  ({ default: ProfileGate } = await vite.ssrLoadModule('/src/navigation/ProfileGate.jsx'));
  ({ default: Sidebar } = await vite.ssrLoadModule('/src/components/layout/Sidebar.jsx'));
  wizard = await vite.ssrLoadModule('/src/components/ui/form-2.tsx');
  profileApi = await vite.ssrLoadModule('/src/services/profileApi.js');
  storage = await vite.ssrLoadModule('/src/services/userStorage.js');
  profileModel = await vite.ssrLoadModule('/src/data/profileModel.ts');
  ({ default: ProfileSetupChoice } = await vite.ssrLoadModule('/src/pages/ProfileSetupChoice.jsx'));
  ({ default: ProfileCompleted } = await vite.ssrLoadModule('/src/pages/ProfileCompleted.jsx'));
  ({ default: Settings } = await vite.ssrLoadModule('/src/pages/Settings.jsx'));
  ({ ProfileSavedNotice } = await vite.ssrLoadModule('/src/components/profile/ProfileNotices.jsx'));
});

after(async () => {
  await vite.close();
});

beforeEach(() => {
  Object.defineProperty(globalThis, 'localStorage', { value: fakeStorage(), configurable: true, writable: true });
});

after(() => {
  delete globalThis.window;
});

test('new accounts go to onboarding, and finished ones to the dashboard', () => {
  const student = { role: 'student' };
  assert.equal(access.homePathFor(student, READY), '/profile-setup');
  assert.equal(access.homePathFor(student, DONE), '/dashboard');
  assert.equal(access.homePathFor({ role: 'admin' }, READY), '/admin/scholarships');
});

test('an incomplete student is sent from any feature to onboarding', () => {
  assert.equal(access.decideAccess(READY, 'complete'), '/profile-setup');
  assert.equal(access.decideAccess(READY, 'onboarding'), 'allow');
  assert.equal(access.decideAccess(READY, 'any'), 'allow');
});

test('finishing the profile unlocks the app and moves on from onboarding', () => {
  assert.equal(access.decideAccess(DONE, 'complete'), 'allow');
  assert.equal(access.decideAccess(DONE, 'onboarding'), '/dashboard');
  assert.equal(access.decideAccess(DONE, 'any'), 'allow');
});

test('no redirect ever leads back to the page that sent it', () => {
  for (const completion of [READY, DONE, ADMIN]) {
    const target = access.decideAccess(completion, 'complete');
    if (target === '/profile-setup') assert.equal(access.decideAccess(completion, 'onboarding'), 'allow');
    const moved = access.decideAccess(completion, 'onboarding');
    if (moved === '/dashboard') assert.equal(access.decideAccess(completion, 'complete'), 'allow');
  }
});

test('administrators are never held back by a student profile', () => {
  assert.equal(access.canUseApp(ADMIN), true);
  assert.equal(access.decideAccess(ADMIN, 'complete'), 'allow');
});

test('nothing is decided until the API has answered', () => {
  for (const gate of ['complete', 'onboarding', 'any']) {
    assert.equal(access.decideAccess(access.LOADING_COMPLETION, gate), 'wait');
    assert.equal(access.decideAccess(access.FAILED_COMPLETION, gate), 'failed');
  }
  assert.equal(access.canUseApp(access.LOADING_COMPLETION), false);
  assert.equal(access.canUseApp(access.FAILED_COMPLETION), false);
});

test('a direct URL renders nothing private while loading, incomplete or failed', () => {
  assert.doesNotMatch(page(access.LOADING_COMPLETION, 'complete'), /Private page/);
  assert.doesNotMatch(page(READY, 'complete'), /Private page/);
  assert.doesNotMatch(page(access.FAILED_COMPLETION, 'complete'), /Private page/);
  assert.match(page(access.LOADING_COMPLETION, 'complete'), /Checking your profile/);
  assert.match(page(access.FAILED_COMPLETION, 'complete'), /couldn’t check your profile/);
  assert.match(page(DONE, 'complete'), /Private page/);
});

test('the sidebar lists only what an incomplete student can open', () => {
  const html = sidebar(READY);
  assert.match(html, /Complete profile/);
  assert.match(html, /My Profile/);
  assert.match(html, /Log out/);
  for (const hidden of ['Explore', 'Compare', 'Financial Planner', 'Application Pathway', 'Documents', 'Settings', '>Dashboard<']) {
    assert.ok(!html.includes(hidden), hidden);
  }
});

test('the sidebar stays locked until the status is known', () => {
  assert.doesNotMatch(sidebar(access.LOADING_COMPLETION), /Compare/);
});

test('a finished profile gets the whole sidebar back', () => {
  const html = sidebar(DONE);
  for (const shown of ['Dashboard', 'Explore', 'Compare', 'Settings', 'Log out']) assert.match(html, new RegExp(shown));
  assert.doesNotMatch(html, /Complete profile/);
});

test('a stored profile row is not treated as finished', () => {
  const mapped = profileApi.mapBackendToFrontendProfile({ id: 1, user_id: 2, degree_level: "Bachelor's", cgpa: 3.1 }, { name: 'Student' }, {});
  assert.equal(mapped.profileComplete, false);
  assert.equal(mapped.profileStatus, 'draft');
  assert.equal('profileCompletionPercentage' in mapped, false);
});

test('the graduation date survives a round trip through the API', () => {
  const backend = { academic_status: 'studying', graduation_date: '2027-06', field_of_study: 'CS', degree_level: "Bachelor's" };
  assert.equal(profileApi.mapBackendToFrontendProfile(backend, {}, {}).academicBackground.expectedGraduationDate, '2027-06');
  const graduated = { ...backend, academic_status: 'graduated' };
  assert.equal(profileApi.mapBackendToFrontendProfile(graduated, {}, {}).academicBackground.graduationDate, '2027-06');
});

test('a custom grading scale reaches the API without clamping the grade', () => {
  const values = validProfile();
  Object.assign(values.academicBackground, { gradingScale: 'Other', customGradingScale: '7', cgpa: '6.5' });
  const payload = profileApi.mapFrontendToBackendProfile(values);
  assert.equal(payload.cgpa_scale, 7);
  assert.equal(payload.cgpa, 6.5);
});

test('refreshing keeps the onboarding step and draft', () => {
  globalThis.window = { localStorage };
  storage.writeUserProfile(7, { profileSetupStep: 3, profileDraft: { personalInfo: { fullName: 'Student' } } });
  const restored = storage.readUserProfile(7);
  assert.equal(restored.profileSetupStep, 3);
  assert.equal(restored.profileDraft.personalInfo.fullName, 'Student');
  delete globalThis.window;
});

test('the wizard reports its progress step by step', () => {
  const render = (initialStep) => renderToString(h(wizard.default, { initialStep, initialValues: validProfile() }));
  assert.match(render(0), /Step <!-- -->1<!-- --> of <!-- -->5<!-- --> · <!-- -->20<!-- -->% complete/);
  assert.match(render(1), /40<!-- -->% complete/);
  assert.match(render(4), /100<!-- -->% complete/);
  assert.match(render(4), /Review &amp; Complete/);
});

test('required fields are checked at every step, and optional ones are not', () => {
  assert.equal(wizard.firstInvalidStep(validProfile()), null);
  const blank = wizard.validateStep(0, profileModel.mergeProfile());
  assert.ok(blank.citizenshipCountry && blank.currentCountry);
  assert.equal(blank.dateOfBirth, undefined);
  assert.equal(blank.phoneNumber, undefined);
});

test('a review sends the student back to the first unfinished step', () => {
  const values = validProfile();
  values.academicBackground.institution = '';
  const problem = wizard.firstInvalidStep(values);
  assert.equal(problem.step, 1);
  assert.ok(problem.errors.institution);
});

test('a region alone is refused, because recommendations work from countries', () => {
  const values = validProfile();
  Object.assign(values.studyPreferences, { countries: [], regions: ['Europe'] });
  assert.ok(wizard.validateStep(2, values).countries);
  Object.assign(values.studyPreferences, { countries: ['Other'], otherCountry: '' });
  assert.ok(wizard.validateStep(2, values).countries);
  values.studyPreferences.otherCountry = 'Norway';
  assert.equal(wizard.validateStep(2, values).countries, undefined);
});

test('a finished profile opening setup goes to the dashboard', () => {
  assert.equal(access.decideAccess(DONE, 'onboarding'), '/dashboard');
  assert.equal(access.homePathFor({ role: 'student' }, DONE), '/dashboard');
});

test('a student whose profile became incomplete is held back until it is fixed', () => {
  const lapsed = { ...DONE, complete: false, percent: 89, missing: ['University'] };
  assert.equal(access.decideAccess(lapsed, 'complete'), '/profile-setup');
  assert.equal(access.decideAccess(lapsed, 'onboarding'), 'allow');
  assert.equal(access.decideAccess(lapsed, 'any'), 'allow');
});

const choice = (value) => renderToString(h(ProfileContext.Provider, { value },
  h(StaticRouter, { location: '/profile-setup' }, h(ProfileSetupChoice))));

test('setup explains what is missing to a returning student, not to a new one', () => {
  const html = choice({ completion: READY, hasBackendProfile: true });
  assert.match(html, /Please complete: <!-- -->University/);
  assert.doesNotMatch(choice({ completion: READY, hasBackendProfile: false }), /Please complete/);
});

const done = (location) => renderToString(withCompletion(DONE, h(StaticRouter, { location }, h(ProfileCompleted))));

test('the completion confirmation shows once, and never by direct URL', () => {
  assert.match(done({ pathname: '/profile-setup/complete', state: { justCompleted: true } }), /Your profile is complete/);
  assert.doesNotMatch(done('/profile-setup/complete'), /Your profile is complete/);
});

test('the editor saves straight away, with no draft or onboarding wording', () => {
  const html = renderToString(h(wizard.default, { editing: true, completionPercent: 100, initialStep: 2, initialValues: validProfile() }));
  assert.match(html, /Edit your profile/);
  assert.match(html, /Save Changes/);
  assert.match(html, /Cancel/);
  assert.match(html, /Profile <!-- -->100<!-- -->% complete/);
  for (const hidden of ['Save Draft', 'Continue', 'Complete My Profile', 'Step ']) assert.ok(!html.includes(hidden), hidden);
});

test('onboarding keeps its steps and draft button', () => {
  const html = renderToString(h(wizard.default, { initialStep: 2, initialValues: validProfile() }));
  assert.match(html, /Save Draft/);
  assert.match(html, /Continue/);
  assert.doesNotMatch(html, /Save Changes/);
});

test('settings opens the profile editor and shows progress', () => {
  const html = renderToString(h(StaticRouter, { location: '/settings' },
    h(AuthProvider, null, withCompletion(DONE, h(Settings)))));
  assert.match(html, /Edit Profile/);
  assert.match(html, /100<!-- -->% complete/);
});

test('a save confirmation appears only after a save', () => {
  const notice = (location) => renderToString(h(StaticRouter, { location }, h(ProfileSavedNotice)));
  assert.match(notice({ pathname: '/settings', state: { profileSaved: true } }), /changes have been saved/);
  assert.doesNotMatch(notice('/settings'), /changes have been saved/);
});

test('edits to preferred fields reach the API after a reload', () => {
  const loaded = profileApi.mapBackendToFrontendProfile({ field_of_study: 'Data Science, Marine Biology', degree_level: "Bachelor's" }, {}, {});
  assert.deepEqual(loaded.studyPreferences.fields, ['Data Science', 'Marine Biology']);
  assert.equal(loaded.academicBackground.major, 'Data Science, Marine Biology');
  loaded.studyPreferences.fields = ['Cybersecurity'];
  assert.equal(profileApi.mapFrontendToBackendProfile(loaded).field_of_study, 'Cybersecurity');
});

test('an optional field can be cleared by an edit', () => {
  const values = validProfile();
  values.academicBackground.technicalSkills = '';
  values.academicBackground.projects = '';
  const payload = profileApi.mapFrontendToBackendProfile(values, { skills: ['Python'], researchExperience: 'Old project' });
  assert.equal(payload.skills, null);
  assert.equal(payload.research_interests, null);
});

test('a reload keeps the degree title apart from the degree level', () => {
  const cached = validProfile();
  const loaded = profileApi.mapBackendToFrontendProfile({ degree_level: "Bachelor's" }, {}, cached);
  assert.equal(loaded.academicBackground.degreeTitle, 'BS Computer Science');
});

test('a study field can be typed, without duplicating a listed one', () => {
  const options = ['Data Science'];
  assert.deepEqual(wizard.addTypedOption([], options, '  Marine   Biology '), ['Marine Biology']);
  assert.deepEqual(wizard.addTypedOption([], options, 'data science'), ['Data Science']);
  assert.deepEqual(wizard.addTypedOption(['Marine Biology'], options, 'marine biology'), ['Marine Biology']);
  assert.deepEqual(wizard.addTypedOption(['Marine Biology'], options, '   '), ['Marine Biology']);
  const values = validProfile();
  values.studyPreferences.fields = ['Marine Biology'];
  assert.equal(wizard.validateStep(2, values).fields, undefined);
});

test('a completed English test needs its type and score, and no test does not', () => {
  const values = validProfile();
  values.englishProficiency.testStatus = 'Completed';
  const errors = wizard.validateStep(3, values);
  assert.ok(errors.testType && errors.overallScore);
  values.englishProficiency.testStatus = 'Not taken';
  assert.deepEqual(wizard.validateStep(3, values), {});
});

test('CV details need the student to confirm them on the review step', () => {
  const props = { initialStep: 4, initialValues: validProfile() };
  assert.match(renderToString(h(wizard.default, { ...props, requiresReviewConfirmation: true })), /I have checked the details taken from my CV/);
  assert.doesNotMatch(renderToString(h(wizard.default, props)), /I have checked the details/);
});
