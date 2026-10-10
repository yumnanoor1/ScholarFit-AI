import * as React from "react";
import { ArrowLeft, ArrowRight, CalendarDays, Check, ChevronDown, GraduationCap, Globe2, Lightbulb, Save, AlertCircle, WalletCards, FileText, Info, type LucideIcon } from "lucide-react";
import { Button } from "./button";
import { EMPTY_PROFILE, mergeProfile, type StudentProfile } from "../../data/profileModel";

const STEPS = ["About You", "Academic Background", "Study Goals", "Funding & Documents"];
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
  const controlClassName = `h-9 w-full rounded-md border ${props.error ? "border-red-400" : "border-slate-200"} bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-sky-950 ${props.as === "textarea" ? "h-auto py-2" : ""} ${props.className || ""}`;
  if (props.as === "select") {
    const { as, error, className, ...selectProps } = props;
    return <select className={controlClassName} {...selectProps} />;
  }
  if (props.as === "textarea") {
    const { as, error, className, ...textareaProps } = props;
    return <textarea className={controlClassName} {...textareaProps} />;
  }
  const { as, error, className, ...inputProps } = props;
  return <input className={controlClassName} {...inputProps} />;
}

function MultiSelect({ label, options, value, onChange, placeholder = "Search or select..." }: {
  label: string;
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const filteredOptions = options.filter((option) => option.toLowerCase().includes(query.toLowerCase()));

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
            placeholder="Search options..."
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
          />
          <div className="profile-multi-select-options">
            {filteredOptions.length ? filteredOptions.map((option) => {
              const selected = value.includes(option);
              return <button key={option} type="button" aria-pressed={selected} onClick={() => onChange(selected ? value.filter((item) => item !== option) : [...value, option])}><span>{option}</span>{selected && <Check size={12} aria-hidden="true" />}</button>;
            }) : <span className="profile-multi-select-empty">No matching options</span>}
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

function validateStep(step: number, values: StudentProfile) {
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
    if (academic.academicStatus === "studying" && !academic.currentYear.trim()) errors.currentYear = "Enter your current semester or year.";
    if (academic.academicStatus === "studying" && !academic.expectedGraduationDate) errors.expectedGraduationDate = "Enter your expected graduation date.";
    if (academic.academicStatus === "graduated" && !academic.graduationDate) errors.graduationDate = "Enter your graduation date.";
    if (!academic.degreeStartDate) errors.degreeStartDate = "Enter your degree start date.";
    if (!academic.cgpa.trim()) errors.cgpa = "Enter your grade.";
    const grade = Number(academic.cgpa);
    const scale = Number(academic.gradingScale === "Other" ? academic.customGradingScale : academic.gradingScale);
    if (academic.cgpa && (!Number.isFinite(grade) || grade < 0 || (Number.isFinite(scale) && grade > scale))) errors.cgpa = `Enter a grade between 0 and ${academic.gradingScale || "the selected scale"}.`;
    if (!academic.gradingScale || !Number.isFinite(scale) || scale <= 0) errors.gradingScale = "Enter the maximum grade or percentage.";
    if (academic.gradingScale === "Other" && (!academic.customGradingScale || !Number.isFinite(scale) || scale <= 0)) errors.customGradingScale = "Enter a valid maximum grade.";
    if (academic.degreeStartDate && academic.expectedGraduationDate && academic.expectedGraduationDate < academic.degreeStartDate) errors.expectedGraduationDate = "Expected graduation cannot be before the start date.";
    if (academic.degreeStartDate && academic.graduationDate && academic.graduationDate < academic.degreeStartDate) errors.graduationDate = "Graduation cannot be before the start date.";
  }
  if (step === 2) {
    if (!goals.fields.length) errors.fields = "Select at least one preferred study field.";
    if (!goals.countries.length && !goals.regions.length) errors.countries = "Select at least one country or region.";
    if (!goals.intake) errors.intake = "Select an intended intake.";
    if (!goals.admissionYear) errors.admissionYear = "Select an admission year.";
    if (!goals.programPreference) errors.programPreference = "Select a program type.";
    if (!goals.languageOfInstruction.trim()) errors.languageOfInstruction = "Enter a preferred language.";
  }
  if (step === 3) {
    if (!values.studyPreferences.fundingPreference) errors.fundingPreference = "Select a funding preference.";
    for (const [field, label] of [["maxTuitionBudget", "Annual tuition budget"], ["maxLivingCostBudget", "Monthly living budget"]]) {
      const value = values.studyPreferences[field];
      if (!value) errors[field] = `Enter your ${label.toLowerCase()}.`;
      else if (!Number.isFinite(Number(value)) || Number(value) < 0) errors[field] = `${label} must be a valid non-negative number.`;
    }
    if (!values.studyPreferences.fundingPreferences.length) errors.fundingPreferences = "Select at least one preferred funding type.";
    if (!values.englishProficiency.willingToTest) errors.willingToTest = "Choose whether you are willing to take an English proficiency test.";
    if (!values.englishProficiency.testStatus) errors.testStatus = "Select your English test status.";
    if (values.englishProficiency.overallScore && (!Number.isFinite(Number(values.englishProficiency.overallScore)) || Number(values.englishProficiency.overallScore) < 0)) {
      errors.overallScore = "Enter a valid non-negative score.";
    }
  }
  return errors;
}

export default function FormLayout01({
  onSave,
  onComplete,
  onStepChange,
  initialValues,
  initialStep = 0,
  isSaving = false,
  saveError = "",
  finalButtonLabel = "Create My Profile",
}: {
  onSave?: (values: any, progress: { step: number; complete: boolean }) => Promise<boolean> | boolean;
  onComplete?: () => void;
  onStepChange?: (step: number) => void;
  initialValues?: any;
  initialStep?: number;
  isSaving?: boolean;
  saveError?: string;
  finalButtonLabel?: string;
}) {
  const [values, setValues] = React.useState(() => mergeProfile(initialValues || EMPTY_PROFILE));
  const [step, setStep] = React.useState(Math.min(Math.max(initialStep, 0), 3));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [feedback, setFeedback] = React.useState("");

  React.useEffect(() => {
    setStep(Math.min(Math.max(initialStep, 0), 3));
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
    if (result !== false) setFeedback(complete ? "Profile saved successfully." : "Draft saved. You can continue later.");
    return result !== false;
  };
  const continueStep = async () => {
    const nextErrors = validateStep(step, values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    if (step < 3) {
      if (await save(false)) goTo(step + 1);
    } else if (await save(true)) onComplete?.();
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
  const languageOptions = ["English", "French", "German", "Spanish", "Italian", "Japanese", "Mandarin", "Other"];
  if (goals.languageOfInstruction && !languageOptions.includes(goals.languageOfInstruction)) {
    languageOptions.unshift(goals.languageOfInstruction);
  }
  const updateDestinations = (destinations) => {
    update("studyPreferences", "countries", destinations.filter((destination) => !REGIONS.includes(destination)));
    update("studyPreferences", "regions", destinations.filter((destination) => REGIONS.includes(destination)));
  };

  const footerActions = <footer className="profile-wizard-actions mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800"><Button type="button" variant="outline" size="sm" onClick={() => save(false)} disabled={isSaving}><Save size={12} className="mr-1.5" />Save Draft</Button><div className="ml-auto flex gap-2">{step === 0 && <Button type="button" variant="outline" size="sm" onClick={() => window.history.back()} disabled={isSaving}>Cancel</Button>}{step > 0 && <Button type="button" variant="outline" size="sm" onClick={() => goTo(step - 1)} disabled={isSaving}><ArrowLeft size={12} className="mr-1" />Back</Button>}<Button type="button" size="sm" onClick={continueStep} disabled={isSaving}>{isSaving ? "Saving..." : step === 3 ? finalButtonLabel : "Continue"}{step === 3 ? <Check size={12} className="ml-1.5" /> : <ArrowRight size={12} className="ml-1.5" />}</Button></div></footer>;

  return <div className="profile-wizard-root min-h-[calc(100vh-48px)] w-full bg-slate-50 dark:bg-slate-950">
    <div className="profile-wizard-content mx-auto w-full max-w-5xl" style={{ maxWidth: "1260px" }}>
    <header className="profile-wizard-header mb-6">
      <div className="profile-wizard-heading flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-start gap-2"><button type="button" onClick={() => window.history.back()} className="mt-0.5 rounded-md p-1 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white" aria-label="Go back"><ArrowLeft size={16} /></button><div><h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-[26px]">Build your Master's profile</h1><p className="mt-1 text-xs text-slate-500 dark:text-slate-400 sm:text-sm">Complete your profile in 4 simple steps. You can save a draft and come back anytime.</p></div></div>
        <span className="text-xs font-medium text-slate-500">Step {step + 1} of 4</span>
      </div>
      <div className="profile-wizard-stepper mt-5 flex items-center" aria-label="Profile progress">{STEPS.map((title, index) => <React.Fragment key={title}><button type="button" onClick={() => index <= step && goTo(index)} className="flex min-w-0 items-center gap-2 text-left" aria-label={`Go to ${title}`}><span className={`profile-wizard-step-number flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${index <= step ? "border-sky-600 bg-sky-600 text-white" : "border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-900"}`}>{index < step ? <Check size={12} strokeWidth={3} /> : index + 1}</span><span className={`profile-wizard-step-label hidden truncate text-[11px] sm:inline ${index === step ? "font-semibold text-sky-700 dark:text-sky-300" : "text-slate-500"}`}>{title}</span></button>{index < STEPS.length - 1 && <span className={`profile-wizard-step-line mx-2 h-px min-w-5 flex-1 ${index < step ? "bg-sky-300" : "bg-slate-200 dark:bg-slate-700"}`} />}</React.Fragment>)}</div>
    </header>

    {saveError && <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{saveError}</p>}
    {feedback && <p role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{feedback}</p>}

    {step === 0 && <Section title="About You" description="Let's start with your basic information." className="profile-about-panel"><div className="profile-about-fields grid gap-4 sm:grid-cols-2">
      <Field label="Full Name" required error={errors.fullName}>{input("personalInfo", "fullName", { autoComplete: "name" })}</Field>
      <Field label="Email Address" required error={errors.email}>{input("personalInfo", "email", { type: "email", autoComplete: "email", className: "profile-email-input" })}</Field>
      <Field label="Nationality" required error={errors.citizenshipCountry}>{select("personalInfo", "citizenshipCountry", COUNTRIES)}</Field>
      <Field label="Current Country of Residence" required error={errors.currentCountry}>{select("personalInfo", "currentCountry", COUNTRIES)}</Field>
      <Field label={<>Phone Number <span className="font-normal text-slate-500">(optional)</span></>} >{input("personalInfo", "phoneNumber", { type: "tel", autoComplete: "tel" })}</Field>
    </div>{footerActions}</Section>}

    {step === 1 && <Section title="Academic Background" description="Tell us about your education history and current study status." className="profile-academic-panel"><div className="profile-academic-fields grid gap-x-4 gap-y-2 sm:grid-cols-2">
      <Field label="Current or Highest Degree" required error={errors.currentDegree}>{select("academicBackground", "currentDegree", degreeOptions)}</Field>
      <Field label="Degree Title / Major" required error={errors.degreeTitle}>{input("academicBackground", "degreeTitle")}</Field>
      <Field label="University Name" required error={errors.institution}>{input("academicBackground", "institution")}</Field>
      <Field label="Country of University" required error={errors.institutionCountry}>{select("academicBackground", "institutionCountry", COUNTRIES)}</Field>
      <Field label="Current Study Status" required error={errors.academicStatus}><div className="profile-academic-status flex h-9 items-center gap-6">{[["studying", "Currently studying"], ["graduated", "Graduated"]].map(([value, label]) => <label key={value} className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-200"><input type="radio" name="academicStatus" value={value} checked={academic.academicStatus === value} onChange={(event) => update("academicBackground", "academicStatus", event.target.value)} className="accent-sky-600" />{label}</label>)}</div></Field>
      <Field label="Current Semester / Year" required={academic.academicStatus === "studying"} error={errors.currentYear}>{select("academicBackground", "currentYear", ["1st Semester", "2nd Semester", "3rd Semester", "4th Semester", "5th Semester", "6th Semester", "7th Semester", "8th Semester", "Graduated"])}</Field>
      <Field label="CGPA / Percentage" required error={errors.cgpa}>{input("academicBackground", "cgpa", { type: "number", min: "0", step: "0.01" })}</Field>
      <Field label="Grading Scale / Maximum CGPA" required error={errors.gradingScale}>{select("academicBackground", "gradingScale", gradingScaleOptions)}</Field>
      {academic.gradingScale === "Other" && <Field label="Custom maximum grade" required error={errors.customGradingScale}>{input("academicBackground", "customGradingScale", { type: "number", min: "0", step: "0.01" })}</Field>}
      <Field label="Degree Start Date" required error={errors.degreeStartDate}>{monthInput("degreeStartDate")}</Field>
      {academic.academicStatus === "studying" ? <Field label="Expected Graduation Date" required error={errors.expectedGraduationDate}>{monthInput("expectedGraduationDate")}</Field> : <Field label="Actual Graduation Date" required error={errors.graduationDate}>{monthInput("graduationDate")}</Field>}
    </div><div className="profile-previous-degree mt-3 rounded-md border border-sky-100 bg-sky-50/50 p-3 dark:border-sky-950 dark:bg-sky-950/20"><div className="mb-3 flex items-center gap-2"><ChevronDown size={12} className="text-sky-600" aria-hidden="true" /><div><h3 className="text-xs font-semibold text-slate-800 dark:text-slate-100">Previous Degree <span className="font-normal text-slate-500">(Optional)</span></h3><p className="text-[10px] text-slate-500">Add details if you have completed a previous degree.</p></div></div><div className="grid gap-3 sm:grid-cols-3"><Field label="Degree Title / Major">{input("academicBackground", "previousDegreeTitle", { placeholder: "e.g. Intermediate / A-Level / Associate Degree" })}</Field><Field label="University Name">{input("academicBackground", "previousDegreeInstitution", { placeholder: "e.g. Government College / University" })}</Field><Field label="Graduation Date">{monthInput("previousDegreeDate")}</Field></div></div><div className="profile-achievements mt-3"><Field label="Academic Achievements (Optional)"><Control as="textarea" rows={2} maxLength={500} value={academic.academicAchievements || ""} onChange={(event) => update("academicBackground", "academicAchievements", event.target.value)} placeholder="e.g. Dean's list, scholarships, awards, research projects..." /><span className="profile-character-count">{(academic.academicAchievements || "").length}/500</span></Field></div>{footerActions}</Section>}

    {step === 2 && <Section title="Study Goals" description="Tell us about your preferred degree, field, destination and study preferences." className="profile-study-panel">
      <div className="profile-study-goals-grid">
        <Field label="Intended Degree" required className="profile-goal-degree">
          <span className="profile-goal-icon-control"><GraduationCap size={12} aria-hidden="true" /><Control as="select" value={goals.intendedDegree || "Master's"} onChange={(event) => update("studyPreferences", "intendedDegree", event.target.value)}><option value="Master's">Master's (MSc/MS)</option></Control></span>
        </Field>
        <GroupField label="Preferred Study Fields" required error={errors.fields} className="profile-goal-fields">
          <MultiSelect label="Preferred Study Fields" options={FIELDS} value={selectedFields} onChange={(fields) => { update("studyPreferences", "fields", fields); if (!fields.includes("Other")) update("studyPreferences", "customField", ""); }} placeholder="Search or select fields..." />
          <span className="profile-goal-helper">Select multiple options</span>
        </GroupField>
        <GroupField label="Preferred Countries / Regions" required error={errors.countries} className="profile-goal-destinations">
          <MultiSelect label="Preferred Countries / Regions" options={destinationOptions} value={selectedDestinations} onChange={updateDestinations} placeholder="Search or select destinations..." />
          <span className="profile-goal-helper">Select multiple options</span>
        </GroupField>
        <Field label="Intended Intake" required error={errors.intake} className="profile-goal-intake">
          <span className="profile-goal-icon-control"><CalendarDays size={12} aria-hidden="true" />{select("studyPreferences", "intake", ["Spring", "Fall"])}</span>
        </Field>
        <Field label="Intended Admission Year" required error={errors.admissionYear} className="profile-goal-year">
          <span className="profile-goal-icon-control"><CalendarDays size={12} aria-hidden="true" />{select("studyPreferences", "admissionYear", ["2027", "2028", "2029", "2030"])}</span>
        </Field>
        <GroupField label="Program Type" required error={errors.programPreference} className="profile-goal-program">
          <div className="profile-program-options" role="group" aria-label="Preferred program type">
            {["Coursework", "Research", "Either"].map((program) => <button key={program} type="button" aria-pressed={goals.programPreference === program} className={goals.programPreference === program ? "is-selected" : ""} onClick={() => update("studyPreferences", "programPreference", program)}><span className="profile-program-radio">{goals.programPreference === program && <span />}</span>{program}</button>)}
          </div>
        </GroupField>
        <Field label="Preferred Language of Instruction" required error={errors.languageOfInstruction} className="profile-goal-language">
          <span className="profile-goal-icon-control"><Globe2 size={12} aria-hidden="true" />{select("studyPreferences", "languageOfInstruction", languageOptions)}</span>
        </Field>
        <Field label={<>Preferred Program Duration <span className="font-normal text-slate-500">(Optional)</span></>} className="profile-goal-duration">
          <span className="profile-goal-icon-control"><CalendarDays size={12} aria-hidden="true" />{select("studyPreferences", "preferredProgramDuration", [{ value: "1 year", label: "1 year" }, { value: "1-2 years", label: "1–2 years" }, { value: "2 years", label: "2 years" }, { value: "3+ years", label: "3+ years" }])}</span>
        </Field>
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
        <Field label="English Test Type" className="profile-funding-test-type">
          {select("englishProficiency", "testType", ["IELTS", "TOEFL iBT", "PTE", "Duolingo English Test", "Other", "No Test / Not Taken"], { "aria-label": "English test type (optional)" })}
        </Field>
        <Field label="Expected Test Score (Overall)" error={errors.overallScore} className="profile-funding-score">
          {input("englishProficiency", "overallScore", { type: "number", min: "0", step: "any", placeholder: "e.g. 7.0", "aria-label": "English test score (optional)" })}
        </Field>
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
    </div>
  </div>;
}
