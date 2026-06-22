import csv
import codecs
import numpy as np

# ── 통계 기준값 (직종 대분류별 월임금총액, 천원) ───────────────────────────
BASE_WAGES = {
    "관리자": 12563,
    "전문가 및 관련종사자": 5149,
    "사무 종사자": 4942,
    "서비스 종사자": 2285,
    "판매 종사자": 4104,
    "농림·어업 숙련 종사자": 3111,
    "기능원 및 관련 기능 종사자": 4147,
    "장치·기계 조작 및 조립 종사자": 4215,
    "단순노무 종사자": 2631,
    "비경제활동/무직": 0,
}

# ── 사회 진입 연령 (취업준비기간 +1년 포함) ────────────────────────────────
# 무학/초등/중학 → 고졸과 동일 취급
ENTRY_AGE = {
    "무학":          20,
    "초등학교":      20,
    "중학교":        20,
    "고등학교":      20,
    "2~3년제 전문대학": 22,
    "4년제 대학교":  24,
    "대학원":        27,
}

# ── 학력 프리미엄 ───────────────────────────────────────────────────────────
EDU_MULT = {
    "무학":          0.80,
    "초등학교":      0.80,
    "중학교":        0.80,
    "고등학교":      0.90,
    "2~3년제 전문대학": 0.95,
    "4년제 대학교":  1.00,
    "대학원":        1.10,
}

# ── 연차별 호봉 계수 (구간별 계단 함수) ─────────────────────────────────────
def get_seniority_mult(t: int) -> float:
    if t < 3:   return 0.70   # 신입 ~ 주임
    if t < 5:   return 0.80   # 대리
    if t < 10:  return 0.90   # 과장
    if t < 15:  return 1.00   # 차장 (대분류 평균 기준)
    if t < 20:  return 1.10   # 부장
    if t < 25:  return 1.15   # 임원급 접근
    return 1.10               # 25년+ 정체/소폭 하락

# 누적 호봉 합계 테이블 사전 계산 (0~70년)
_MAX_YRS = 71
_CUM_SEN = [0.0] * _MAX_YRS
for _t in range(1, _MAX_YRS):
    _CUM_SEN[_t] = _CUM_SEN[_t - 1] + get_seniority_mult(_t)

def cum_seniority(n: int) -> float:
    """t=1 부터 t=n 까지 호봉계수의 합 (연금 누적 계산용)"""
    if n <= 0:
        return 0.0
    if n >= _MAX_YRS:
        return _CUM_SEN[_MAX_YRS - 1]
    return _CUM_SEN[n]


def main():
    np.random.seed(42)

    src_dir = r"g:\내 드라이브\03_DArt-B\22_학술제\퇴직연금 _XAI\temp"

    # ── 1. 직업 매핑 테이블 로드 (occupation_mapping.csv) ──────────────────
    occ_map: dict[str, dict] = {}
    with open(f"{src_dir}\\occupation_mapping.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            occ_map[row["original_job"]] = {
                "job_category":     row["job_category"],
                "salary_multiplier": float(row["salary_multiplier"]),
                "reasoning":        row["reasoning"],
            }

    # ── 2. 원본 파일 읽기 (persona_final_earnings.csv, EUC-KR) ────────────
    print("원본 파일 읽는 중...")
    src_rows: list[dict] = []
    with open(f"{src_dir}\\persona_final_earnings.csv", encoding="cp949", newline="") as f:
        reader = csv.DictReader(f)
        orig_fieldnames = list(reader.fieldnames)
        for row in reader:
            src_rows.append(row)
    print(f"  {len(src_rows):,}행 로드 완료")

    # ── 3. 파생 변수 계산 ──────────────────────────────────────────────────
    NEW_COLS = [
        "job_category", "salary_multiplier", "reasoning",
        "entry_age", "military_delay", "years_of_service",
        "seniority_multiplier", "education_multiplier", "region_multiplier",
        "random_noise",
        "estimated_monthly_salary", "estimated_annual_salary",
        "pension_balance",
    ]

    unmapped: set[str] = set()
    out_rows: list[dict] = []

    for row in src_rows:
        occ = row["occupation"]
        edu = row.get("education_level", "4년제 대학교")
        sex = row.get("sex", "")
        age = int(row.get("age", 30))
        province = row.get("province", "")

        # 직업 매핑 (occupation_mapping에 없으면 기본값)
        if occ in occ_map:
            m = occ_map[occ]
        else:
            unmapped.add(occ)
            m = {"job_category": "전문가 및 관련종사자", "salary_multiplier": 1.0, "reasoning": "매핑 없음 — 전문가 평균 적용"}

        job_cat  = m["job_category"]
        sal_mult = m["salary_multiplier"]
        reasoning = m["reasoning"]

        # 사회 진입 연령 & 군 복무 지연
        entry_age  = ENTRY_AGE.get(edu, 24)
        mil_delay  = 2 if sex == "남자" else 0
        years      = max(0, age - entry_age - mil_delay)

        # 계수들
        sen_mult = get_seniority_mult(years)          # 현재 연차 기준 호봉계수
        edu_mult = EDU_MULT.get(edu, 1.0)
        reg_mult = 1.08 if province.startswith("서울") else 1.00
        noise    = np.random.lognormal(mean=0.0, sigma=0.15)

        base = BASE_WAGES.get(job_cat, 0)

        # 현재 월 소득 추정
        monthly = base * sal_mult * sen_mult * edu_mult * reg_mult * noise
        annual  = monthly * 12

        # 퇴직연금 잔액 = Σ(t=1→years) [base × sal_mult × seniority(t) × edu × reg × noise]
        #              = base × sal_mult × edu × reg × noise × Σ seniority(t)
        pension = base * sal_mult * edu_mult * reg_mult * noise * cum_seniority(years)

        row["job_category"]             = job_cat
        row["salary_multiplier"]        = round(sal_mult, 4)
        row["reasoning"]                = reasoning
        row["entry_age"]                = entry_age
        row["military_delay"]           = mil_delay
        row["years_of_service"]         = years
        row["seniority_multiplier"]     = round(sen_mult, 2)
        row["education_multiplier"]     = edu_mult
        row["region_multiplier"]        = reg_mult
        row["random_noise"]             = round(noise, 4)
        row["estimated_monthly_salary"] = round(monthly, 1)
        row["estimated_annual_salary"]  = round(annual, 1)
        row["pension_balance"]          = round(pension, 1)

        out_rows.append(row)

    # ── 4. 출력 (UTF-8-sig) ────────────────────────────────────────────────
    all_cols = orig_fieldnames + NEW_COLS
    out_path = f"{src_dir}\\persona_final_earnings.csv"
    print(f"결과 파일 쓰는 중 → {out_path}")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"완료: {len(out_rows):,}행 저장")

    if unmapped:
        print(f"\n[경고] occupation_mapping에 없는 직업 {len(unmapped)}개:")
        for u in sorted(unmapped)[:20]:
            print(f"  - {u}")

    # ── 5. 간단한 통계 출력 ────────────────────────────────────────────────
    pensions  = [float(r["pension_balance"]) for r in out_rows]
    monthlies = [float(r["estimated_monthly_salary"]) for r in out_rows]
    years_arr = [int(r["years_of_service"]) for r in out_rows]

    print("\n── 요약 통계 ─────────────────────────────────────────────────────")
    print(f"  추정 월소득 (천원)  중앙값={np.median(monthlies):,.0f}  평균={np.mean(monthlies):,.0f}  max={np.max(monthlies):,.0f}")
    print(f"  근속연수          중앙값={np.median(years_arr):.0f}  평균={np.mean(years_arr):.1f}  max={np.max(years_arr)}")
    print(f"  퇴직연금 잔액(천원) 중앙값={np.median(pensions):,.0f}  평균={np.mean(pensions):,.0f}  max={np.max(pensions):,.0f}")

    # 무직 비율
    inactive = sum(1 for r in out_rows if r["job_category"] == "비경제활동/무직")
    print(f"\n  무직(pension=0): {inactive:,}명 ({inactive/len(out_rows)*100:.1f}%)")


if __name__ == "__main__":
    main()
