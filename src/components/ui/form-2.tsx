import * as React from "react";
import { ArrowLeft, ArrowRight, CalendarDays, Check, ChevronDown, GraduationCap, Languages, Lightbulb, Pencil, Save, AlertCircle, Target, UserRound, WalletCards, FileText, Info, type LucideIcon } from "lucide-react";
import { Button } from "./button";
import { EMPTY_PROFILE, LAST_PROFILE_STEP, PROFILE_STEPS as STEPS, mergeProfile, type StudentProfile } from "../../data/profileModel";

const FIELDS = ["Computer Science", "Software Engineering", "Artificial Intelligence", "Data Science", "Cybersecurity", "Machine Learning", "Information Technology", "Other"];
const COUNTRIES = ["Pakistan", "Germany", "Netherlands", "Sweden", "Canada", "United States", "United Kingdom", "Australia", "New Zealand", "Other"];
const REGIONS = ["Europe", "North America", "Asia-Pacific", "Global"];
const FUNDING_TYPES = ["Government scholarships", "University scholarships", "Tuition waivers", "Research assistantships", "Teaching assistantships", "Fully funded fellowships", "Other"];
const DOCUMENTS: [string, string, LucideIcon][] = [
  ["cv", "CV / Resume", GraduationCap], ["transcript", "Academic Transcript", FileText],
  ["degreeCertificate", "Degree Certificate", GraduationCap], ["englishCertificate", "English Proficiency Certificate", GraduationCap],
  ["moiCertificate", "Medium of Instruction Certificate", GraduationCap], ["statementOfPurpose", "Statement of Purpose (SOP)", FileText],
  ["passport", "Passport", FileText], ["recommendationLetters", "Recommendation Letters", GraduationCap],
];

function Field({ label, required = false, error = "", className = "", children }: {
  label: React.ReactNode;
  required?: boolean;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`block text-sm ${className}`}>
      <span className="mb-1.5 block font-medium text-slate-700 dark:text-slate-200">{label}{required && <span className="ml-1 text-red-600">*</span>}</span>
      {children}
      {error && <span className="mt-1 flex items-center gap-1 text-xs text-red-600 dark:text-red-300"><AlertCircle size={12} />{error}</span>}
    </label>
  );
}

function GroupField({ label, required = false, error = "", className = "", children }: {
  label: string;
  required?: boolean;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`profile-choice-field ${className}`}>
      <div className="profile-choice-label">{label}{required && <span>*</span>}</div>
      {children}
      {error && <span className="profile-choice-error"><AlertCircle size={11} />{error}</span>}
    </div>
  );
}

type ControlProps =
  | (Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange"> & { as?: "input"; error?: string })
  | (React.SelectHTMLAttributes<HTMLSelectElement> & { as: "select"; error?: string })
  | (React.TextareaHTMLAttributes<HTMLTextAreaElement> & { as: "textarea"; error?: string });

function Control(props: ControlProps) {
  const controlClassName = `h-9 w-full rounded-md border ${props.error ? "!border-red-500 bg-red-50/40" : "border-slate-200"} bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-sky-950 ${props.as === "textarea" ? "h-auto py-2" : ""} ${props.className || ""}`;
  if (props.as === "select") {
    const { as, error, className, ...selectProps } = props;
    return <select className={controlClassName} aria-invalid={Boolean(error)} {...selectProps} />;
  }
  if (props.as === "textarea") {
    const { as, error, className, ...textareaProps } = props;
    return <textarea className={controlClassName} aria-invalid={Boolean(error)} {...textareaProps} />;
  }
  const { as, error, className, ...inputProps } = props;
  return <input className={controlClassName} aria-invalid={Boolean(error)} {...inputProps} />;
}

export function addTypedOption(value: string[], options: string[], typed: string) {
  const text = typed.trim().replace(/\s+/g, " ");
  if (!text) return value;
  const sameText = (item: string) => item.toLowerCase() === text.toLowerCase();
  return value.some(sameText) ? value : [...value, options.find(sameText) || text];
}

function MultiSelect({ label, options, value, onChange, placeholder = "Search or select...", allowTyped = false }: {
  label: string;
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  allowTyped?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const typedValues = value.filter((item) => !options.includes(item)); // listed too, or they could never be removed
  const filteredOptions = [...typedValues, ...options].filter((option) => option.toLowerCase().includes(query.toLowerCase()));
  const typedText = query.trim();
  const canAddTyped = allowTyped && typedText !== "" && ![...value, ...options].some((item) => item.toLowerCase() === typedText.toLowerCase());
  const addTyped = () => {
    onChange(addTypedOption(value, options, query));
    setQuery("");
  };

  return (
    <div className="profile-multi-select">
      <button
        type="button"
        className="profile-multi-select-trigger"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="profile-multi-select-values">
          {value.length ? value.map((item) => <span className="profile-multi-select-chip" key={item}>{item}<span aria-hidden="true">×</span></span>) : <span className="profile-multi-select-placeholder">{placeholder}</span>}
        </span>
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open && (
        <div className="profile-multi-select-menu">
          <input
            type="search"
            value={query}
            aria-label={`Search ${label}`}
            placeholder={allowTyped ? "Search, or type your own and press Enter" : "Search options..."}
            maxLength={100}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setOpen(false);
              if (event.key === "Enter" && allowTyped) { event.preventDefault(); addTyped(); }
            }}
          />
          <div className="profile-multi-select-options">
            {canAddTyped && <button type="button" onClick={addTyped}><span>Add “{typedText}”</span></button>}
            {filteredOptions.length ? filteredOptions.map((option) => {
              const selected = value.includes(option);
              return <button key={option} type="button" aria-pressed={selected} onClick={() => onChange(selected ? value.filter((item) => item !== option) : [...value, option])}><span>{option}</span>{selected && <Check size={12} aria-hidden="true" />}</button>;
            }) : !canAddTyped && <span className="profile-multi-select-empty">No matching options</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, description, className = "", children }: {
  title: string;
  description?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return <section className={`rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6 ${className}`}><h2 className="text-lg font-bold text-slate-900 dark:text-white">{title}</h2>{description && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{description}</p>}<div className="mt-5">{children}</div></section>;
}

export function validateStep(step: number, values: StudentProfile) {
  const personal = values.personalInfo;
  const academic = values.academicBackground;
  const goals = values.studyPreferences;
  const errors: Record<string, string> = {};
  if (step === 0) {
    if (!personal.fullName.trim()) errors.fullName = "Enter your full name.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(personal.email)) errors.email = "Enter a valid email address.";
    if (!personal.citizenshipCountry) errors.citizenshipCountry = "Select your nationality.";
    if (!personal.currentCountry) errors.currentCountry = "Select your current country.";
  }
  if (step === 1) {
    if (!academic.currentDegree) errors.currentDegree = "Select your highest degree.";
    if (!academic.degreeTitle.trim()) errors.degreeTitle = "Enter your degree title or major.";
    if (!academic.institution.trim()) errors.institution = "Enter your university name.";
    if (!academic.institutionCountry) errors.institutionCountry = "Select the university country.";
    if (!academic.academicStatus) errors.academicStatus = "Select your study status.";
    if (academic.academicStatus === "studying" && !academic.currentYear.trim()) errors.currentYear = "Select your current semester or year.";
    if (academic.academicStatus === "studying" && !academic.expectedGraduationDate) errors.expectedGraduationDate = "Enter your expected graduation date.";
    if (academic.academicStatus === "graduated" && !academic.graduationDate) errors.graduationDate = "Enter your graduation date.";
    if (!academic.degreeStartDate) errors.degreeStartDate = "Enter your degree start date.";
    if (!academic.cgpa.trim()) errors.cgpa = "Enter your grade.";
    const grade = Number(academic.cgpa);
    const scale = Number(academic.gradingScale === "Other" ? academic.customGradingScale : academic.gradingScale);
    if (academic.cgpa && (!Number.isFinite(grade) || grade < 0 || (Number.isFinite(scale) && grade > scale))) errors.cgpa = `Enter a grade between 0 and ${academic.gradingScale || "the selected scale"}.`;
    if (!academic.gradingScale || !Number.isFinite(scale) || scale <= 0) errors.gradingScale = "Enter the maximum grade or percentage.";
    if (academic.gradingScale === "Other" && (!academic.customGradingScale || !Number.isFinite(scale) || scale <= 0)) errors.customGradingScale = "Enter a valid maximum grade.";
    if (academic.expectedGraduationDate && !/^\d{4}-(0[1-9]|1[0-2])$/.test(academic.expectedGraduationDate)) errors.expectedGraduationDate = "Use the YYYY-MM date format.";
    if (academic.graduationDate && !/^\d{4}-(0[1-9]|1[0-2])$/.test(academic.graduationDate)) errors.graduationDate = "Use the YYYY-MM date format.";
    if (academic.degreeStartDate && academic.expectedGraduationDate && academic.expectedGraduationDate < academic.degreeStartDate) errors.expectedGraduationDate = "Expected graduation cannot be before the start date.";
    if (academic.degreeStartDate && academic.graduationDate && academic.graduationDate < academic.degreeStartDate) errors.graduationDate = "Graduation cannot be before the start date.";
  }
  if (step === 2) {
    if (!goals.fields.length) errors.fields = "Select at least one preferred study field.";
    // Recommendations and the profile status work from countries, so a region alone isn't enough
    if (!goals.countries.some((country) => country !== "Other") && !goals.otherCountry.trim()) errors.countries = "Select at least one preferred country.";
  }
  if (step === 3) {
    if (!values.studyPreferences.fundingPreference) errors.fundingPreference = "Select a funding preference.";
    for (const [field, label] of [["maxTuitionBudget", "Annual tuition budget"], ["maxLivingCostBudget", "Monthly living budget"]]) {
      const value = values.studyPreferences[field];
      if (!value) errors[field] = `Enter your ${label.toLowerCase()}.`;
      else if (!Number.isFinite(Number(value)) || Number(value) < 0) errors[field] = `${label} must be a valid non-negative number.`;
    }
    if (!/^[A-Za-z]{3}$/.test(values.studyPreferences.currency || "")) errors.currency = "Enter a valid 3-letter currency code, such as USD.";
    if (!values.studyPreferences.fundingPreferences.length) errors.fundingPreferences = "Select at least one preferred funding type.";
    if (!values.englishProficiency.willingToTest) errors.willingToTest = "Choose whether you are willing to take an English proficiency test.";
    if (!values.englishProficiency.testStatus) errors.testStatus = "Select your English test status.";
    if (values.englishProficiency.testStatus === "Completed") {
      if (!values.englishProficiency.testType || values.englishProficiency.testType === "No Test / Not Taken") errors.testType = "Select the English test you took.";
      if (!values.englishProficiency.overallScore) errors.overallScore = "Enter your overall score.";
      if (values.englishProficiency.testType === "Other" && !values.englishProficiency.otherTestName.trim()) errors.otherTestName = "Enter the name of the English test.";
    }
    if (values.englishProficiency.overallScore && !values.englishProficiency.testType) errors.testType = "Select the test type for this score.";
    if (values.englishProficiency.testType === "No Test / Not Taken"
      && [values.englishProficiency.overallScore, values.englishProficiency.listening, values.englishProficiency.reading, values.englishProficiency.writing, values.englishProficiency.speaking].some(Boolean)) {
      errors.testType = "Clear the test scores or select the test they belong to.";
    }
    if (values.englishProficiency.overallScore && (!Number.isFinite(Number(values.englishProficiency.overallScore)) || Number(values.englishProficiency.overallScore) < 0)) {
      errors.overallScore = "Enter a valid non-negative score.";
    }
    const limits = {
      IELTS: { overall: 9, section: 9 },
      "TOEFL iBT": { overall: 120, section: 30 },
      PTE: { overall: 90, section: 90 },
      "Duolingo English Test": { overall: 160, section: 160 },
    };
    const scoreLimits = limits[values.englishProficiency.testType];
    if (scoreLimits && values.englishProficiency.overallScore) {
      const score = Number(values.englishProficiency.overallScore);
      if (score > scoreLimits.overall) errors.overallScore = `The ${values.englishProficiency.testType} overall score cannot exceed ${scoreLimits.overall}.`;
      if (values.englishProficiency.testType === "TOEFL iBT" && !Number.isInteger(score)) errors.overallScore = "The TOEFL iBT overall score must be a whole number.";
    }
    if (scoreLimits) {
      for (const field of ["listening", "reading", "writing", "speaking"] as const) {
        const value = values.englishProficiency[field];
        if (value && (!Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > scoreLimits.section)) {
          errors[field] = `The ${values.englishProficiency.testType} ${field} score must be between 0 and ${scoreLimits.section}.`;
        }
      }
    }
    const testDate = values.englishProficiency.testDate;
    const [year, month, day] = (testDate || "").split("-").map(Number);
    const parsedTestDate = new Date(Date.UTC(year, month - 1, day));
    const validTestDate = /^\d{4}-\d{2}-\d{2}$/.test(testDate || "")
      && parsedTestDate.getUTCFullYear() === year
      && parsedTestDate.getUTCMonth() === month - 1
      && parsedTestDate.getUTCDate() === day;
    if (testDate && (!validTestDate || testDate > new Date().toISOString().slice(0, 10))) {
      errors.testDate = "Enter a valid test date that is not in the future.";
    }
  }
  return errors;
}

/** The first step with a problem, for when the review finds something the form didn't catch. */
export function firstInvalidStep(values: StudentProfile) {
  for (let step = 0; step < LAST_PROFILE_STEP; step += 1) {
    const errors = validateStep(step, values);
    if (Object.keys(errors).length) return { step, errors };
  }
  return null;
}

function reviewList(items: (string | undefined)[]) {
  return items.filter((item) => item && item !== "Other").join(", ");
}

type ReviewSectionTitle = "About You" | "Academic Background" | "Study Goals" | "Language & Funding";

const REVIEW_SECTION_META: Record<ReviewSectionTitle, { icon: LucideIcon; step: number }> = {
  "About You": { icon: UserRound, step: 0 },
  "Academic Background": { icon: GraduationCap, step: 1 },
  "Study Goals": { icon: Target, step: 2 },
  "Language & Funding": { icon: Languages, step: 3 },
};

function reviewSections(values: StudentProfile): [ReviewSectionTitle, [string, string][]][] {
  const { personalInfo: personal, academicBackground: academic, studyPreferences: goals, englishProficiency: english } = values;
  const scale = academic.gradingScale === "Other" ? academic.customGradingScale : academic.gradingScale;
  return [
    ["About You", [["Full Name", personal.fullName], ["Email", personal.email], ["Nationality", personal.citizenshipCountry], ["Country of Residence", personal.currentCountry], ["Date of Birth", personal.dateOfBirth], ["Phone Number", personal.phoneNumber]]],
    ["Academic Background", [["Degree", academic.currentDegree], ["Degree Title / Major", academic.degreeTitle], ["Academic Field", academic.major], ["University", academic.institution], ["Current Semester / Year", academic.currentYear], ["CGPA", academic.cgpa !== "" ? `${academic.cgpa} / ${scale}` : ""], [academic.academicStatus === "graduated" ? "Graduation Date" : "Expected Graduation", academic.academicStatus === "graduated" ? academic.graduationDate : academic.expectedGraduationDate], ["Skills", reviewList([academic.technicalSkills, academic.programmingLanguages])], ["Research Interests", academic.projects]]],
    ["Study Goals", [["Target Degree Level", goals.intendedDegree], ["Preferred Fields", reviewList([...goals.fields, goals.customField])], ["Preferred Destinations", reviewList([...goals.countries, goals.otherCountry, ...goals.regions])]]],
    ["Language & Funding", [["English Test Status", english.testStatus], ["Willingness to Take an English Test", english.willingToTest], ["English Test", english.testType === "Other" ? english.otherTestName : english.testType], ["Overall Score", english.overallScore], ["Listening", english.listening], ["Reading", english.reading], ["Writing", english.writing], ["Speaking", english.speaking], ["Test Date", english.testDate], ["Funding Preference", goals.fundingPreference], ["Preferred Funding Types", reviewList(goals.fundingPreferences)], ["Annual Tuition Budget", goals.maxTuitionBudget !== "" ? `${goals.currency} ${goals.maxTuitionBudget}` : ""], ["Monthly Living Budget", goals.maxLivingCostBudget !== "" ? `${goals.currency} ${goals.maxLivingCostBudget}` : ""]]],
  ];
}

export default function FormLayout01({
  onSave,
  onComplete,
  onCancel,
  onStepChange,
  initialValues,
  initialStep = 0,
  isSaving = false,
  saveError = "",
  finalButtonLabel = "Complete My Profile",
  requiresReviewConfirmation = false,
  editing = false,
  completionPercent = 0,
  notice = null,
  extractionSource = "",
}: {
  onSave?: (values: any, progress: { step: number; complete: boolean }) => Promise<boolean | { success?: boolean; persisted?: boolean }> | boolean | { success?: boolean; persisted?: boolean };
  onComplete?: () => void;
  onCancel?: () => void;
  onStepChange?: (step: number) => void;
  initialValues?: any;
  initialStep?: number;
  isSaving?: boolean;
  saveError?: string;
  finalButtonLabel?: string;
  requiresReviewConfirmation?: boolean;
  editing?: boolean;
  completionPercent?: number;
  notice?: React.ReactNode;
  extractionSource?: string;
  [key: string]: any;
}) {
  const [values, setValues] = React.useState(() => mergeProfile(initialValues || EMPTY_PROFILE));
  const [step, setStep] = React.useState(Math.min(Math.max(initialStep, 0), LAST_PROFILE_STEP));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [feedback, setFeedback] = React.useState("");
  const [reviewConfirmed, setReviewConfirmed] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const submitLock = React.useRef(false);
  const progressPercent = editing ? completionPercent : Math.round(((step + 1) / STEPS.length) * 100);
  const isBusy = isSaving || isSubmitting;
  const cancel = () => (onCancel ? onCancel() : window.history.back());

  React.useEffect(() => {
    setStep(Math.min(Math.max(initialStep, 0), LAST_PROFILE_STEP));
  }, [initialStep]);

  const update = (section, field, value) => {
    setValues((current) => ({ ...current, [section]: { ...current[section], [field]: value } }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };
  const updateDocument = (field, value) => setValues((current) => ({ ...current, documentAvailability: { ...current.documentAvailability, [field]: value } }));
  const goTo = (nextStep) => {
    setStep(nextStep);
    onStepChange?.(nextStep);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const save = async (complete = false) => {
    setFeedback("");
    const result = await onSave?.(values, { step, complete });
    if (result === false || (result && typeof result === "object" && result.success === false)) return false;
    if (result && typeof result === "object" && result.persisted === false) setFeedback("Draft saved on this device. It has not been synced to your account.");
    else setFeedback(complete ? "Profile saved successfully." : "Draft saved. You can continue later.");
    return true;
  };
  const continueStep = async () => {
    if (submitLock.current || isBusy) return;
    submitLock.current = true;
    setIsSubmitting(true);
    try {
      if (step < LAST_PROFILE_STEP && !editing) {
        const nextErrors = validateStep(step, values);
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length) return;
        if (await save(false)) goTo(step + 1);
        return;
      }
      const problem = firstInvalidStep(values);
      if (problem) {
        setErrors(problem.errors);
        goTo(problem.step);
        return;
      }
      if (requiresReviewConfirmation && !reviewConfirmed) {
        setErrors({ reviewConfirmed: "Confirm that you have checked the details taken from your CV." });
        return;
      }
      if (await save(true)) onComplete?.();
    } finally {
      submitLock.current = false;
      setIsSubmitting(false);
    }
  };
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void continueStep();
  };

  const personal = values.personalInfo;
  const academic = values.academicBackground;
  const goals = values.studyPreferences;
  const english = values.englishProficiency;
  const degreeOptions: { value: string; label: string }[] = [
    { value: "Bachelor's", label: "Bachelor's Degree" },
    { value: "Master's", label: "Master's Degree" },
    { value: "Diploma", label: "Associate Degree / Diploma" },
    { value: "Other", label: "Other" },
  ];
  if (academic.currentDegree && !degreeOptions.some(({ value }) => value === academic.currentDegree)) {
    degreeOptions.unshift({ value: academic.currentDegree, label: academic.currentDegree });
  }
  const gradingScaleOptions = ["4.00", "5.00", "10.00", "100.00", "Other"];
  if (academic.gradingScale && !gradingScaleOptions.includes(academic.gradingScale)) {
    gradingScaleOptions.unshift(academic.gradingScale);
  }
  const input = (section, field, props = {}) => <Control {...props} value={values[section][field] || ""} error={errors[field]} onChange={(event) => update(section, field, event.target.value)} />;
  const monthInput = (field) => (
    <span className={`profile-month-control${errors[field] ? " has-error" : ""}`}>
      <CalendarDays size={12} aria-hidden="true" />
      <Control
        type="month"
        className="profile-month-picker"
        value={(academic[field] || "").slice(0, 7)}
        error={errors[field]}
        onChange={(event) => update("academicBackground", field, event.target.value)}
        onClick={(event) => {
          if (typeof event.currentTarget.showPicker === "function") event.currentTarget.showPicker();
        }}
      />
    </span>
  );
  const select = (section, field, options, props = {}) => <Control as="select" {...props} value={values[section][field] || ""} error={errors[field]} onChange={(event) => update(section, field, event.target.value)}><option value="">Select...</option>{options.map((option) => {
    const item = typeof option === "string" ? { value: option, label: option } : option;
    return <option key={item.value} value={item.value}>{item.label}</option>;
  })}</Control>;
  const selectedFields = goals.customField && !goals.fields.includes("Other")
    ? [...goals.fields, "Other"]
    : goals.fields;
  const destinationOptions = [...COUNTRIES, ...REGIONS];
  const selectedDestinations = [...goals.countries, ...goals.regions];
  const updateDestinations = (destinations) => {
    update("studyPreferences", "countries", destinations.filter((destination) => !REGIONS.includes(destination)));
    update("studyPreferences", "regions", destinations.filter((destination) => REGIONS.includes(destination)));
  };

  const footerActions = <footer className={`profile-wizard-actions mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800${step === 1 ? " is-academic-sticky" : ""}${step === LAST_PROFILE_STEP ? " profile-review-actions" : ""}`}>{!editing && <Button type="button" variant="outline" size="sm" onClick={() => save(false)} disabled={isBusy}><Save size={12} className="mr-1.5" />Save Draft</Button>}<div className="ml-auto flex gap-2">{(step === 0 || editing) && <Button type="button" variant="outline" size="sm" onClick={cancel} disabled={isBusy}>Cancel</Button>}{step > 0 && <Button type="button" variant="outline" size="sm" onClick={() => goTo(step - 1)} disabled={isBusy}><ArrowLeft size={12} className="mr-1" />Back</Button>}<Button type="submit" size="sm" disabled={isBusy}>{isBusy ? "Saving..." : editing ? "Save Changes" : step === LAST_PROFILE_STEP ? finalButtonLabel : "Continue"}{step === LAST_PROFILE_STEP || editing ? <Check size={12} className="ml-1.5" /> : <ArrowRight size={12} className="ml-1.5" />}</Button></div></footer>;
  const review = reviewSections(values);
  const renderReviewSection = ([title, rows]: ReturnType<typeof reviewSections>[number]) => {
    const { icon: Icon, step: editStep } = REVIEW_SECTION_META[title];
    return <section key={title} aria-label={title} className="profile-review-card">
      <header className="profile-review-card-header">
        <div className="profile-review-card-title">
          <span className="profile-review-card-icon"><Icon size={16} aria-hidden="true" /></span>
          <h2>{title}</h2>
        </div>
        <button type="button" onClick={() => goTo(editStep)} className="profile-review-edit" aria-label={`Edit ${title} section`}>
          <Pencil size={14} aria-hidden="true" /> <span>Edit Section</span>
        </button>
      </header>
      <dl className="profile-review-rows">
        {rows.map(([label, value]) => {
          const missing = !value.trim();
          return (
            <div key={label} className="profile-review-row">
              <dt>{label}</dt>
              <dd className={missing ? "profile-review-value is-missing" : "profile-review-value"}>{missing ? "Not provided" : value}</dd>
            </div>
          );
        })}
      </dl>
    </section>;
  };

  return <div className="profile-wizard-root min-h-[calc(100vh-48px)] w-full bg-slate-50 dark:bg-slate-950">
    <div className="profile-wizard-content w-full">
    <header className={`profile-wizard-header mb-6${step === LAST_PROFILE_STEP ? " profile-review-header" : ""}`}>
      <div className="profile-wizard-heading flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-start gap-2"><button type="button" onClick={cancel} className="mt-0.5 rounded-md p-1 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white" aria-label="Go back"><ArrowLeft size={16} /></button><div><h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-[26px]">{step === LAST_PROFILE_STEP ? "Review Your Profile" : editing ? "Edit your profile" : "Build your Master's profile"}</h1>{step === LAST_PROFILE_STEP && <p className="profile-review-subtitle">Review your information before completing your profile.</p>}</div></div>
        {step === LAST_PROFILE_STEP && <span className="profile-review-completion"><Check size={13} aria-hidden="true" />{progressPercent}% complete</span>}
      </div>
      {step < LAST_PROFILE_STEP && <div className="mt-4">
        <p className="text-xs font-semibold text-sky-700 dark:text-sky-300">{editing ? <>Profile {progressPercent}% complete</> : <>Step {step + 1} of {STEPS.length} · {progressPercent}% complete</>}</p>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="progressbar" aria-label="Profile setup progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent}><div className="h-full rounded-full bg-sky-600 transition-all" style={{ width: `${progressPercent}%` }} /></div>
      </div>}
      <div className="profile-wizard-stepper mt-5 flex items-center" aria-label="Profile progress">{STEPS.map((title, index) => <React.Fragment key={title}><button type="button" onClick={() => (index <= step || editing) && goTo(index)} className="flex min-w-0 items-center gap-2 text-left" aria-label={`Go to ${title}`}><span className={`profile-wizard-step-number flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${index <= step ? "border-sky-600 bg-sky-600 text-white" : "border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-900"}`}>{index < step ? <Check size={12} strokeWidth={3} /> : index + 1}</span><span className={`profile-wizard-step-label text-[11px] ${index === step ? "font-semibold text-sky-700 dark:text-sky-300" : "text-slate-500"}`}>{title}</span></button>{index < STEPS.length - 1 && <span className={`profile-wizard-step-line mx-2 h-px min-w-5 flex-1 ${index < step ? "bg-sky-300" : "bg-slate-200 dark:bg-slate-700"}`} />}</React.Fragment>)}</div>
    </header>

    {notice}
    {saveError && <p role="alert" className="profile-wizard-notice border border-red-200 bg-red-50 text-red-700"><AlertCircle size={16} aria-hidden="true" />{saveError}</p>}
    {feedback && <p role="status" className="profile-wizard-notice border border-emerald-200 bg-emerald-50 text-emerald-700"><Check size={16} aria-hidden="true" />{feedback}</p>}

    <form onSubmit={handleSubmit} noValidate>
    {Object.values(errors).some(Boolean) && <p role="alert" className="profile-wizard-notice border border-red-200 bg-red-50 text-red-700">Please correct the highlighted fields before continuing.</p>}

    {step === 0 && <Section title="About You" description="Let's start with your basic information." className="profile-about-panel"><div className="profile-about-fields grid gap-4 sm:grid-cols-2">
      <Field label="Full Name" required error={errors.fullName}>{input("personalInfo", "fullName", { autoComplete: "name" })}</Field>
      <Field label="Email Address" required error={errors.email}>{input("personalInfo", "email", { type: "email", autoComplete: "email", className: "profile-email-input" })}</Field>
      <Field label="Nationality" required error={errors.citizenshipCountry}>{select("personalInfo", "citizenshipCountry", COUNTRIES)}</Field>
      <Field label="Current Country of Residence" required error={errors.currentCountry}>{select("personalInfo", "currentCountry", COUNTRIES)}</Field>
      <Field label={<>Date of Birth <span className="font-normal text-slate-500">(optional, used for scholarship age limits)</span></>}>{input("personalInfo", "dateOfBirth", { type: "date", autoComplete: "bday" })}</Field>
      <Field label={<>Phone Number <span className="font-normal text-slate-500">(optional)</span></>} >{input("personalInfo", "phoneNumber", { type: "tel", autoComplete: "tel" })}</Field>
    </div>{footerActions}</Section>}

    {step === 1 && <Section title="Academic Background" description="Tell us about your education history and current study status." className="profile-academic-panel">
      <section className="profile-academic-group">
        <h3>Current degree</h3>
        <div className="profile-academic-fields grid gap-x-4 gap-y-2 sm:grid-cols-2">
          <Field label="Current or Highest Degree" required error={errors.currentDegree}>{select("academicBackground", "currentDegree", degreeOptions)}</Field>
          <Field label="Degree Title / Major" required error={errors.degreeTitle}>{input("academicBackground", "degreeTitle")}</Field>
          <Field label="University Name" required error={errors.institution}>{input("academicBackground", "institution")}</Field>
          <Field label="Country of University" required error={errors.institutionCountry}>{select("academicBackground", "institutionCountry", COUNTRIES)}</Field>
          <Field label="Degree Start Date" required error={errors.degreeStartDate}>{monthInput("degreeStartDate")}</Field>
        </div>
      </section>

      <section className="profile-academic-group">
        <h3>Status</h3>
        <GroupField label="Current Study Status" required error={errors.academicStatus}>
          <div className={`profile-academic-status${errors.academicStatus ? " has-error" : ""}`}>
            {([["studying", "Currently studying"], ["graduated", "Graduated"]] as const).map(([value, label]) => (
              <label key={value} className={errors.academicStatus ? "has-error" : ""}>
                <input type="radio" name="academicStatus" value={value} aria-invalid={Boolean(errors.academicStatus)} checked={academic.academicStatus === value} onChange={(event) => update("academicBackground", "academicStatus", event.target.value)} />
                {label}
              </label>
            ))}
          </div>
        </GroupField>
        {academic.academicStatus === "studying" ? (
          <div className="profile-academic-fields grid gap-x-4 gap-y-2 sm:grid-cols-2">
            <Field label="Current Semester / Year" required error={errors.currentYear}>{select("academicBackground", "currentYear", ["1st Semester", "2nd Semester", "3rd Semester", "4th Semester", "5th Semester", "6th Semester", "7th Semester", "8th Semester"])}</Field>
            <Field label="Expected Graduation Date" required error={errors.expectedGraduationDate}>{monthInput("expectedGraduationDate")}</Field>
          </div>
        ) : academic.academicStatus === "graduated" ? (
          <div className="profile-academic-fields grid gap-x-4 gap-y-2 sm:grid-cols-2">
            <Field label="Graduation Date" required error={errors.graduationDate}>{monthInput("graduationDate")}</Field>
          </div>
        ) : null}
      </section>

      <section className="profile-academic-group">
        <h3>Performance</h3>
        <div className="profile-academic-fields grid gap-x-4 gap-y-2 sm:grid-cols-2">
          <Field label="CGPA / Percentage" required error={errors.cgpa}>{input("academicBackground", "cgpa", { type: "number", min: "0", step: "0.01", placeholder: "e.g. 3.65" })}</Field>
          <Field label="Grading Scale / Maximum CGPA" required error={errors.gradingScale}>
            {select("academicBackground", "gradingScale", gradingScaleOptions)}
            <span className="profile-academic-hint">Example: 3.65 / 4.0</span>
          </Field>
          {academic.gradingScale === "Other" && <Field label="Custom maximum grade" required error={errors.customGradingScale}>{input("academicBackground", "customGradingScale", { type: "number", min: "0", step: "0.01" })}</Field>}
          <Field label="Academic Achievements (Optional)">
            <Control as="textarea" rows={2} maxLength={500} value={academic.academicAchievements || ""} onChange={(event) => update("academicBackground", "academicAchievements", event.target.value)} placeholder="e.g. Dean's list, scholarships, awards, research projects..." />
          </Field>
          <Field label="Technical Skills (Optional)">
            <Control as="textarea" rows={2} maxLength={500} value={academic.technicalSkills || ""} onChange={(event) => update("academicBackground", "technicalSkills", event.target.value)} placeholder="e.g. Python, SQL, machine learning..." />
          </Field>
          <Field label="Projects / Research (Optional)">
            <Control as="textarea" rows={2} maxLength={500} value={academic.projects || ""} onChange={(event) => update("academicBackground", "projects", event.target.value)} placeholder="e.g. final-year project, publications, research interests..." />
          </Field>
          <Field label="Work Experience (Optional)">
            <Control as="textarea" rows={2} maxLength={2000} value={academic.workExperience || ""} onChange={(event) => update("academicBackground", "workExperience", event.target.value)} placeholder="e.g. internships, jobs, volunteering, with dates..." />
          </Field>
        </div>
      </section>

      <details className="profile-previous-degree">
        <summary>Previous Degree <span>(Optional)</span></summary>
        <p>Add details if you have completed a previous degree.</p>
        <div className="profile-academic-fields grid gap-x-4 gap-y-2 sm:grid-cols-2">
          <Field label="Degree Title / Major">{input("academicBackground", "previousDegreeTitle", { placeholder: "e.g. Associate Degree" })}</Field>
          <Field label="University Name">{input("academicBackground", "previousDegreeInstitution", { placeholder: "e.g. Government College" })}</Field>
          <Field label="Graduation Date">{monthInput("previousDegreeDate")}</Field>
        </div>
      </details>
      {footerActions}
    </Section>}

    {step === 2 && <Section title="Study Goals" description="Tell us about your preferred degree, field, destination and study preferences." className="profile-study-panel">
      <div className="profile-study-goals-grid">
        <Field label="Intended Degree" required className="profile-goal-degree">
          <span className="profile-goal-icon-control"><GraduationCap size={12} aria-hidden="true" /><Control as="select" value={goals.intendedDegree || "Master's"} onChange={(event) => update("studyPreferences", "intendedDegree", event.target.value)}><option value="Master's">Master's (MSc/MS)</option></Control></span>
        </Field>
        <GroupField label="Preferred Study Fields" required error={errors.fields} className="profile-goal-fields">
          <MultiSelect label="Preferred Study Fields" options={FIELDS} value={selectedFields} onChange={(fields) => { update("studyPreferences", "fields", fields); if (!fields.includes("Other")) update("studyPreferences", "customField", ""); }} placeholder="Search, select or type a field..." allowTyped />
          <span className="profile-goal-helper">Select multiple options</span>
        </GroupField>
        <GroupField label="Preferred Countries / Regions" required error={errors.countries} className="profile-goal-destinations">
          <MultiSelect label="Preferred Countries / Regions" options={destinationOptions} value={selectedDestinations} onChange={updateDestinations} placeholder="Search or select destinations..." />
          <span className="profile-goal-helper">Select multiple options</span>
        </GroupField>
        {goals.fields.includes("Other") && <Field label="Other preferred field" className="profile-goal-other-field">{input("studyPreferences", "customField", { placeholder: "Enter your preferred field" })}</Field>}
        {goals.countries.includes("Other") && <Field label="Other preferred destination" className="profile-goal-other-country">{input("studyPreferences", "otherCountry", { placeholder: "Enter a country" })}</Field>}
        <div className="profile-study-tip"><Lightbulb size={13} aria-hidden="true" /><span>You can always update your preferences later. We'll match you with opportunities based on your current choices.</span></div>
      </div>
      {footerActions}
    </Section>}

    {step === 3 && <section className="profile-funding-panel">
      <header className="profile-funding-heading">
        <WalletCards size={18} aria-hidden="true" />
        <div><h2>Funding Preferences</h2><p>Tell us about your financial situation and preferred funding options.</p></div>
      </header>
      <div className="profile-funding-grid">
        <Field label="Funding Preference" required error={errors.fundingPreference} className="profile-funding-preference">
          {select("studyPreferences", "fundingPreference", ["Fully funded only", "Fully funded or substantial scholarship", "Partial scholarship acceptable", "Self-funded options acceptable", "Not sure"])}
        </Field>
        <Field label={<>Maximum Annual Tuition Budget ({goals.currency || "USD"})</>} required error={errors.maxTuitionBudget} className="profile-funding-tuition">
          <span className="profile-money-control"><span>{goals.currency === "USD" || !goals.currency ? "$" : goals.currency}</span>{input("studyPreferences", "maxTuitionBudget", { type: "number", min: "0", placeholder: "e.g. 25,000" })}</span>
        </Field>
        <Field label={<>Monthly Living Expense Budget ({goals.currency || "USD"})</>} required error={errors.maxLivingCostBudget} className="profile-funding-living">
          <span className="profile-money-control"><span>{goals.currency === "USD" || !goals.currency ? "$" : goals.currency}</span>{input("studyPreferences", "maxLivingCostBudget", { type: "number", min: "0", placeholder: "e.g. 800" })}</span>
        </Field>
        <Field label="Budget Currency (3-letter code)" required error={errors.currency} className="profile-funding-currency">
          {input("studyPreferences", "currency", { type: "text", maxLength: 3, placeholder: "USD", autoCapitalize: "characters" })}
        </Field>
        <GroupField label="Preferred Funding Types (Select all that apply)" required error={errors.fundingPreferences} className="profile-funding-types">
          <div className="profile-funding-type-options">
            {FUNDING_TYPES.map((type) => {
              const selected = goals.fundingPreferences.includes(type);
              return <label key={type} className="profile-funding-type-option"><input type="checkbox" checked={selected} onChange={() => update("studyPreferences", "fundingPreferences", selected ? goals.fundingPreferences.filter((item) => item !== type) : [...goals.fundingPreferences, type])} />{type}</label>;
            })}
          </div>
        </GroupField>
        <GroupField label="Willingness to Take an English Proficiency Test" required error={errors.willingToTest} className="profile-funding-willingness">
          <div className="profile-funding-radio-options" role="radiogroup" aria-label="Willing to take an English proficiency test?">
            {["Yes", "No", "Not sure"].map((option) => <label key={option}><input type="radio" name="willingToTest" value={option} checked={english.willingToTest === option} onChange={(event) => update("englishProficiency", "willingToTest", event.target.value)} />{option}</label>)}
          </div>
        </GroupField>
        <Field label="English Test Status" required error={errors.testStatus} className="profile-funding-test-status">
          {select("englishProficiency", "testStatus", ["Not taken", "Booked", "Completed", "Not sure"])}
        </Field>
        <Field label="English Test Type" error={errors.testType} className="profile-funding-test-type">
          {select("englishProficiency", "testType", ["IELTS", "TOEFL iBT", "PTE", "Duolingo English Test", "Other", "No Test / Not Taken"], { "aria-label": "English test type (optional)" })}
        </Field>
        {english.testType === "Other" && <Field label="Other English Test" error={errors.otherTestName} className="profile-funding-other-test">
          {input("englishProficiency", "otherTestName", { placeholder: "Enter the test name" })}
        </Field>}
        <Field label="Expected Test Score (Overall)" error={errors.overallScore} className="profile-funding-score">
          {input("englishProficiency", "overallScore", { type: "number", min: "0", step: "any", placeholder: "e.g. 7.0", "aria-label": "English test score (optional)" })}
        </Field>
        <Field label="Test Date" error={errors.testDate} className="profile-funding-test-date">
          {input("englishProficiency", "testDate", { type: "date" })}
        </Field>
        {["IELTS", "TOEFL iBT", "PTE"].includes(english.testType) && (["listening", "reading", "writing", "speaking"] as const).map((field) => (
          <Field key={field} label={field[0].toUpperCase() + field.slice(1)} error={errors[field]} className="profile-funding-section-score">
            {input("englishProficiency", field, { type: "number", min: "0", step: "any" })}
          </Field>
        ))}
        <Field label="Medium of Instruction (MOI) Certificate Available?" className="profile-funding-moi">
          {select("englishProficiency", "mediumOfInstruction", ["Yes", "No", "Not available"])}
        </Field>
      </div>
      <section className="profile-document-section">
        <header className="profile-document-heading">
          <FileText size={17} aria-hidden="true" />
          <div><h2>Document Availability</h2><p>Let us know which documents you currently have. You can upload them later.</p></div>
        </header>
        <div className="profile-document-tip"><Info size={12} aria-hidden="true" /><span>You can upload your documents anytime after creating your profile.</span></div>
        <div className="profile-document-grid">
          {DOCUMENTS.map(([key, label, Icon]) => <div key={key} className="profile-document-row">
            <span className="profile-document-icon"><Icon size={12} aria-hidden="true" /></span>
            <label htmlFor={`document-${key}`}>{label}</label>
            <select id={`document-${key}`} value={values.documentAvailability[key] || ""} onChange={(event) => updateDocument(key, event.target.value)} aria-label={`${label} availability`}>
              <option value="">Select...</option><option>Available</option><option>Not available</option><option>Not sure</option>
            </select>
          </div>)}
        </div>
      </section>
      {footerActions}
    </section>}

    {step === LAST_PROFILE_STEP && <section className="profile-review-panel" aria-label="Profile information review">
      <div className="profile-review-grid">
        <div className="profile-review-column">{review.slice(0, 2).map(renderReviewSection)}</div>
        <div className="profile-review-column">{review.slice(2).map(renderReviewSection)}</div>
      </div>
      {requiresReviewConfirmation && <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">
        {extractionSource === "api"
          ? "This draft includes information from the configured external CV extraction service. Review every field before saving."
          : "This draft was extracted locally in your browser. No external AI service was used. Review every field before saving."}
      </p>}
      {requiresReviewConfirmation && <label className="mt-5 flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
        <input type="checkbox" className="mt-0.5" aria-invalid={Boolean(errors.reviewConfirmed)} checked={reviewConfirmed} onChange={(event) => { setReviewConfirmed(event.target.checked); setErrors((current) => ({ ...current, reviewConfirmed: undefined })); }} />
        <span>I have checked the details taken from my CV, and they are correct.</span>
      </label>}
      {errors.reviewConfirmed && <span role="alert" className="mt-1 flex items-center gap-1 text-xs text-red-600 dark:text-red-300"><AlertCircle size={12} />{errors.reviewConfirmed}</span>}
      {footerActions}
    </section>}
    </form>
    </div>
  </div>;
}
