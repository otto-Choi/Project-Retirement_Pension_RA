import csv

with open("persona_final_earnings.csv", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 5:
            break
        print(
            f"sex={row['sex']}  age={row['age']}  edu={row['education_level']}  "
            f"occ={row['occupation']}  province={row['province']}"
        )
        print(
            f"  job_cat={row['job_category']}  sal_mult={row['salary_multiplier']}  "
            f"entry_age={row['entry_age']}  mil_del={row['military_delay']}  "
            f"years={row['years_of_service']}"
        )
        print(
            f"  sen_m={row['seniority_multiplier']}  edu_m={row['education_multiplier']}  "
            f"reg_m={row['region_multiplier']}  noise={row['random_noise']}"
        )
        print(
            f"  monthly={row['estimated_monthly_salary']}  "
            f"annual={row['estimated_annual_salary']}  "
            f"pension={row['pension_balance']}"
        )
        print()
