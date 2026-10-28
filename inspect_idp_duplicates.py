
import pandas as pd
from pathlib import Path

INPUT = Path("data/processed/idp_standardized.csv")
OUTPUT = Path(
    "data/processed/quality_reports/idp_key_audit.csv"
)

def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Dataset not found: {INPUT}")

    df = pd.read_csv(INPUT, low_memory=False)

    # Candidate keys: compare both the code-based and name-based versions.
    code_key = [
        "year", "state_code", "district_code", "crop_code", "season"
    ]
    name_key = [
        "year", "state_code", "district_code", "crop_name", "season"
    ]

    required = set(code_key + ["crop_name"])
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Normalize key text in temporary columns only.
    df["_crop_name_key"] = (
        df["crop_name"].astype("string").str.strip().str.casefold()
    )
    df["_season_key"] = (
        df["season"].astype("string").str.strip().str.casefold()
    )

    code_key = [
        "year", "state_code", "district_code", "crop_code", "_season_key"
    ]
    name_key = [
        "year", "state_code", "district_code", "_crop_name_key", "_season_key"
    ]

    code_duplicates = df.duplicated(code_key, keep=False)
    name_duplicates = df.duplicated(name_key, keep=False)

    print("=" * 75)
    print("IDP RECORD-KEY AUDIT")
    print("=" * 75)
    print(f"Total records: {len(df):,}")
    print(
        "Rows in repeated crop-code key groups: "
        f"{int(code_duplicates.sum()):,}"
    )
    print(
        "Rows in repeated crop-name key groups: "
        f"{int(name_duplicates.sum()):,}"
    )

    # Exact duplicate check across original columns.
    exact_duplicates = df.drop(
        columns=["_crop_name_key", "_season_key"]
    ).duplicated(keep=False)

    print(
        "Rows in exact duplicate records: "
        f"{int(exact_duplicates.sum()):,}"
    )

    # Save name-based key collisions for manual review.
    review = df.loc[name_duplicates].copy()
    review["key_audit_reason"] = (
        "Repeated year/state/district/crop-name/season key"
    )

    review = review.drop(
        columns=["_crop_name_key", "_season_key"]
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(OUTPUT, index=False)

    print(f"Name-key review saved to: {OUTPUT}")
    print("No rows were removed or changed in the source dataset.")

if __name__ == "__main__":
    main()
