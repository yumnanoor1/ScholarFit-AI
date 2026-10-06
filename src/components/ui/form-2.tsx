"use client"; 

import * as React from "react"; 
import { clsx, type ClassValue } from "clsx"; 
import { twMerge } from "tailwind-merge"; 
import { Slot } from "@radix-ui/react-slot"; 
import { cva, type VariantProps } from "class-variance-authority"; 
import * as LabelPrimitive from "@radix-ui/react-label"; 
import * as SeparatorPrimitive from "@radix-ui/react-separator"; 
import { mergeProfile, type ProfileFieldStatus, type ProfileFieldStatuses, type ProfileSaveProgress, type StudentProfile } from "@/data/profileModel";

function cn(...inputs: ClassValue[]) { 
  return twMerge(clsx(inputs)); 
} 

const buttonVariants = cva( 
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive", 
  { 
    variants: { 
      variant: { 
        default: 
          "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90", 
        destructive: 
          "bg-destructive text-white shadow-xs hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60", 
        outline: 
          "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50", 
        secondary: 
          "bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80", 
        ghost: 
          "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50", 
        link: "text-primary underline-offset-4 hover:underline", 
      }, 
      size: { 
        default: "h-9 px-4 py-2 has-[>svg]:px-3", 
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5", 
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4", 
        icon: "size-9", 
      }, 
    }, 
    defaultVariants: { 
      variant: "default", 
      size: "default", 
    }, 
  } 
); 

function Button({ 
  className, 
  variant, 
  size, 
  asChild = false, 
  ...props 
}: React.ComponentProps<"button"> & 
  VariantProps<typeof buttonVariants> & { 
    asChild?: boolean; 
  }) { 
  const Comp = asChild ? Slot : "button"; 

  return ( 
    <Comp 
      data-slot="button" 
      className={cn(buttonVariants({ variant, size, className }))} 
      {...props} 
    /> 
  ); 
} 

function Input({ className, type, ...props }: React.ComponentProps<"input">) { 
  return ( 
    <input 
      type={type} 
      data-slot="input" 
      className={cn( 
        "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input flex h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm", 
        "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]", 
        "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive", 
        className 
      )} 
      {...props} 
    /> 
  ); 
} 

function Label({ 
  className, 
  ...props 
}: React.ComponentProps<typeof LabelPrimitive.Root>) { 
  return ( 
    <LabelPrimitive.Root 
      data-slot="label" 
      className={cn( 
        "flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50", 
        className 
      )} 
      {...props} 
    /> 
  ); 
} 
Label.displayName = LabelPrimitive.Root.displayName; 

function Separator({ 
  className, 
  orientation = "horizontal", 
  decorative = true, 
  ...props 
}: React.ComponentProps<typeof SeparatorPrimitive.Root>) { 
  return ( 
    <SeparatorPrimitive.Root 
      data-slot="separator-root" 
      decorative={decorative} 
      orientation={orientation} 
      className={cn( 
        "bg-border shrink-0 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px", 
        className 
      )} 
      {...props} 
    /> 
  ); 
} 
Separator.displayName = SeparatorPrimitive.Root.displayName; 

export interface FormLayout01Props {
  onSave: (data: StudentProfile, progress: ProfileSaveProgress) => Promise<boolean | void> | boolean | void;
  onComplete?: () => void;
  onStepChange?: (step: number) => void;
  onGenerateRecommendations?: () => void;
  isSaving?: boolean;
  saveError?: string;
  initialValues?: Partial<StudentProfile>;
  initialStep?: number;
  isProfileComplete?: boolean;
  verificationMode?: boolean;
  requiresReviewConfirmation?: boolean;
  fieldStatuses?: ProfileFieldStatuses;
  finalButtonLabel?: string;
}

const STEP_TITLES = ["Personal", "Academic", "English Test", "Study Preferences"];
const STEP_HEADINGS = ["Personal Information", "Academic Background", "English Test Scores", "Study Preferences"];
const DEGREE_FIELDS = [
  "Computer Science",
  "Software Engineering",
  "Artificial Intelligence",
  "Data Science",
  "Machine Learning",
  "Cybersecurity",
  "Information Technology",
  "Other",
];
const COUNTRY_OPTIONS = [
  "Germany", "Switzerland", "Netherlands", "Sweden", "Finland", "Austria",
  "Hungary", "France", "Italy", "Canada", "Australia", "United States", "United Kingdom", "Other",
];
const REGION_OPTIONS = ["Europe", "North America", "Asia-Pacific"];
const FUNDING_OPTIONS = [
  "Fully Funded", "Mostly Funded", "Partial Scholarship", "Tuition Waiver",
  "Research Assistantship (RA)", "Teaching Assistantship (TA)", "Self-Funded",
];
const INPUT_CLASS = "mt-2";
const SELECT_CLASS = "mt-2 flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-50";
const TEXTAREA_CLASS = "mt-2 min-h-24 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-50";
const FIELD_LABEL_CLASS = "flex flex-wrap items-center gap-2 text-sm font-medium text-slate-800 dark:text-slate-200";
const today = new Date().toISOString().slice(0, 10);
const FIELD_STATUS_KEYS: Record<string, string> = {
  "full-name": "personalInfo.fullName", "email-address": "personalInfo.email", "date-of-birth": "personalInfo.dateOfBirth",
  gender: "personalInfo.gender", citizenship: "personalInfo.citizenshipCountry", "current-country": "personalInfo.currentCountry",
  city: "personalInfo.city", "phone-number": "personalInfo.phoneNumber", "profile-photo": "personalInfo.profilePhoto",
  "current-degree": "academicBackground.currentDegree", "degree-title": "academicBackground.degreeTitle", major: "academicBackground.major",
  institution: "academicBackground.institution", "institution-country": "academicBackground.institutionCountry",
  "academic-status": "academicBackground.academicStatus", "current-year": "academicBackground.currentYear", cgpa: "academicBackground.cgpa",
  "grading-scale": "academicBackground.gradingScale", "expected-graduation": "academicBackground.expectedGraduationDate",
  "custom-grading-scale": "academicBackground.customGradingScale",
  "graduation-date": "academicBackground.graduationDate", transcript: "academicBackground.transcript",
  coursework: "academicBackground.relevantCoursework", "technical-skills": "academicBackground.technicalSkills",
  "programming-languages": "academicBackground.programmingLanguages", certifications: "academicBackground.certifications",
  projects: "academicBackground.projects", "english-test": "englishProficiency.testType",
  "other-test-name": "englishProficiency.otherTestName", "overall-score": "englishProficiency.overallScore",
  "test-listening": "englishProficiency.listening", "test-reading": "englishProficiency.reading",
  "test-writing": "englishProficiency.writing", "test-speaking": "englishProficiency.speaking",
  "test-date": "englishProficiency.testDate", "moi-certificate": "englishProficiency.moiCertificate",
  "add-discipline": "studyPreferences.fields", "custom-field": "studyPreferences.customField",
  "other-country": "studyPreferences.otherCountry", intake: "studyPreferences.intake",
  "study-mode": "studyPreferences.studyMode", "program-preference": "studyPreferences.programPreference",
  "program-duration": "studyPreferences.duration", "max-tuition": "studyPreferences.maxTuitionBudget",
  "max-living": "studyPreferences.maxLivingCostBudget", currency: "studyPreferences.currency",
  "additional-preferences": "studyPreferences.additionalPreferences",
};

const FieldStatusContext = React.createContext<{
  statuses: ProfileFieldStatuses;
  editedFields: Set<string>;
  verificationMode: boolean;
}>({ statuses: {}, editedFields: new Set(), verificationMode: false });

function StatusText({ status }: { status: ProfileFieldStatus }) {
  const labels: Record<ProfileFieldStatus, string> = {
    extracted: "✓ Extracted from CV",
    edited: "✎ Edited",
    missing: "⚠ Not found in CV - please enter manually",
    optional: "Optional",
    account: "✓ From your account",
    "not-applicable": "Not applicable",
  };
  const colors: Record<ProfileFieldStatus, string> = {
    extracted: "text-emerald-700 dark:text-emerald-300",
    edited: "text-sky-700 dark:text-sky-300",
    missing: "text-amber-700 dark:text-amber-300",
    optional: "text-slate-500 dark:text-slate-400",
    account: "text-sky-700 dark:text-sky-300",
    "not-applicable": "text-slate-500 dark:text-slate-400",
  };
  return <span className={`text-xs font-normal ${colors[status]}`} role={status === "missing" ? "alert" : undefined}>{labels[status]}</span>;
}

function FieldLabel({ htmlFor, children, optional = false }: { htmlFor: string; children: React.ReactNode; optional?: boolean }) {
  const { statuses, editedFields, verificationMode } = React.useContext(FieldStatusContext);
  const key = FIELD_STATUS_KEYS[htmlFor];
  const status = key && editedFields.has(key) ? "edited" : key ? statuses[key] : undefined;
  return (
    <Label htmlFor={htmlFor} className={FIELD_LABEL_CLASS}>
      {children}
      {verificationMode && status ? <StatusText status={status} /> : <span className="text-xs font-normal text-slate-500 dark:text-slate-400">{optional ? "Optional" : "Required"}</span>}
    </Label>
  );
}

function MultiSelectField({
  title,
  options,
  selected,
  onToggle,
  statusKey,
  required = true,
}: {
  title: string;
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
  statusKey?: string;
  required?: boolean;
}) {
  const { statuses, editedFields, verificationMode } = React.useContext(FieldStatusContext);
  const status = statusKey && editedFields.has(statusKey) ? "edited" : statusKey ? statuses[statusKey] : undefined;
  return (
    <fieldset>
      <legend className={FIELD_LABEL_CLASS}>{title} {verificationMode && status ? <StatusText status={status} /> : <span className="text-xs font-normal text-slate-500 dark:text-slate-400">{required ? "Required; select all that apply" : "Optional alternative; select all that apply"}</span>}</legend>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {options.map((option) => (
          <label key={option} className="flex min-h-10 items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:border-sky-500 dark:border-slate-700 dark:text-slate-200">
            <input
              type="checkbox"
              checked={selected.includes(option)}
              onChange={() => onToggle(option)}
              className="size-4 accent-sky-700"
            />
            {option}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export default function FormLayout01({
  onSave,
  onComplete,
  onStepChange,
  onGenerateRecommendations,
  isSaving = false,
  saveError = "",
  initialValues,
  initialStep = 0,
  isProfileComplete = false,
  verificationMode = false,
  requiresReviewConfirmation = false,
  fieldStatuses = {},
  finalButtonLabel,
}: FormLayout01Props) {
  const [activeStep, setActiveStep] = React.useState(Math.min(Math.max(initialStep, 0), 3));
  const [formValues, setFormValues] = React.useState(() => mergeProfile(initialValues));
  const [isComplete, setIsComplete] = React.useState(isProfileComplete);
  const [localError, setLocalError] = React.useState("");
  const [disciplineToAdd, setDisciplineToAdd] = React.useState("");
  const [reviewConfirmed, setReviewConfirmed] = React.useState(false);
  const [editedFields, setEditedFields] = React.useState<Set<string>>(() => new Set());
  const [stepValid, setStepValid] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);

  const updateSection = (section: keyof StudentProfile, field: string, value: unknown) => {
    setFormValues((current) => ({
      ...current,
      [section]: { ...current[section], [field]: value },
    } as StudentProfile));
    setEditedFields((current) => new Set(current).add(`${section}.${field}`));
    setLocalError("");
  };

  const togglePreference = (field: "fields" | "countries" | "regions" | "fundingPreferences", value: string) => {
    const current = formValues.studyPreferences[field];
    updateSection("studyPreferences", field, current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value]);
  };

  const handleFileChange = (
    section: "personalInfo" | "academicBackground" | "englishProficiency",
    field: "profilePhoto" | "transcript" | "moiCertificate",
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    updateSection(section, field, event.currentTarget.files?.[0] || null);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLocalError("");

    if (activeStep === 3) {
      const preferences = formValues.studyPreferences;
      if (preferences.fields.length === 0) {
        setLocalError("Choose at least one preferred Master's field.");
        return;
      }
      if (preferences.fields.includes("Other") && !preferences.customField.trim()) {
        setLocalError("Enter the additional field you want to study.");
        return;
      }
      if (preferences.countries.length === 0 && preferences.regions.length === 0) {
        setLocalError("Choose at least one country or region.");
        return;
      }
      if (preferences.countries.includes("Other") && !preferences.otherCountry.trim()) {
        setLocalError("Enter the additional country you prefer.");
        return;
      }
      if (preferences.fundingPreferences.length === 0) {
        setLocalError("Choose at least one funding preference.");
        return;
      }
    }

    if (activeStep === 3 && requiresReviewConfirmation && !reviewConfirmed) {
      setLocalError("Confirm that you have reviewed your profile before saving.");
      return;
    }

    const complete = activeStep === 3;
    try {
      const savedStatuses = { ...fieldStatuses };
      editedFields.forEach((path) => { savedStatuses[path] = "edited"; });
      const saved = await onSave(formValues, {
        step: activeStep,
        complete,
        source: verificationMode ? "cv" : "manual",
        fieldStatuses: savedStatuses,
      });
      if (saved === false) return;
      if (complete) {
        if (onComplete) onComplete();
        else setIsComplete(true);
      } else {
        const nextStep = activeStep + 1;
        setActiveStep(nextStep);
        onStepChange?.(nextStep);
      }
    } catch {
      setLocalError("We could not save this step. Please try again.");
    }
  };

  const addDiscipline = () => {
    const discipline = disciplineToAdd.trim();
    if (!discipline || formValues.studyPreferences.fields.includes(discipline)) return;
    togglePreference("fields", discipline);
    setDisciplineToAdd("");
  };

  const completionSummary = isComplete;
  const error = localError || saveError;
  const preferences = formValues.studyPreferences;
  const preferenceSelectionsValid = preferences.fields.length > 0 &&
    (!preferences.fields.includes("Other") || Boolean(preferences.customField.trim())) &&
    (preferences.countries.length > 0 || preferences.regions.length > 0) &&
    (!preferences.countries.includes("Other") || Boolean(preferences.otherCountry.trim())) &&
    preferences.fundingPreferences.length > 0;
  const focusFirstMissingField = () => {
    const form = formRef.current;
    let firstInvalid = form?.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | HTMLButtonElement>(":invalid") || null;
    if (!firstInvalid && activeStep === 3) {
      firstInvalid = form?.querySelector<HTMLInputElement>("section input[type='checkbox']") || null;
    }
    if (firstInvalid) {
      firstInvalid.focus();
      firstInvalid.scrollIntoView({ behavior: "smooth", block: "center" });
      firstInvalid.reportValidity();
    }
  };
  const handleContinueClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    const form = formRef.current;
    const firstInvalid = form?.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | HTMLButtonElement>(":invalid") || null;
    const reviewMissing = requiresReviewConfirmation && activeStep === 3 && !reviewConfirmed;
    if (firstInvalid || (activeStep === 3 && !preferenceSelectionsValid) || reviewMissing) {
      event.preventDefault();
      setLocalError("Complete the highlighted required fields before continuing.");
      if (firstInvalid) focusFirstMissingField();
    }
  };

  React.useEffect(() => {
    const browserFieldsValid = formRef.current?.checkValidity() ?? false;
    setStepValid(browserFieldsValid && (activeStep !== 3 || preferenceSelectionsValid));
  }, [activeStep, formValues, preferenceSelectionsValid, reviewConfirmed]);

  return (
    <FieldStatusContext.Provider value={{ statuses: fieldStatuses, editedFields, verificationMode }}>
    <div className="flex items-center justify-center p-4 sm:p-6 md:p-10">
      <div className="w-full max-w-4xl rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-7 md:p-9">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-sky-700 dark:text-sky-300">FitScholar AI / Master's Profile</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950 dark:text-slate-50">{completionSummary ? "Profile Complete" : verificationMode ? "Review Your Information" : "Build your Master's profile"}</h2>
          </div>
          {!completionSummary && <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">Step {activeStep + 1} of 4</span>}
        </div>

        {!completionSummary && (
          <>
            <ol aria-label="Profile setup progress" className="mt-7 grid grid-cols-4 gap-2">
              {STEP_TITLES.map((title, index) => (
                <li key={title} aria-label={title} aria-current={activeStep === index ? "step" : undefined} className="min-w-0">
                  <div className={`mb-2 h-1 rounded-full ${index <= activeStep ? "bg-sky-700 dark:bg-sky-400" : "bg-slate-200 dark:bg-slate-700"}`} />
                  <span className={`block text-xs ${index === activeStep ? "font-semibold text-slate-900 dark:text-slate-100" : "text-slate-500 dark:text-slate-400"}`}>
                    <span className="hidden sm:inline">{title}</span>
                    <span className="sm:hidden">{index + 1}</span>
                  </span>
                </li>
              ))}
            </ol>

            <div className="mt-7">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{STEP_HEADINGS[activeStep]}</h3>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-400">
                {verificationMode
                  ? "We've extracted information from your CV. Review and verify it before continuing; you can edit anything incorrect or add information that was not found."
                  : activeStep === 0 && "Tell us about yourself so we can personalize your Master's study-abroad recommendations."}
                {!verificationMode && activeStep === 1 && "Provide your academic information to help us determine which Master's programs and scholarships you may be eligible for."}
                {!verificationMode && activeStep === 2 && "Add your English proficiency information to help us identify Master's programs and scholarships that match your language requirements."}
                {!verificationMode && activeStep === 3 && "Tell us what you want from your Master's study-abroad experience. FitScholar AI will use these preferences to generate personalized recommendations."}
              </p>
            </div>

            <form ref={formRef} onSubmit={handleSubmit} className="mt-6">
              {activeStep === 0 && (
                <section className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-6">
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="full-name">Full name</FieldLabel>
                    <Input id="full-name" autoComplete="name" required value={formValues.personalInfo.fullName} onChange={(event) => updateSection("personalInfo", "fullName", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="email-address">Email address</FieldLabel>
                    <Input id="email-address" type="email" autoComplete="email" required value={formValues.personalInfo.email} onChange={(event) => updateSection("personalInfo", "email", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="date-of-birth">Date of birth</FieldLabel>
                    <Input id="date-of-birth" type="date" max={today} required value={formValues.personalInfo.dateOfBirth} onChange={(event) => updateSection("personalInfo", "dateOfBirth", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="gender">Gender</FieldLabel>
                    <select id="gender" required value={formValues.personalInfo.gender} onChange={(event) => updateSection("personalInfo", "gender", event.currentTarget.value)} className={SELECT_CLASS}>
                      <option value="">Select gender</option><option>Woman</option><option>Man</option><option>Non-binary</option><option>Prefer not to say</option><option>Self-describe</option>
                    </select>
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="citizenship">Country of citizenship</FieldLabel>
                    <Input id="citizenship" autoComplete="country-name" required value={formValues.personalInfo.citizenshipCountry} onChange={(event) => updateSection("personalInfo", "citizenshipCountry", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="current-country">Current country</FieldLabel>
                    <Input id="current-country" autoComplete="country-name" required value={formValues.personalInfo.currentCountry} onChange={(event) => updateSection("personalInfo", "currentCountry", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="city">City</FieldLabel>
                    <Input id="city" autoComplete="address-level2" required value={formValues.personalInfo.city} onChange={(event) => updateSection("personalInfo", "city", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="phone-number">Phone number</FieldLabel>
                    <Input id="phone-number" type="tel" autoComplete="tel" minLength={7} maxLength={20} title="Enter a phone number between 7 and 20 characters" required value={formValues.personalInfo.phoneNumber} onChange={(event) => updateSection("personalInfo", "phoneNumber", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="profile-photo" optional>Profile photo</FieldLabel>
                    <Input id="profile-photo" type="file" accept="image/*" onChange={(event) => handleFileChange("personalInfo", "profilePhoto", event)} className={INPUT_CLASS} />
                    {formValues.personalInfo.profilePhoto && <p className="mt-1 text-xs text-slate-500">{formValues.personalInfo.profilePhoto.name}</p>}
                  </div>
                </section>
              )}

              {activeStep === 1 && (
                <section className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-6">
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="current-degree">Current degree</FieldLabel>
                    <select id="current-degree" required value={formValues.academicBackground.currentDegree} onChange={(event) => updateSection("academicBackground", "currentDegree", event.currentTarget.value)} className={SELECT_CLASS}>
                      <option value="">Select degree</option><option>Bachelor&apos;s degree</option><option>Equivalent degree</option><option>Other</option>
                    </select>
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="degree-title">Degree title</FieldLabel>
                    <Input id="degree-title" required value={formValues.academicBackground.degreeTitle} onChange={(event) => updateSection("academicBackground", "degreeTitle", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="major">Major / field of study</FieldLabel>
                    <Input id="major" required value={formValues.academicBackground.major} onChange={(event) => updateSection("academicBackground", "major", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="institution">University / institution</FieldLabel>
                    <Input id="institution" required value={formValues.academicBackground.institution} onChange={(event) => updateSection("academicBackground", "institution", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="institution-country">Country of institution</FieldLabel>
                    <Input id="institution-country" required value={formValues.academicBackground.institutionCountry} onChange={(event) => updateSection("academicBackground", "institutionCountry", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="academic-status">Study status</FieldLabel>
                    <select id="academic-status" required value={formValues.academicBackground.academicStatus} onChange={(event) => updateSection("academicBackground", "academicStatus", event.currentTarget.value)} className={SELECT_CLASS}>
                      <option value="">Select status</option><option value="studying">Currently studying</option><option value="graduated">Already graduated</option>
                    </select>
                  </div>
                  {formValues.academicBackground.academicStatus === "studying" ? (
                    <>
                      <div className="col-span-full sm:col-span-3">
                        <FieldLabel htmlFor="current-year">Current semester / year</FieldLabel>
                        <Input id="current-year" required value={formValues.academicBackground.currentYear} onChange={(event) => updateSection("academicBackground", "currentYear", event.currentTarget.value)} className={INPUT_CLASS} />
                      </div>
                      <div className="col-span-full sm:col-span-3">
                        <FieldLabel htmlFor="expected-graduation">Expected graduation date</FieldLabel>
                        <Input id="expected-graduation" type="date" min={today} required value={formValues.academicBackground.expectedGraduationDate} onChange={(event) => updateSection("academicBackground", "expectedGraduationDate", event.currentTarget.value)} className={INPUT_CLASS} />
                      </div>
                    </>
                  ) : formValues.academicBackground.academicStatus === "graduated" ? (
                    <div className="col-span-full sm:col-span-3">
                      <FieldLabel htmlFor="graduation-date">Graduation date</FieldLabel>
                      <Input id="graduation-date" type="date" max={today} required value={formValues.academicBackground.graduationDate} onChange={(event) => updateSection("academicBackground", "graduationDate", event.currentTarget.value)} className={INPUT_CLASS} />
                    </div>
                  ) : null}
                  <div className="col-span-full sm:col-span-2">
                    <FieldLabel htmlFor="grading-scale">Grading scale</FieldLabel>
                    <select id="grading-scale" required value={formValues.academicBackground.gradingScale} onChange={(event) => updateSection("academicBackground", "gradingScale", event.currentTarget.value)} className={SELECT_CLASS}>
                      <option value="">Select scale</option><option value="4.0">4.0</option><option value="5.0">5.0</option><option value="10.0">10.0</option><option value="100">100</option><option value="Other">Other</option>
                    </select>
                  </div>
                  {formValues.academicBackground.gradingScale === "Other" && (
                    <div className="col-span-full sm:col-span-2">
                      <FieldLabel htmlFor="custom-grading-scale">Maximum grade on scale</FieldLabel>
                      <Input id="custom-grading-scale" type="number" min="0.1" step="any" required value={formValues.academicBackground.customGradingScale} onChange={(event) => updateSection("academicBackground", "customGradingScale", event.currentTarget.value)} className={INPUT_CLASS} />
                    </div>
                  )}
                  <div className="col-span-full sm:col-span-2">
                    <FieldLabel htmlFor="cgpa">Current CGPA / GPA</FieldLabel>
                    <Input id="cgpa" type="number" min="0" max={formValues.academicBackground.gradingScale === "Other" ? formValues.academicBackground.customGradingScale : formValues.academicBackground.gradingScale || undefined} step="any" required value={formValues.academicBackground.cgpa} onChange={(event) => updateSection("academicBackground", "cgpa", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-2">
                    <FieldLabel htmlFor="transcript" optional>Academic transcript</FieldLabel>
                    <Input id="transcript" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(event) => handleFileChange("academicBackground", "transcript", event)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full">
                    <FieldLabel htmlFor="coursework">Relevant coursework</FieldLabel>
                    <Input id="coursework" placeholder="Separate subjects with commas" required value={formValues.academicBackground.relevantCoursework} onChange={(event) => updateSection("academicBackground", "relevantCoursework", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="technical-skills">Technical skills</FieldLabel>
                    <Input id="technical-skills" placeholder="Separate skills with commas" required value={formValues.academicBackground.technicalSkills} onChange={(event) => updateSection("academicBackground", "technicalSkills", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="programming-languages">Programming languages</FieldLabel>
                    <Input id="programming-languages" placeholder="e.g. Python, Java" required value={formValues.academicBackground.programmingLanguages} onChange={(event) => updateSection("academicBackground", "programmingLanguages", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="certifications" optional>Certifications</FieldLabel>
                    <Input id="certifications" value={formValues.academicBackground.certifications} onChange={(event) => updateSection("academicBackground", "certifications", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="projects" optional>Projects / academic experience</FieldLabel>
                    <Input id="projects" value={formValues.academicBackground.projects} onChange={(event) => updateSection("academicBackground", "projects", event.currentTarget.value)} className={INPUT_CLASS} />
                  </div>
                </section>
              )}

              {activeStep === 2 && (
                <section className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-6">
                  <div className="col-span-full sm:col-span-3">
                    <FieldLabel htmlFor="english-test">English test</FieldLabel>
                    <select id="english-test" required value={formValues.englishProficiency.testType} onChange={(event) => updateSection("englishProficiency", "testType", event.currentTarget.value)} className={SELECT_CLASS}>
                      <option value="">Select test</option><option>IELTS</option><option>TOEFL iBT</option><option>PTE</option><option>Duolingo English Test</option><option>Other</option><option>No Test / Not Taken</option>
                    </select>
                  </div>
                  {formValues.englishProficiency.testType !== "No Test / Not Taken" && (
                    <>
                      {formValues.englishProficiency.testType === "Other" && (
                        <div className="col-span-full sm:col-span-3">
                          <FieldLabel htmlFor="other-test-name">Test name</FieldLabel>
                          <Input id="other-test-name" required value={formValues.englishProficiency.otherTestName} onChange={(event) => updateSection("englishProficiency", "otherTestName", event.currentTarget.value)} className={INPUT_CLASS} />
                        </div>
                      )}
                      <div className="col-span-full sm:col-span-3">
                        <FieldLabel htmlFor="overall-score">{formValues.englishProficiency.testType === "IELTS" ? "Overall band" : "Overall score"}</FieldLabel>
                        <Input id="overall-score" type="number" min={formValues.englishProficiency.testType === "PTE" || formValues.englishProficiency.testType === "Duolingo English Test" ? 10 : 0} max={formValues.englishProficiency.testType === "IELTS" ? 9 : formValues.englishProficiency.testType === "TOEFL iBT" ? 120 : formValues.englishProficiency.testType === "PTE" ? 90 : formValues.englishProficiency.testType === "Duolingo English Test" ? 160 : undefined} step={formValues.englishProficiency.testType === "IELTS" ? 0.5 : 1} required value={formValues.englishProficiency.overallScore} onChange={(event) => updateSection("englishProficiency", "overallScore", event.currentTarget.value)} className={INPUT_CLASS} />
                      </div>
                      {(formValues.englishProficiency.testType === "IELTS" || formValues.englishProficiency.testType === "TOEFL iBT" || formValues.englishProficiency.testType === "PTE") && [
                        ["listening", "Listening"], ["reading", "Reading"], ["writing", "Writing"], ["speaking", "Speaking"],
                      ].map(([field, label]) => (
                        <div key={field} className="col-span-full sm:col-span-3">
                          <FieldLabel htmlFor={`test-${field}`}>{label}</FieldLabel>
                          <Input id={`test-${field}`} type="number" min={formValues.englishProficiency.testType === "PTE" ? 10 : 0} max={formValues.englishProficiency.testType === "TOEFL iBT" ? 30 : formValues.englishProficiency.testType === "IELTS" ? 9 : 90} step={formValues.englishProficiency.testType === "IELTS" ? 0.5 : 1} required value={formValues.englishProficiency[field as "listening" | "reading" | "writing" | "speaking"]} onChange={(event) => updateSection("englishProficiency", field, event.currentTarget.value)} className={INPUT_CLASS} />
                        </div>
                      ))}
                      <div className="col-span-full sm:col-span-3">
                        <FieldLabel htmlFor="test-date">Test date</FieldLabel>
                        <Input id="test-date" type="date" max={today} required value={formValues.englishProficiency.testDate} onChange={(event) => updateSection("englishProficiency", "testDate", event.currentTarget.value)} className={INPUT_CLASS} />
                      </div>
                    </>
                  )}
                  <fieldset className="col-span-full">
                    <legend className={FIELD_LABEL_CLASS}>Was your Bachelor&apos;s degree taught in English? {verificationMode && fieldStatuses["englishProficiency.mediumOfInstruction"] ? <StatusText status={editedFields.has("englishProficiency.mediumOfInstruction") ? "edited" : fieldStatuses["englishProficiency.mediumOfInstruction"]} /> : <span className="text-xs font-normal text-slate-500">Required</span>}</legend>
                    <div className="mt-3 flex gap-5">
                      {["Yes", "No"].map((answer) => (
                        <label key={answer} className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                          <input type="radio" name="mediumOfInstruction" required checked={formValues.englishProficiency.mediumOfInstruction === answer} onChange={() => updateSection("englishProficiency", "mediumOfInstruction", answer)} className="size-4 accent-sky-700" />
                          {answer}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  {formValues.englishProficiency.mediumOfInstruction === "Yes" && (
                    <div className="col-span-full sm:col-span-3">
                      <FieldLabel htmlFor="moi-certificate" optional>Medium of Instruction (MOI) certificate</FieldLabel>
                      <Input id="moi-certificate" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(event) => handleFileChange("englishProficiency", "moiCertificate", event)} className={INPUT_CLASS} />
                    </div>
                  )}
                </section>
              )}

              {activeStep === 3 && (
                <section className="space-y-6">
                  <MultiSelectField title="Preferred Master's fields" options={DEGREE_FIELDS} selected={formValues.studyPreferences.fields} onToggle={(value) => togglePreference("fields", value)} statusKey="studyPreferences.fields" />
                  {formValues.studyPreferences.fields.includes("Other") && (
                    <div>
                      <FieldLabel htmlFor="custom-field">Other discipline</FieldLabel>
                      <Input id="custom-field" required value={formValues.studyPreferences.customField} onChange={(event) => updateSection("studyPreferences", "customField", event.currentTarget.value)} className={INPUT_CLASS} />
                    </div>
                  )}
                  {formValues.studyPreferences.fields.some((field) => !DEGREE_FIELDS.includes(field)) && (
                    <ul aria-label="Additional selected disciplines" className="flex flex-wrap gap-2">
                      {formValues.studyPreferences.fields.filter((field) => !DEGREE_FIELDS.includes(field)).map((field) => (
                        <li key={field}>
                          <button type="button" onClick={() => togglePreference("fields", field)} className="rounded-full border border-sky-200 px-3 py-1 text-xs text-sky-800 hover:bg-sky-50 dark:border-sky-800 dark:text-sky-200 dark:hover:bg-slate-800">
                            Remove {field}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-6">
                    <div className="sm:col-span-4">
                      <Label htmlFor="add-discipline" className={FIELD_LABEL_CLASS}>Search or add another discipline <span className="text-xs font-normal text-slate-500">Optional</span></Label>
                      <Input id="add-discipline" list="discipline-options" value={disciplineToAdd} onChange={(event) => setDisciplineToAdd(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addDiscipline(); } }} className={INPUT_CLASS} />
                      <datalist id="discipline-options">{DEGREE_FIELDS.filter((field) => field !== "Other").map((field) => <option key={field} value={field} />)}</datalist>
                    </div>
                    <div className="flex items-end sm:col-span-2">
                      <Button type="button" variant="outline" onClick={addDiscipline} className="w-full">Add field</Button>
                    </div>
                  </div>
                  <MultiSelectField title="Preferred countries" options={COUNTRY_OPTIONS} selected={formValues.studyPreferences.countries} onToggle={(value) => togglePreference("countries", value)} statusKey="studyPreferences.countries" required={formValues.studyPreferences.regions.length === 0} />
                  {formValues.studyPreferences.countries.includes("Other") && (
                    <div>
                      <FieldLabel htmlFor="other-country">Other preferred country</FieldLabel>
                      <Input id="other-country" required value={formValues.studyPreferences.otherCountry} onChange={(event) => updateSection("studyPreferences", "otherCountry", event.currentTarget.value)} className={INPUT_CLASS} />
                    </div>
                  )}
                  <MultiSelectField title="Or choose a region" options={REGION_OPTIONS} selected={formValues.studyPreferences.regions} onToggle={(value) => togglePreference("regions", value)} statusKey="studyPreferences.regions" required={formValues.studyPreferences.countries.length === 0} />
                  <div className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-2">
                    <div>
                      <FieldLabel htmlFor="intake">Preferred intake</FieldLabel>
                      <select id="intake" required value={formValues.studyPreferences.intake} onChange={(event) => updateSection("studyPreferences", "intake", event.currentTarget.value)} className={SELECT_CLASS}><option value="">Select intake</option><option>Spring</option><option>Fall</option><option>Any</option></select>
                    </div>
                    <div>
                      <FieldLabel htmlFor="study-mode">Study mode</FieldLabel>
                      <select id="study-mode" required value={formValues.studyPreferences.studyMode} onChange={(event) => updateSection("studyPreferences", "studyMode", event.currentTarget.value)} className={SELECT_CLASS}><option value="">Select mode</option><option>On Campus</option><option>Hybrid</option><option>Online</option><option>Flexible</option></select>
                    </div>
                    <div>
                      <FieldLabel htmlFor="program-preference">Program preference</FieldLabel>
                      <select id="program-preference" required value={formValues.studyPreferences.programPreference} onChange={(event) => updateSection("studyPreferences", "programPreference", event.currentTarget.value)} className={SELECT_CLASS}><option value="">Select preference</option><option>Coursework Focused</option><option>Research Focused</option><option>Either</option></select>
                    </div>
                    <div>
                      <FieldLabel htmlFor="program-duration">Preferred program duration</FieldLabel>
                      <select id="program-duration" required value={formValues.studyPreferences.duration} onChange={(event) => updateSection("studyPreferences", "duration", event.currentTarget.value)} className={SELECT_CLASS}><option value="">Select duration</option><option>1 Year</option><option>1.5 Years</option><option>2 Years</option><option>Flexible</option></select>
                    </div>
                  </div>
                  <MultiSelectField title="Funding preference" options={FUNDING_OPTIONS} selected={formValues.studyPreferences.fundingPreferences} onToggle={(value) => togglePreference("fundingPreferences", value)} statusKey="studyPreferences.fundingPreferences" />
                  <div className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-3">
                    <div>
                      <FieldLabel htmlFor="max-tuition">Maximum tuition budget</FieldLabel>
                      <Input id="max-tuition" type="number" min="0" step="100" required value={formValues.studyPreferences.maxTuitionBudget} onChange={(event) => updateSection("studyPreferences", "maxTuitionBudget", event.currentTarget.value)} className={INPUT_CLASS} />
                    </div>
                    <div>
                      <FieldLabel htmlFor="max-living">Maximum living cost budget</FieldLabel>
                      <Input id="max-living" type="number" min="0" step="100" required value={formValues.studyPreferences.maxLivingCostBudget} onChange={(event) => updateSection("studyPreferences", "maxLivingCostBudget", event.currentTarget.value)} className={INPUT_CLASS} />
                    </div>
                    <div>
                      <FieldLabel htmlFor="currency">Currency</FieldLabel>
                      <select id="currency" required value={formValues.studyPreferences.currency} onChange={(event) => updateSection("studyPreferences", "currency", event.currentTarget.value)} className={SELECT_CLASS}><option value="">Select currency</option><option>USD</option><option>EUR</option><option>GBP</option><option>CAD</option><option>AUD</option></select>
                    </div>
                  </div>
                  <div>
                    <FieldLabel htmlFor="additional-preferences" optional>Anything else you&apos;re looking for?</FieldLabel>
                    <textarea id="additional-preferences" value={formValues.studyPreferences.additionalPreferences} onChange={(event) => updateSection("studyPreferences", "additionalPreferences", event.currentTarget.value)} placeholder="For example: English-taught Master's programs, funding, low tuition fees, or programs without GRE requirements." className={TEXTAREA_CLASS} />
                  </div>
                </section>
              )}

              {verificationMode && requiresReviewConfirmation && activeStep === 3 && (
                <label className="mt-6 flex items-start gap-3 rounded-md border border-slate-200 p-4 text-sm text-slate-700 dark:border-slate-700 dark:text-slate-200">
                  <input type="checkbox" required checked={reviewConfirmed} onChange={(event) => setReviewConfirmed(event.currentTarget.checked)} className="mt-0.5 size-4 accent-sky-700" />
                  <span>I have reviewed and verified my profile information.</span>
                </label>
              )}

              <Separator className="my-6" />
              {error && <p role="alert" className="mb-4 text-sm text-red-700 dark:text-red-300">{error}</p>}
              {verificationMode && requiresReviewConfirmation && activeStep === 3 && !stepValid && (
                <p role="status" className="mb-4 flex flex-wrap items-center gap-1 text-sm text-amber-700 dark:text-amber-300">
                  Complete all required fields and confirm your review to enable profile confirmation.
                  <button type="button" onClick={focusFirstMissingField} className="font-semibold underline underline-offset-2">Jump to first missing field</button>
                </p>
              )}
              <div className="flex justify-between gap-3">
                <Button type="button" variant="outline" disabled={activeStep === 0 || isSaving} onClick={() => { const previousStep = activeStep - 1; setActiveStep(previousStep); onStepChange?.(previousStep); setLocalError(""); }}>
                  Back
                </Button>
                <Button type="submit" onClick={handleContinueClick} disabled={isSaving || (verificationMode && requiresReviewConfirmation && activeStep === 3 && !stepValid)}>
                  {isSaving ? "Saving progress..." : activeStep === 3 ? finalButtonLabel || (verificationMode ? "Confirm & Save Profile" : "Save & Generate Recommendations") : "Submit & Continue"}
                </Button>
              </div>
            </form>
          </>
        )}

        {completionSummary && (
          <section className="mt-8" aria-labelledby="profile-complete-heading">
            <Separator className="mb-7" />
            <h3 id="profile-complete-heading" className="text-xl font-semibold text-slate-950 dark:text-slate-50">Your Master's profile is ready!</h3>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-400">FitScholar AI can now analyze your profile and match you with relevant Master's programs and scholarships.</p>
            <ul className="mt-4 grid grid-cols-1 gap-2 text-sm text-slate-700 sm:grid-cols-2 dark:text-slate-300">
              {["Academic background", "English proficiency", "Study preferences", "Funding requirements", "Eligibility"].map((item) => (
                <li key={item} className="flex items-center gap-2"><span aria-hidden="true" className="size-1.5 rounded-full bg-sky-700 dark:bg-sky-400" />{item}</li>
              ))}
            </ul>
            <div className="mt-7 flex flex-wrap justify-end gap-3">
              <Button type="button" variant="outline" onClick={() => { setIsComplete(false); setActiveStep(0); setReviewConfirmed(false); onStepChange?.(0); }}>Review Profile</Button>
              <Button type="button" onClick={onGenerateRecommendations}>Generate My Recommendations</Button>
            </div>
          </section>
        )}
      </div>
    </div>
    </FieldStatusContext.Provider>
  );
}