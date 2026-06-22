import csv
import os

REMOVE_COLS = {
    "professional_persona", "sports_persona", "arts_persona",
    "travel_persona", "culinary_persona", "family_persona",
    "persona", "cultural_background",
    "skills_and_expertise", "skills_and_expertise_list",
    "hobbies_and_interests", "hobbies_and_interests_list",
    "career_goals_and_ambitions",
    "marital_status", "military_status", "family_type", "housing_type",
    "district", "country",
}

src = r"g:\내 드라이브\03_DArt-B\22_학술제\퇴직연금 _XAI\temp\persona_final_earnings.csv"
tmp = src + ".tmp"

print("읽는 중...")
rows = []
with open(src, encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    orig_cols = list(reader.fieldnames)
    keep_cols = [c for c in orig_cols if c not in REMOVE_COLS]
    for row in reader:
        rows.append(row)

print(f"  {len(rows):,}행 로드")
print(f"  제거 컬럼: {len(orig_cols) - len(keep_cols)}개 → 잔존: {len(keep_cols)}개")

print("쓰는 중...")
with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=keep_cols, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

os.replace(tmp, src)
print("완료")
print("잔존 컬럼:", keep_cols)
