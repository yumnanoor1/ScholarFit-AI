"""
Sourced program costs. Every figure below was read on the official page in source_url on VERIFIED.
Nothing is estimated here: a university with no usable official figure has no row, and the
feasibility calculation reports that cost as missing.

Usage (backend folder):
    python seed_program_costs.py      # adds or refreshes these rows; safe to run again

Notes:
- amount..amount_max is a published range; the calculation uses the upper end.
- includes: other cost categories already inside this figure, so they aren't counted twice.
- Polimi publishes items without a total, so its range is the sum of the items in `note`.
- KTH: its page only shows personal student examples ("not an official KTH budget"), so no living cost.
- Saarland's fact sheet gives a semester fee of EUR 361.90 (exchange students); the program record's
  EUR 412.30 for the M.Sc. Computer Science is used for that program, and Cybersecurity has no figure.
- Delft's living cost is the amount it lists for non-EU students under IND residence-permit rules.
"""
from datetime import date

from app.database import SessionLocal
from app.models.opportunity import Program, ProgramCost

VERIFIED = date(2026, 10, 31)

# Set by the official ETH degree listing / programme pages (the seed had no duration for these)
DURATIONS = {19: 24, 20: 24}

TUM = "https://www.tum.de/en/studies/fees"
SAARLAND = "https://www.uni-saarland.de/fileadmin/upload/global/welcome-center/weltweit/uds_fm_fact_sheet2025_26.pdf"
SAARLAND_CS = "https://www.uni-saarland.de/en/study/programmes/master/informatics.html"
TUWIEN = "https://www.tuwien.at/fileadmin/Assets/dienstleister/international_office/incoming/wg_20230217_web_en.pdf"
POLIMI = "https://www.polimi.it/en/information-for/international-prospective-students/life/living-in-italy/useful-information/cost-of-living"
AALTO = "https://www.aalto.fi/en/international-students/moving-to-finland-and-financial-matters"
DELFT = "https://www.tudelft.nl/en/education/study-programme-orientation/practical-matters/tuition-fee-finances"
IPPARIS = "https://www.ip-paris.fr/en/education/masters/faqs"
ELTE = "https://www.ajk.elte.hu/en/studying_here/pract_info"
ETH = "https://ethz.ch/content/dam/ethz/main/education/finanzielles/files-en/cost-of-living.pdf"


def living(amount, amount_max, currency, period, name, url, note=None, includes=None):
    return dict(category="living_costs", amount=amount, amount_max=amount_max, currency=currency, period=period,
                is_estimate=True, source_name=name, source_url=url, note=note, includes=includes)


def fee(category, amount, currency, period, name, url, note=None):
    return dict(category=category, amount=amount, amount_max=None, currency=currency, period=period,
                is_estimate=False, source_name=name, source_url=url, note=note, includes=None)


def costs_for(program):
    """Rows for one program, by university. KTH gets its application fee only (see the notes above)."""
    name = program.university.name
    url = program.source_url
    if name == "Technical University of Munich":
        return [living(1300, 2000, "EUR", "monthly", "TUM study fees and costs", TUM, "Single-person household, greater Munich."),
                fee("university_fees", 97, "EUR", "semester", "TUM program page", url, "Student union semester fee.")]
    if name == "Saarland University":
        rows = [living(950, None, "EUR", "monthly", "Saarland University fact sheet 2025/26", SAARLAND,
                       "Accommodation, health insurance and general living costs.", "health_insurance")]
        if program.id == 3:
            rows.append(fee("university_fees", 412.30, "EUR", "semester", "Saarland University program page", SAARLAND_CS,
                            "Administrative semester fee."))
        return rows
    if name == "TU Wien":
        return [living(800, 1000, "EUR", "monthly", "TU Wien Welcome Guide (2023)", TUWIEN,
                       "Rent, food, public transport, books and leisure. Published in 2023.")]
    if name == "Politecnico di Milano":
        return [living(672, 1122, "EUR", "monthly", "Politecnico di Milano cost of living", POLIMI,
                       "Sum of published items: accommodation 400-700, food 150-200, social life 100-200, public transport 22.")]
    if name == "KTH Royal Institute of Technology":
        return [fee("application_fees", 900, "SEK", "total", "KTH program page", url)]
    if name == "Aalto University":
        return [living(800, 1300, "EUR", "monthly", "Aalto University: moving to Finland", AALTO, "Published as EUR 800-1300+.")]
    if name == "Delft University of Technology":
        return [living(14200, None, "EUR", "yearly", "TU Delft tuition fee and finances", DELFT,
                       "Living costs for non-EU students under residence-permit rules (2026/2027).")]
    if name == "Institut Polytechnique de Paris":
        return [living(600, 900, "EUR", "monthly", "IP Paris Master's FAQ", IPPARIS,
                       "General estimate for living in Paris; the page is undated and may be out of date.")]
    if "ELTE" in name:
        return [living(750, None, "EUR", "monthly", "ELTE Faculty of Law practical information", ELTE,
                       "Published as HUF 300,000 (about EUR 750): rent, food, local transport, study materials, health insurance.",
                       "health_insurance"),
                fee("application_fees", 150, "EUR", "total", "ELTE program page", url)]
    if name == "ETH Zurich":
        return [living(22100, None, "CHF", "yearly", "ETH Financial Aid Office: study and living costs", ETH,
                       "Rent (2024 average), meals, public transport, health insurance, individual expenses.", "health_insurance"),
                fee("university_fees", 148, "CHF", "yearly", "ETH Financial Aid Office: study and living costs", ETH,
                    "ASVZ, Scholarship Fund and VSETH fees."),
                fee("other", 1500, "CHF", "yearly", "ETH Financial Aid Office: study and living costs", ETH,
                    "Study material and excursions."),
                fee("application_fees", 150, "CHF", "total", "ETH program page", url)]
    return []


def main():
    db = SessionLocal()
    added = updated = 0
    for program_id, months in DURATIONS.items():
        program = db.query(Program).filter(Program.id == program_id).first()
        if program and program.duration_months is None:
            program.duration_months = months
    for program in db.query(Program).order_by(Program.id).all():
        for row in costs_for(program):
            existing = (
                db.query(ProgramCost)
                .filter(ProgramCost.program_id == program.id, ProgramCost.category == row["category"])
                .first()
            )
            if existing:
                for field, value in row.items():
                    setattr(existing, field, value)
                existing.last_verified = VERIFIED
                updated += 1
            else:
                db.add(ProgramCost(program_id=program.id, last_verified=VERIFIED, **row))
                added += 1
    db.commit()
    db.close()
    print(f"Added: {added} | Refreshed: {updated}")


if __name__ == "__main__":
    main()
