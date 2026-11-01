"""
Reviewed scholarship-program data. INSTITUTIONS comes from each scholarship record's own study type,
provider and notes. LINKS covers only pairs in the same host country that the rules don't rule out.

A pair is "confirmed" only where the official page in source_url was read on CHECKED and its wording
covers that program. Everything else stays unverified and carries no last_verified date.
Pairs with no entry here (Erasmus Mundus, for one) are still evaluated by the rules, without evidence.
"""
from datetime import date

CHECKED = date(2026, 10, 31)

# scholarship id: (institution_scope, host_institution, host_university_id in our catalog)
INSTITUTIONS = {
    1: ("national", None, None), 4: ("national", None, None),
    2: ("participating_list", None, None), 17: ("participating_list", None, None),
    3: ("participating_list", None, None), 5: ("participating_list", None, None),
    6: ("single_institution", "University of Amsterdam", None),
    7: ("single_institution", "Leiden University", None),
    8: ("single_institution", "Delft University of Technology", 7),
    9: ("single_institution", "Maastricht University", None),
    10: ("single_institution", "Radboud University", None),
    11: ("participating_list", None, None),
    12: ("single_institution", "KTH Royal Institute of Technology", 5),
    13: ("single_institution", "Lund University", None),
    14: ("single_institution", "Chalmers University of Technology", None),
    15: ("national", None, None),
    16: ("single_institution", "Sciences Po", None),
    18: ("national", None, None), 19: ("national", None, None),
    20: ("participating_list", None, None), 21: ("participating_list", None, None),
    22: ("participating_list", None, None), 23: ("national", None, None),
    24: ("participating_list", None, None), 25: ("national", None, None),
    26: ("single_institution", "Politecnico di Milano", 4),
    27: ("participating_list", None, None), 28: ("national", None, None), 29: ("national", None, None),
    30: ("participating_list", None, None), 31: ("participating_list", None, None),
    32: ("participating_list", None, None),
    33: ("single_institution", "University of Cambridge", None),
    34: ("participating_list", None, None), 35: ("national", None, None),
    36: ("participating_list", None, None),
    37: ("single_institution", "University of Melbourne", None),
    38: ("participating_list", None, None),
    39: ("single_institution", "University of Adelaide", None),
    40: ("single_institution", "Australian National University", None),
    41: ("single_institution", "Australian National University", None),
}

KTH_RULE = ("KTH: scholarships are \"available for applicants to all master's programmes with two years spent at KTH\", "
            "and not for joint Erasmus+ and EIT programmes. This program's fee page: \"KTH's scholarships are open to all "
            "fee-paying applicants\".")
POLIMI_RULE = ("Polimi's merit-based scholarships are for international candidates admitted to a Master of Science programme "
               "taught in English; this program's official page gives English as its language.")
POLIMI_NOTE = "Only applications made in the early-bird admission window qualify."
TUM_RULE = ("TUM: \"Both Bachelor's and Master's students at TUM\" can apply. Funders may earmark up to two-thirds of "
            "awards for subjects; the rest are open to all faculties.")
SAARLAND_RULE = ("Saarland University supports its students regardless of \"Nationalität, Alter, Semesterzahl oder "
                 "Studiengang\", through the StudienStiftungSaar.")
SH_ELTE = ("The official Stipendium Hungaricum portal lists ELTE's MSc Computer Science (Budapest) with a Cybersecurity "
           "specialization.")
MAECI = "The record covers Master's degrees at public or legally recognised Italian universities; this program isn't named."
EIFFEL = "The record's Mathematics and Digital Science field fits, but the institution must nominate the candidate."
EPOS = "Only pre-approved development-related courses qualify, and no such list on record includes this program."
SISGP = "The record says eligible Master's programmes exist across Sweden; no list on record includes this program."
DSU = "Run separately by each Italian region; no regional agency page has been checked."


def _confirmed(scholarship_id, program_id, kind, evidence, url, notes=None):
    return dict(scholarship_id=scholarship_id, program_id=program_id, outcome="confirmed", relationship_type=kind,
                evidence=evidence, source_url=url, verification_status="verified", last_verified=CHECKED, notes=notes)


def _open(scholarship_id, program_id, outcome, evidence, url=None, notes=None):
    return dict(scholarship_id=scholarship_id, program_id=program_id, outcome=outcome, relationship_type="unconfirmed",
                evidence=evidence, source_url=url, verification_status="unverified", last_verified=None, notes=notes)


TUM_URL = "https://www.tum.de/en/studies/fees-and-financial-aid/scholarships/tum-scholarships/deutschlandstipendium/application"
SAARLAND_URL = "https://www.uni-saarland.de/studieren/deutschlandstipendium.html"
SH_URL = "https://apply.stipendiumhungaricum.hu/courses/course/441-msc-computer-science-budapest"
POLIMI_URL = "https://www.polimi.it/en/international-prospective-students/laurea-magistrale-programmes-equivalent-to-master-of-science/scholarships/merit-based-scholarships"
KTH_ML_URL = "https://www.kth.se/en/studies/master/machine-learning/fees-machine-learning-1.909974"
KTH_CS_URL = "https://www.kth.se/en/studies/master/computer-science/fees-communication-systems-1.909945"
DELFT_URL = "https://www.tudelft.nl/en/education/study-programme-orientation/practical-matters/scholarships/faq"

LINKS = [
    _confirmed(24, 1, "all_programs_at_university", TUM_RULE, TUM_URL),
    _confirmed(24, 2, "all_programs_at_university", TUM_RULE, TUM_URL),
    _confirmed(24, 3, "all_programs_at_university", SAARLAND_RULE, SAARLAND_URL),
    _confirmed(24, 4, "all_programs_at_university", SAARLAND_RULE, SAARLAND_URL),
    _confirmed(3, 18, "named_program", SH_ELTE, SH_URL, "Pakistani applicants also go through HEC's annual list."),
    _open(3, 17, "needs_verification",
          "ELTE lists Artificial Intelligence as a Computer Science MSc specialization, but the Stipendium Hungaricum "
          "course page doesn't list it.", SH_URL),
    _confirmed(12, 10, "programs_meeting_stated_criteria", KTH_RULE, KTH_ML_URL),
    _confirmed(12, 11, "programs_meeting_stated_criteria", KTH_RULE, KTH_CS_URL),
    _confirmed(26, 8, "programs_meeting_stated_criteria", POLIMI_RULE, POLIMI_URL, POLIMI_NOTE),
    _confirmed(26, 9, "programs_meeting_stated_criteria", POLIMI_RULE, POLIMI_URL, POLIMI_NOTE),
    _open(8, 14, "potential",
          "TU Delft says the scholarships cover \"all TU Delft regular 2- year MSc programmes\". This program runs 24 months "
          "and isn't on the excluded list, but no page states that it counts as regular.", DELFT_URL),
    _open(5, 14, "needs_verification", "Only participating institutions take part, and no page checked confirms TU Delft for incoming students."),
    _open(15, 15, "potential", EIFFEL), _open(15, 16, "potential", EIFFEL),
    _open(25, 8, "potential", MAECI), _open(25, 9, "potential", MAECI),
    _open(11, 10, "needs_verification", SISGP), _open(11, 11, "needs_verification", SISGP),
    _open(22, 1, "needs_verification", EPOS), _open(22, 2, "needs_verification", EPOS),
    _open(22, 3, "needs_verification", EPOS), _open(22, 4, "needs_verification", EPOS),
    _open(27, 8, "needs_verification", DSU), _open(27, 9, "needs_verification", DSU),
]
