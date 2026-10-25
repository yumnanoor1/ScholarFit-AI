const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

// ---------------------------------------------------------------------------
// Field Mapping Helper
// ---------------------------------------------------------------------------

/**
 * Maps a backend ProgramResponse + UniversityResponse to the shape
 * expected by Universities.jsx program cards.
 *
 * Backend program fields:
 *   id, university_id, name, degree_level, field_of_study, duration_months,
 *   tuition_usd_per_year, living_cost_usd_per_year, min_cgpa, min_ielts,
 *   min_toefl, required_degree, application_deadline, description, source_url
 *
 * Backend university fields:
 *   id, name, country, city, ranking, website, description
 */
export function mapProgramToFrontend(program, university) {
  const tuition =
    program.tuition_usd_per_year != null
      ? `$${Number(program.tuition_usd_per_year).toLocaleString()} / year`
      : null;

  let englishReq = null;
  if (program.min_ielts != null && program.min_toefl != null) {
    englishReq = `IELTS ${program.min_ielts} / TOEFL ${program.min_toefl}`;
  } else if (program.min_ielts != null) {
    englishReq = `IELTS ${program.min_ielts}`;
  } else if (program.min_toefl != null) {
    englishReq = `TOEFL ${program.min_toefl}`;
  }

  return {
    // IDs kept as strings to match existing ProfileContext save/compare logic
    id: String(program.id),
    _numericId: program.id,

    // Core program fields
    program: program.name,
    degree: program.degree_level || null,
    fieldOfStudy: program.field_of_study || null,
    description: program.description || null,
    sourceUrl: program.source_url || null,

    // University identity (joined)
    university: university?.name || 'University not listed',
    country: university?.country || null,
    city: university?.city || null,
    universityWebsite: university?.website || null,

    // Cost & timeline
    tuition: tuition,
    duration: program.duration_months ? `${program.duration_months} months` : null,
    deadline: program.application_deadline || null,

    // Requirements
    cgpaReq: program.min_cgpa != null ? String(program.min_cgpa) : null,
    englishReq: englishReq,
    requiredDegree: program.required_degree || null,

    // Match score — not computed by this integration step
    matchScore: null,

    // Indicate data came from real backend (not mock)
    sourceStatus: 'live-backend',
    requiredDocuments: [],
    applicationUrl: null,
    applicationUrlStatus: 'unavailable',

    kind: 'program',
  };
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

/**
 * Fetch all universities with optional filters.
 * GET /universities/?country=&search=&skip=&limit=
 */
export async function fetchUniversities({ country, search, skip = 0, limit = 100 } = {}) {
  const params = new URLSearchParams();
  if (country) params.set('country', country);
  if (search) params.set('search', search);
  params.set('skip', String(skip));
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/universities/?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch universities (${response.status})`);
  }
  return response.json(); // UniversityResponse[]
}

/**
 * Fetch a single university by its numeric ID.
 * GET /universities/{id}
 * Returns null (not a throw) on 404 so callers can handle missing gracefully.
 */
export async function fetchUniversityById(id) {
  const response = await fetch(`${API_BASE_URL}/universities/${id}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to fetch university ${id} (${response.status})`);
  }
  return response.json(); // UniversityResponse
}

/**
 * Fetch all programs with optional filters.
 * GET /programs/?country=&field_of_study=&degree_level=&max_tuition=&search=&skip=&limit=
 */
export async function fetchPrograms({
  country,
  field_of_study,
  degree_level,
  max_tuition,
  deadline_before,
  university_id,
  search,
  skip = 0,
  limit = 100,
} = {}) {
  const params = new URLSearchParams();
  if (country) params.set('country', country);
  if (field_of_study) params.set('field_of_study', field_of_study);
  if (degree_level) params.set('degree_level', degree_level);
  if (max_tuition != null) params.set('max_tuition', String(max_tuition));
  if (deadline_before) params.set('deadline_before', deadline_before);
  if (university_id != null) params.set('university_id', String(university_id));
  if (search) params.set('search', search);
  params.set('skip', String(skip));
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/programs/?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch programs (${response.status})`);
  }
  return response.json(); // ProgramResponse[]
}

/**
 * Fetch a single program by its numeric ID, then joins its university.
 * Returns { program: ProgramResponse, university: UniversityResponse|null }
 * Returns null on 404.
 */
export async function fetchProgramById(id) {
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) return null;

  const response = await fetch(`${API_BASE_URL}/programs/${numericId}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to fetch program ${numericId} (${response.status})`);
  }
  const program = await response.json(); // ProgramResponse

  // Join university to get name/country for the detail page
  const university = await fetchUniversityById(program.university_id);

  return { program, university };
}

/**
 * Fetches all programs and all universities, joins them, and returns
 * an array of frontend-mapped program objects ready for Universities.jsx.
 *
 * If the database is empty this returns [] — the UI handles that with its
 * existing "No programs match these filters" empty state.
 */
export async function fetchMappedPrograms(filters = {}) {
  const [programs, universities] = await Promise.all([
    fetchPrograms(filters),
    fetchUniversities(),
  ]);

  // Build a lookup map so joining is O(1) per program
  const universityMap = Object.fromEntries(universities.map((u) => [u.id, u]));

  return programs.map((p) => mapProgramToFrontend(p, universityMap[p.university_id] || null));
}

