
import pandas as pd
from pathlib import Path

DATA_PATH = Path("data/processed/idp_standardized.csv")
OUTPUT_PATH = Path(
    "data/processed/quality_reports/idp_crop_code_review.csv"
)


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_PATH}"
        )

    df = pd.read_csv(DATA_PATH, low_memory=False)

    required = [
        "year",
        "state_name",
        "district_name",
        "crop_name",
        "crop_code",
        "crop_type",
        "season",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # Normalize text only for analysis; source values remain unchanged.
    df["crop_name_check"] = (
        df["crop_name"].astype("string").str.strip()
    )

    # Summarize the number of distinct crop names for each crop code.
    summary = (
        df.dropna(subset=["crop_code"])
        .groupby("crop_code")
        .agg(
            row_count=("crop_code", "size"),
            distinct_crop_names=("crop_name_check", "nunique"),
            distinct_crop_types=("crop_type", "nunique"),
            crop_names=(
                "crop_name_check",
                lambda values: " | ".join(
                    sorted(values.dropna().unique())
                ),
            ),
        )
        .reset_index()
    )

    shared_codes = summary.loc[
        summary["distinct_crop_names"] > 1
    ].sort_values(
        ["distinct_crop_names", "row_count"],
        ascending=False,
    )

    print("=" * 75)
    print("IDP CROP-CODE INVESTIGATION")
    print("=" * 75)
    print(f"Total dataset rows: {len(df):,}")
    print(f"Distinct non-missing crop codes: {df['crop_code'].nunique():,}")
    print(f"Codes associated with multiple crop names: {len(shared_codes):,}")

    print("\nCrop codes associated with multiple names:")
    if shared_codes.empty:
        print("No shared crop codes found.")
    else:
        print(
            shared_codes.head(25).to_string(
                index=False,
                max_colwidth=120,
            )
        )

    # Inspect records for crop code 188, seen in the earlier audit.
    print("\nDetailed records for crop code 188:")
    code_188 = df.loc[
        pd.to_numeric(df["crop_code"], errors="coerce").eq(188),
        required,
    ]

    if code_188.empty:
        print("No records found for crop code 188.")
    else:
        print(
            code_188[
                ["year", "state_name", "district_name",
                 "crop_name", "crop_code", "crop_type", "season"]
            ]
            .drop_duplicates()
            .head(30)
            .to_string(index=False)
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    shared_codes.to_csv(OUTPUT_PATH, index=False)

    print(f"\nReview file saved to: {OUTPUT_PATH}")
    print("No source records were changed or removed.")


if __name__ == "__main__":
    main()
