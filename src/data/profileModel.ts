export interface PersonalInformation {
  fullName: string;
  email: string;
  dateOfBirth: string;
  gender: string;
  citizenshipCountry: string;
  currentCountry: string;
  city: string;
  phoneNumber: string;
  profilePhoto: File | null;
}

export interface AcademicBackground {
  currentDegree: string;
  degreeTitle: string;
  major: string;
  institution: string;
  institutionCountry: string;
  academicStatus: "" | "studying" | "graduated";
  currentYear: string;
  cgpa: string;
  gradingScale: string;
  customGradingScale: string;
  expectedGraduationDate: string;
  graduationDate: string;
  transcript: File | null;
  relevantCoursework: string;
  technicalSkills: string;
  programmingLanguages: string;
  certifications: string;
  projects: string;
}

export type EnglishTestType = "" | "IELTS" | "TOEFL iBT" | "PTE" | "Duolingo English Test" | "Other" | "No Test / Not Taken";

export interface EnglishProficiency {
  testType: EnglishTestType;
  otherTestName: string;
  overallScore: string;
  listening: string;
  reading: string;
  writing: string;
  speaking: string;
  testDate: string;
  mediumOfInstruction: "Yes" | "No" | "";
  moiCertificate: File | null;
}

export interface StudyPreferences {
  fields: string[];
  customField: string;
  countries: string[];
  regions: string[];
  otherCountry: string;
  intake: string;
  studyMode: string;
  programPreference: string;
  fundingPreferences: string[];
  maxTuitionBudget: string;
  maxLivingCostBudget: string;
  currency: string;
  duration: string;
  additionalPreferences: string;
}

export interface StudentProfile {
  personalInfo: PersonalInformation;
  academicBackground: AcademicBackground;
  englishProficiency: EnglishProficiency;
  studyPreferences: StudyPreferences;
}

export type ProfileFieldStatus = "extracted" | "edited" | "missing" | "optional" | "account" | "not-applicable";
export type ProfileFieldStatuses = Record<string, ProfileFieldStatus>;

export interface ProfileSaveProgress {
  step: number;
  complete: boolean;
  source?: "manual" | "cv";
  fieldStatuses?: ProfileFieldStatuses;
}

export const EMPTY_PROFILE: StudentProfile = {
  personalInfo: {
    fullName: "", email: "", dateOfBirth: "", gender: "", citizenshipCountry: "",
    currentCountry: "", city: "", phoneNumber: "", profilePhoto: null,
  },
  academicBackground: {
    currentDegree: "", degreeTitle: "", major: "", institution: "",
    institutionCountry: "", academicStatus: "", currentYear: "", cgpa: "",
    gradingScale: "", customGradingScale: "", expectedGraduationDate: "", graduationDate: "", transcript: null,
    relevantCoursework: "", technicalSkills: "", programmingLanguages: "", certifications: "", projects: "",
  },
  englishProficiency: {
    testType: "", otherTestName: "", overallScore: "", listening: "", reading: "",
    writing: "", speaking: "", testDate: "", mediumOfInstruction: "", moiCertificate: null,
  },
  studyPreferences: {
    fields: [], customField: "", countries: [], regions: [], otherCountry: "", intake: "",
    studyMode: "", programPreference: "", fundingPreferences: [],
    maxTuitionBudget: "", maxLivingCostBudget: "", currency: "", duration: "",
    additionalPreferences: "",
  },
};

export function mergeProfile(values: Partial<StudentProfile> = {}): StudentProfile {
  return {
    personalInfo: { ...EMPTY_PROFILE.personalInfo, ...values.personalInfo },
    academicBackground: { ...EMPTY_PROFILE.academicBackground, ...values.academicBackground },
    englishProficiency: { ...EMPTY_PROFILE.englishProficiency, ...values.englishProficiency },
    studyPreferences: { ...EMPTY_PROFILE.studyPreferences, ...values.studyPreferences },
  };
}