"""
Europe pilot dataset: 10 universities, 20 English-taught Master's programmes.

Har record official university pages se check kiya gaya hai (LAST_VERIFIED date par).
Jo field official source par nahi mila wo None hai - kuch bhi guess nahi kiya.

Usage (backend folder se):
    python migrate_program_columns.py      # pehli dafa, naye columns ke liye
    python seed_europe_programs.py         # sirf missing records add karta hai
    python seed_europe_programs.py --update  # existing seeded records ko is data se refresh karo

Notes:
- tuition_amount / tuition_currency = university ka published figure (per year).
  tuition_usd_per_year = usi ka conversion, ECB reference rates (RATES_DATE) se.
- min_toefl purane 0-120 TOEFL iBT scale par hai. Jahan sirf naya (1-6) scale
  diya gaya tha, wahan None rakha hai aur description mein likha hai.
- min_cgpa sirf tab set hai jab source ne 4.0 scale par minimum diya ho
  (eligibility engine 4.0 scale assume karta hai).
- application_deadline = verification date ke baad agla official deadline (YYYY-MM-DD),
  taa ke deadline_before filter kaam kare. Baqi intakes description mein hain.
- Living costs verify nahi kiye, is liye living_cost_usd_per_year None hai.
"""
import sys
from datetime import date

from app.database import SessionLocal
from app.models.opportunity import University, Program

LAST_VERIFIED = date(2026, 10, 25)

# ECB euro reference rates, 23 October 2026 (1 EUR = x) - shared with the financial feasibility service
from app.services.exchange_rates import EUR_RATES, RATES_DATE  # noqa: E402,F401


def to_usd(amount, currency):
    if amount is None:
        return None
    return round(amount / EUR_RATES[currency] * EUR_RATES["USD"])


UNIVERSITIES = [
    {"key": "tum", "name": "Technical University of Munich", "country": "Germany",
     "city": "Munich", "website": "https://www.tum.de/en/"},
    {"key": "saarland", "name": "Saarland University", "country": "Germany",
     "city": "Saarbrücken", "website": "https://www.uni-saarland.de/en/"},
    {"key": "tuwien", "name": "TU Wien", "country": "Austria",
     "city": "Vienna", "website": "https://www.tuwien.at/en/"},
    {"key": "polimi", "name": "Politecnico di Milano", "country": "Italy",
     "city": "Milan", "website": "https://www.polimi.it/en"},
    {"key": "kth", "name": "KTH Royal Institute of Technology", "country": "Sweden",
     "city": "Stockholm", "website": "https://www.kth.se/en"},
    {"key": "aalto", "name": "Aalto University", "country": "Finland",
     "city": "Espoo", "website": "https://www.aalto.fi/en"},
    {"key": "tudelft", "name": "Delft University of Technology", "country": "Netherlands",
     "city": "Delft", "website": "https://www.tudelft.nl/en/"},
    {"key": "ipparis", "name": "Institut Polytechnique de Paris", "country": "France",
     "city": "Palaiseau", "website": "https://www.ip-paris.fr/en"},
    {"key": "elte", "name": "Eötvös Loránd University (ELTE)", "country": "Hungary",
     "city": "Budapest", "website": "https://www.elte.hu/en"},
    {"key": "eth", "name": "ETH Zurich", "country": "Switzerland",
     "city": "Zurich", "website": "https://ethz.ch/en.html"},
]

# Shared source pages (tuition / language rules that apply to several programmes)
TUM_LANG = "https://www.tum.de/en/studies/application/application-info-portal/admission-requirements/language-certificates"
SIC_GUIDE = "https://saarland-informatics-campus.de/en/studium-studies/master-english/application-guide/"
SIC_CS = "https://saarland-informatics-campus.de/en/studium-studies/msc-computer-science/"
TUWIEN_FEE = "https://www.tuwien.at/en/studies/admission/students-union-fee-and-tuition-fee/tuition-fee"
TUWIEN_LANG = "https://www.tuwien.at/en/studies/admission/masters-programmes/other-inter-national-bachelors-degree/competence-in-english"
TUWIEN_DATES = "https://www.tuwien.at/en/studies/admission/masters-programmes/other-inter-national-bachelors-degree"
POLIMI_DATES = "https://www.polimi.it/en/prospective-students/how-to-apply/admission-to-laurea-magistrale/foreign-qualification/deadlines"
POLIMI_LANG = "https://www.polimi.it/en/prospective-students/how-to-apply/admission-to-laurea-magistrale/foreign-qualification/application/list-of-documents-required-by-the-admissions-office"
POLIMI_FEE = "https://www.polimi.it/en/prospective-students/how-much-does-it-cost/laurea-laurea-magistrale-and-single-cycle-programmes"
KTH_APPLY = "https://www.kth.se/en/studies/master/admissions/how-to-apply-for-masters-studies-1.68487"
AALTO_LANG = "https://www.aalto.fi/en/admission-services/language-requirements-in-masters-admissions"
DELFT_FEE = "https://www.tudelft.nl/en/education/study-programme-orientation/practical-matters/tuition-fee-finances"
DELFT_REQ = "https://www.tudelft.nl/en/education/admission-and-application/msc-international-diploma/admission-requirements"
DELFT_COUNTRY = "https://www.tudelft.nl/en/education/admission-and-application/msc-international-diploma/admission-requirements/where-did-you-obtain-your-degree"
DELFT_CS_ADM = "https://www.tudelft.nl/en/education/programmes/masters/cs/msc-computer-science/admission-and-application/non-eu-efta-applicants-with-an-international-bachelor-degree"
IPP_FEE = "https://www.ip-paris.fr/sites/default/files/pages/documents/Masters/master-phd-track-registration-fees-EN-26-27%20(3).pdf"
IPP_ADM = "https://www.ip-paris.fr/en/education/useful-information/admissions"
ETH_FEE = "https://ethz.ch/students/en/studies/financial/tuition-fees.html"
ETH_DATES = "https://ethz.ch/en/studies/master/application/dates.html"


def sources(*urls):
    return "Other official sources: " + " ; ".join(urls)


PROGRAMS = [
    # ---------- Germany: TUM ----------
    {
        "uni": "tum", "name": "Informatics (M.Sc.)", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 12000, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 88,
        "required_degree": "Recognized undergraduate degree (e.g. Bachelor's); admission via TUM aptitude assessment.",
        "application_deadline": "2026-11-30",
        "source_url": "https://www.tum.de/en/studies/degree-programs/detail/informatics-master-of-science-msc",
        "description": (
            "Language of instruction is usually English. Tuition for international (non-EU) students: "
            "EUR 6,000 per semester. Separate from tuition: student union semester fee of EUR 97.00. "
            "Application periods: winter semester 01.02.-31.05., summer semester 01.10.-30.11. "
            "English: IELTS Academic 6.5, TOEFL iBT 88 (Test Date Score only), PTE Academic 65, Cambridge CAE/CPE grade A-C. "
            + sources(TUM_LANG)
        ),
    },
    {
        "uni": "tum", "name": "Data Engineering and Analytics (M.Sc.)", "field_of_study": "Data Science",
        "duration_months": 24, "tuition_amount": 12000, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 88,
        "required_degree": "Recognized undergraduate degree (e.g. Bachelor's) and successful completion of the aptitude assessment (points-based; may include interview).",
        "application_deadline": "2026-11-30",
        "source_url": "https://www.tum.de/en/studies/degree-programs/detail/data-engineering-and-analytics-master-of-science-msc",
        "description": (
            "Language of instruction is usually English. Tuition for international (non-EU) students: "
            "EUR 6,000 per semester. Separate from tuition: student union semester fee of EUR 97.00. "
            "Application periods: winter semester 01.02.-31.05., summer semester 01.10.-30.11. "
            "English: IELTS Academic 6.5, TOEFL iBT 88, PTE Academic 65, Cambridge CAE/CPE grade A-C. "
            + sources(TUM_LANG)
        ),
    },
    # ---------- Germany: Saarland ----------
    {
        "uni": "saarland", "name": "Computer Science (M.Sc.)", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 0, "tuition_currency": "EUR",
        "min_cgpa": 3.0, "min_ielts": 7.0, "min_toefl": 95,
        "required_degree": "Bachelor's in informatics, computer science or a related field. Stated minimum: CGPA of 75% or 3.00/4.0 plus top-10% class ranking (does not guarantee admission).",
        "application_deadline": "2026-11-15",
        "source_url": "https://www.uni-saarland.de/en/study/programmes/master/informatics.html",
        "description": (
            "Taught entirely in English. No tuition fees. Separate from tuition: administrative semester fee of EUR 412.30 per semester. "
            "Deadlines: 15 May (winter semester start), 15 November (summer semester start). "
            "English C1 required; Medium of Instruction certificate not accepted. Accepted: IELTS Academic 7.0, "
            "TOEFL iBT 95/120 (new scale: 5 of 6), PTE Academic 76, Cambridge C1 Advanced / C2 Proficiency. "
            "Requires two academic references and a motivation letter. "
            + sources(SIC_CS, SIC_GUIDE)
        ),
    },
    {
        "uni": "saarland", "name": "Cybersecurity (M.Sc.)", "field_of_study": "Cybersecurity",
        "duration_months": 24, "tuition_amount": 0, "tuition_currency": "EUR",
        "min_cgpa": 3.0, "min_ielts": 7.0, "min_toefl": 95,
        "required_degree": "Bachelor's in computer science, informatics or a related field, with knowledge equivalent to Saarland's core CS bachelor area (mathematics, theoretical and practical informatics). Stated minimum CGPA 75% or 3.00/4.0.",
        "application_deadline": "2026-11-15",
        "source_url": "https://www.uni-saarland.de/en/study/programmes/master/cybersecurity.html",
        "description": (
            "Taught in English. No tuition fees; a semester fee applies (see Saarland Informatics Campus fee information). "
            "Deadlines: 15 May (winter semester start), 15 November (summer semester start). "
            "English C1 required; Medium of Instruction certificate not accepted. Accepted: IELTS Academic 7.0, "
            "TOEFL iBT 95/120, PTE Academic 76, Cambridge C1 Advanced / C2 Proficiency. "
            + sources(SIC_GUIDE)
        ),
    },
    # ---------- Austria: TU Wien ----------
    {
        "uni": "tuwien", "name": "Data Science", "field_of_study": "Data Science",
        "duration_months": 24, "tuition_amount": 1453.44, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 87,
        "required_degree": "Eligible Bachelor's degree (e.g. Informatics, Business Informatics, Technical Mathematics); supplementary exams of up to 30 ECTS may be required.",
        "application_deadline": "2027-01-15",
        "source_url": "https://www.tuwien.at/en/studies/studies/master-programmes/informatics/data-science",
        "description": (
            "Degree awarded: Dipl.-Ing. (comparable to Master of Science), 120 ECTS, taught in English. "
            "Tuition for non-EU nationals: EUR 726.72 per semester. The ÖH student union fee is charged separately (amount not verified). "
            "Non-EU/EEA applicants should submit complete applications 16 Jan-15 Jul (winter semester) or 16 Jul-15 Jan (summer semester). "
            "English B2: IELTS Academic 6.5, TOEFL iBT 87 (new scale 4.5), Cambridge B2 First/C1 Advanced 160+. "
            + sources(TUWIEN_FEE, TUWIEN_LANG, TUWIEN_DATES)
        ),
    },
    {
        "uni": "tuwien", "name": "Software Engineering", "field_of_study": "Software Engineering",
        "duration_months": 24, "tuition_amount": 1453.44, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 87,
        "required_degree": "Accredited Bachelor's with at least 120 ECTS in mathematics and computer science (incl. 20 ECTS maths/statistics, 25 ECTS algorithms/data structures/programming, 20 ECTS CS foundations); up to 30 ECTS supplementary exams possible.",
        "application_deadline": "2027-01-15",
        "source_url": "https://www.tuwien.at/en/studies/studies/master-programmes/informatics/software-engineering",
        "description": (
            "Degree awarded: Dipl.-Ing. (comparable to Master of Science), 120 ECTS, taught in English. "
            "Tuition for non-EU nationals: EUR 726.72 per semester. The ÖH student union fee is charged separately (amount not verified). "
            "Non-EU/EEA applicants should submit complete applications 16 Jan-15 Jul (winter semester) or 16 Jul-15 Jan (summer semester). "
            "English B2: IELTS Academic 6.5, TOEFL iBT 87 (new scale 4.5). "
            + sources(TUWIEN_FEE, TUWIEN_LANG, TUWIEN_DATES)
        ),
    },
    {
        "uni": "tuwien", "name": "Logic and Artificial Intelligence", "field_of_study": "Artificial Intelligence",
        "duration_months": 24, "tuition_amount": 1453.44, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 87,
        "required_degree": "Accredited Bachelor's with at least 120 ECTS in mathematics and computer science (incl. 25 ECTS maths/statistics/theoretical CS, 20 ECTS algorithms/data structures/programming); up to 30 ECTS supplementary exams possible.",
        "application_deadline": "2027-01-15",
        "source_url": "https://www.tuwien.at/en/studies/studies/master-programmes/informatics/logic-and-artificial-intelligence",
        "description": (
            "Degree awarded: Dipl.-Ing. (comparable to Master of Science), 120 ECTS, taught in English. "
            "Tuition for non-EU nationals: EUR 726.72 per semester. The ÖH student union fee is charged separately (amount not verified). "
            "Non-EU/EEA applicants should submit complete applications 16 Jan-15 Jul (winter semester) or 16 Jul-15 Jan (summer semester). "
            "English B2: IELTS Academic 6.5, TOEFL iBT 87 (new scale 4.5). "
            + sources(TUWIEN_FEE, TUWIEN_LANG, TUWIEN_DATES)
        ),
    },
    # ---------- Italy: Politecnico di Milano ----------
    {
        "uni": "polimi", "name": "Computer Science and Engineering", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 3943.04, "tuition_currency": "EUR",
        "min_ielts": 6.0, "min_toefl": 78,
        "required_degree": "First-level (Bachelor's) degree; a Bachelor's in Computer Science and Engineering gives a good chance of admission, other backgrounds may need fundamentals courses.",
        "application_deadline": "2026-12-01",
        "source_url": "https://www.polimi.it/en/education/laurea-magistrale-programmes/programme-detail/computer-science-and-engineering",
        "description": (
            "Laurea Magistrale (MSc), 120 credits, taught in English, Milano Leonardo campus. "
            "Fees: non-EU students with a foreign degree and no scholarship pay the maximum contribution (proportional to ECTS in the study plan); "
            "the highest annual all-inclusive contribution listed for 2026/27 is EUR 3,943.04 (stored here as an upper bound). "
            "Intake September 2027 (Engineering): 1st call 1 Oct-1 Dec 2026, 2nd call 12 Jan-25 Feb 2027; results by end of May 2027. "
            "English: IELTS 6.0, TOEFL iBT 78 (tests from 21/01/2026: 4.5), PTE Academic 59, Cambridge First grade B. "
            + sources(POLIMI_DATES, POLIMI_LANG, POLIMI_FEE)
        ),
    },
    {
        "uni": "polimi", "name": "High Performance Computing Engineering", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 3943.04, "tuition_currency": "EUR",
        "min_ielts": 6.0, "min_toefl": 78,
        "required_degree": "Non-Italian applicants: Bachelor's in Computer Science Engineering, Mathematical Engineering or a related field; other backgrounds assessed case by case.",
        "application_deadline": "2026-12-01",
        "source_url": "https://www.polimi.it/en/education/laurea-magistrale-programmes/programme-detail/high-performance-computing-engineering",
        "description": (
            "Laurea Magistrale (MSc), 2 years, taught in English, Milano Leonardo campus. "
            "Fees: non-EU students with a foreign degree and no scholarship pay the maximum contribution; "
            "highest annual all-inclusive contribution listed for 2026/27 is EUR 3,943.04 (upper bound). "
            "Intake September 2027 (Engineering): 1st call 1 Oct-1 Dec 2026, 2nd call 12 Jan-25 Feb 2027. "
            "English: IELTS 6.0, TOEFL iBT 78 (tests from 21/01/2026: 4.5), PTE Academic 59. "
            + sources(POLIMI_DATES, POLIMI_LANG, POLIMI_FEE)
        ),
    },
    # ---------- Sweden: KTH ----------
    {
        "uni": "kth", "name": "MSc Machine Learning", "field_of_study": "Machine Learning",
        "duration_months": 24, "tuition_amount": 192500, "tuition_currency": "SEK",
        "min_ielts": 6.5, "min_toefl": None,
        "required_degree": "Bachelor's degree (180 ECTS) or equivalent with specified levels of mathematics and computer science.",
        "application_deadline": "2027-01-15",
        "source_url": "https://www.kth.se/en/studies/master/machine-learning/msc-machine-learning-1.48533",
        "description": (
            "Two-year programme (120 ECTS) taught in English, start August 2027. "
            "Full programme tuition for non-EU/EEA/Swiss citizens: SEK 385,000 (stored as SEK 192,500 per year), paid per semester. "
            "Application fee SEK 900. Apply by 15 January; documents by 1 February. "
            "English 6 equivalent: IELTS 6.5 overall or TOEFL 4.5 (new TOEFL scale; old-scale score not stated). "
            + sources("https://www.kth.se/en/studies/master/machine-learning/fees-machine-learning-1.909974",
                      "https://www.kth.se/en/studies/master/machine-learning/entry-requirements-machine-learning-1.48539",
                      KTH_APPLY)
        ),
    },
    {
        "uni": "kth", "name": "MSc Computer Science", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 192500, "tuition_currency": "SEK",
        "min_ielts": 6.5, "min_toefl": None,
        "required_degree": "Bachelor's (180 ECTS) incl. 28.5 ECTS mathematics (calculus, linear algebra, probability/statistics, discrete maths) and 22.5 ECTS CS (OOP, algorithms and data structures, algorithmic complexity).",
        "application_deadline": "2027-01-15",
        "source_url": "https://www.kth.se/en/studies/master/computer-science",
        "description": (
            "Two-year programme (120 ECTS) taught in English, start August 2027. "
            "Full programme tuition for non-EU/EEA/Swiss citizens: SEK 385,000 (stored as SEK 192,500 per year). "
            "Application fee SEK 900. Apply by 15 January; documents by 1 February. "
            "English: IELTS 6.5 overall or TOEFL 4.5 (new TOEFL scale). "
            + sources("https://www.kth.se/en/studies/master/computer-science/fees-communication-systems-1.909945",
                      "https://www.kth.se/en/studies/master/computer-science/entry-requirements-computer-science-1.419975",
                      KTH_APPLY)
        ),
    },
    # ---------- Finland: Aalto ----------
    {
        "uni": "aalto", "name": "Computer Science, Master of Science (Technology)", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 17000, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 92,
        "required_degree": "Relevant Bachelor's with excellent grades. Previous-year GPA benchmark for Pakistan: 3.60/4 (not a guarantee of admission).",
        "application_deadline": "2027-01-05",
        "source_url": "https://www.aalto.fi/en/study-options/computer-science-master-of-science-technology",
        "description": (
            "Two years, 120 ECTS, taught in English. Tuition for non-EU/EEA citizens: EUR 17,000 per year. "
            "Application period 7 Dec 2026 - 5 Jan 2027. GRE not required (optional supporting document). "
            "English: IELTS Academic 6.5 (writing 6.0); TOEFL iBT 92 (writing 22) for tests before 21 Jan 2026, "
            "or 4.5 total (4.0 each subtest) on the new scale. "
            + sources(AALTO_LANG)
        ),
    },
    {
        "uni": "aalto", "name": "Machine Learning, Data Science and Artificial Intelligence, Master of Science (Technology)",
        "field_of_study": "Machine Learning / Data Science / Artificial Intelligence",
        "duration_months": 24, "tuition_amount": 17000, "tuition_currency": "EUR",
        "min_ielts": 6.5, "min_toefl": 92,
        "required_degree": "Bachelor's in computer science, software engineering, communications or electrical engineering, or sufficient maths and CS studies. Previous-year GPA benchmark for Pakistan: 3.60/4. GRE is obligatory for applicants with a non-EU/EEA bachelor's (Admission group 2).",
        "application_deadline": "2027-01-05",
        "source_url": "https://www.aalto.fi/en/study-options/machine-learning-data-science-and-artificial-intelligence-master-of-science-technology",
        "description": (
            "Two years, 120 ECTS, taught in English. Tuition for non-EU/EEA citizens: EUR 17,000 per year. "
            "Application period 7 Dec 2026 - 5 Jan 2027. GRE required for applicants with a non-EU/EEA bachelor's degree. "
            "English: IELTS Academic 6.5 (writing 6.0); TOEFL iBT 92 (writing 22) for tests before 21 Jan 2026, "
            "or 4.5 total (4.0 each subtest) on the new scale. "
            + sources(AALTO_LANG)
        ),
    },
    # ---------- Netherlands: TU Delft ----------
    {
        "uni": "tudelft", "name": "MSc Computer Science", "field_of_study": "Computer Science",
        "duration_months": 24, "tuition_amount": 26479, "tuition_currency": "EUR",
        "min_ielts": 7.0, "min_toefl": 100,
        "required_degree": "Engineering bachelor in Computer Science or closely related field. Pakistan: a 5-year professional Bachelor's, or a 4-year Bachelor's plus a relevant Master's, with final mark of 70% or better; a 4-year Bachelor's alone is not sufficient. GRE required for international diplomas.",
        "application_deadline": "2027-01-15",
        "source_url": "https://www.tudelft.nl/en/education/programmes/masters/cs/msc-computer-science",
        "description": (
            "24 months, 120 EC, taught in English, September start. "
            "Institutional (non-EEA) tuition: EUR 26,479 for 2027/2028 (EUR 25,633 for 2026/2027). "
            "Application deadline 15 January (23:59 CEST); applications are ranked by the admission committee. "
            "English: IELTS Academic 7.0 (6.5 each section); TOEFL iBT 100 (22 each section) before 21 Jan 2026, "
            "or 5 (4.5 each section) on the new scale; Cambridge C1/C2 185. "
            + sources(DELFT_FEE, DELFT_REQ, DELFT_COUNTRY, DELFT_CS_ADM)
        ),
    },
    # ---------- France: IP Paris ----------
    {
        "uni": "ipparis", "name": "Master in Computer Science - Data and Artificial Intelligence (DataAI)",
        "field_of_study": "Data Science / Artificial Intelligence",
        "duration_months": 24, "tuition_amount": 7166, "tuition_currency": "EUR",
        "required_degree": "Bachelor of Science in Computer Science; good background in mathematics.",
        "application_deadline": "2027-01-14",
        "source_url": "https://www.ip-paris.fr/en/education/masters/computer-science-program/major-data-and-artificial-intelligence-dataai",
        "description": (
            "Two-year Master's (120 ECTS) taught in English, Palaiseau campus. "
            "Tuition for non-EU/EEA students on international-track programmes (DAIIG track): EUR 7,166 per year (2026-2027 schedule, indexed annually; 2027-28 not yet published). "
            "IP Paris portal sessions: 28 Oct 2026-14 Jan 2027, 15 Jan-31 Mar 2027, 1 Apr-31 May 2027. "
            "English generally B2-C1 depending on programme; specific test scores not published. "
            + sources(IPP_FEE, IPP_ADM)
        ),
    },
    {
        "uni": "ipparis", "name": "Master in Computer Science - Cybersecurity", "field_of_study": "Cybersecurity",
        "duration_months": 24, "tuition_amount": 7166, "tuition_currency": "EUR",
        "required_degree": "Bachelor of Science in Computer Science.",
        "application_deadline": "2027-01-14",
        "source_url": "https://www.ip-paris.fr/en/education/masters/computer-science-program/major-cybersecurity",
        "description": (
            "Two-year Master's (120 ECTS) taught in English, Palaiseau campus. "
            "Tuition for non-EU/EEA students on international-track programmes (CCSN track): EUR 7,166 per year (2026-2027 schedule, indexed annually). "
            "IP Paris portal sessions: 28 Oct 2026-14 Jan 2027, 15 Jan-31 Mar 2027, 1 Apr-31 May 2027. "
            "English B1/B2 required; specific test scores not published. "
            + sources(IPP_FEE, IPP_ADM)
        ),
    },
    # ---------- Hungary: ELTE ----------
    {
        "uni": "elte", "name": "Artificial Intelligence MSc", "field_of_study": "Artificial Intelligence",
        "duration_months": 24, "tuition_amount": 6400, "tuition_currency": "EUR",
        "required_degree": "BSc in Computer Science, or at least 60 ECTS in informatics and mathematical subjects from a completed CS-related Bachelor's.",
        "application_deadline": "2027-04-30",
        "source_url": "https://www.elte.hu/en/artificial-intelligence-msc",
        "description": (
            "4 semesters, taught in English. Tuition EUR 3,200 per semester (EU/EEA and non-EU/EEA); application fee EUR 150. "
            "September 2027 intake deadline: 30 April 2027. "
            "English: at least B2 oral and written (intermediate); no specific IELTS/TOEFL score published."
        ),
    },
    {
        "uni": "elte", "name": "Computer Science MSc - Cybersecurity specialization", "field_of_study": "Cybersecurity",
        "duration_months": 24, "tuition_amount": 6400, "tuition_currency": "EUR",
        "required_degree": "BSc in Computer Science, or at least 60 ECTS in informatics (and mathematics) from a Bachelor's programme.",
        "application_deadline": "2027-04-30",
        "source_url": "https://apply.elte.hu/courses/course/313-msc-computer-science-msc-course---cybersecurity-specialization",
        "description": (
            "MSc (Computer Scientist), 4 semesters, 120 ECTS, taught in English. Tuition EUR 3,200 per semester; "
            "application fee EUR 150 (non-refundable). September 2027 intake deadline: 30 April 2027 23:59 CET; start 1 Sept 2027. "
            "English: B2 oral and written; no specific IELTS/TOEFL score published."
        ),
    },
    # ---------- Switzerland: ETH Zurich ----------
    {
        "uni": "eth", "name": "Computer Science MSc", "field_of_study": "Computer Science",
        "tuition_amount": 4380, "tuition_currency": "CHF",
        "required_degree": "Bachelor's degree meeting ETH's programme-specific performance prerequisites; two recommendation letters and a motivation letter required.",
        "application_deadline": "2026-11-30",
        "source_url": "https://ethz.ch/en/studies/master/application/master-informatik.html",
        "description": (
            "Taught in English. Tuition for students coming to Switzerland to study (from Autumn Semester 2025): CHF 2,190 per semester "
            "(threefold fee; simple fee CHF 730). Application fee CHF 150. "
            "International Bachelor's applicants: application period 1-30 November 2026 (deadline 30 Nov 2026, 11:59 CET) for Autumn Semester 2027. "
            "English C1 proof required by the deadline (IELTS/TOEFL/Cambridge accepted); ETH does not publish minimum scores on the checked pages. "
            + sources(ETH_FEE, ETH_DATES)
        ),
    },
    {
        "uni": "eth", "name": "Data Science MSc", "field_of_study": "Data Science",
        "tuition_amount": 4380, "tuition_currency": "CHF",
        "required_degree": "Bachelor's degree meeting ETH's programme-specific performance prerequisites; two recommendation letters and a motivation letter required.",
        "application_deadline": "2026-11-30",
        "source_url": "https://ethz.ch/en/studies/master/application/master-datascience.html",
        "description": (
            "Taught in English. Tuition for students coming to Switzerland to study (from Autumn Semester 2025): CHF 2,190 per semester. "
            "Application fee CHF 150. International Bachelor's applicants: 1-30 November 2026 for Autumn Semester 2027. "
            "English C1 proof required by the deadline; minimum test scores not published on the checked pages. "
            + sources(ETH_FEE, ETH_DATES)
        ),
    },
]

PROGRAM_DEFAULTS = {
    "degree_level": "Master",
    "language_of_instruction": "English",
    "duration_months": None,
    "min_cgpa": None,
    "min_ielts": None,
    "min_toefl": None,
    "living_cost_usd_per_year": None,
    "last_verified": LAST_VERIFIED,
}


def build_program(p, university_id):
    row = {**PROGRAM_DEFAULTS, **{k: v for k, v in p.items() if k != "uni"}}
    row["university_id"] = university_id
    row["tuition_usd_per_year"] = to_usd(row["tuition_amount"], row["tuition_currency"])
    row["description"] = (
        f"{row['description']} "
        f"[Tuition in USD converted from {row['tuition_currency']} at ECB reference rate of {RATES_DATE}. "
        f"Living costs not included. Last verified {LAST_VERIFIED.isoformat()}.]"
    ).strip()
    return row


def main():
    update = "--update" in sys.argv
    sys.stdout.reconfigure(encoding="utf-8")
    db = SessionLocal()
    stats = {"uni_added": 0, "uni_existing": 0, "prog_added": 0, "prog_existing": 0, "prog_updated": 0}

    try:
        uni_ids = {}
        for u in UNIVERSITIES:
            data = {k: v for k, v in u.items() if k != "key"}
            uni = (
                db.query(University)
                .filter(University.name.ilike(data["name"]), University.country.ilike(data["country"]))
                .first()
            )
            if uni:
                stats["uni_existing"] += 1
                if update:
                    for field, value in data.items():
                        setattr(uni, field, value)
            else:
                uni = University(**data)
                db.add(uni)
                db.flush()
                stats["uni_added"] += 1
            uni_ids[u["key"]] = uni.id

        for p in PROGRAMS:
            row = build_program(p, uni_ids[p["uni"]])
            program = (
                db.query(Program)
                .filter(Program.university_id == row["university_id"], Program.name.ilike(row["name"]))
                .first()
            )
            if program:
                stats["prog_existing"] += 1
                if update:
                    for field, value in row.items():
                        setattr(program, field, value)
                    stats["prog_updated"] += 1
            else:
                db.add(Program(**row))
                stats["prog_added"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(
        f"Universities added: {stats['uni_added']} | already existed: {stats['uni_existing']}\n"
        f"Programs added: {stats['prog_added']} | already existed: {stats['prog_existing']}"
        + (f" | refreshed: {stats['prog_updated']}" if update else "")
    )


if __name__ == "__main__":
    main()
