
import re
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

INPUT_PATH = Path("data/processed/idp_standardized.csv")
OUTPUT_DIR = Path("data/processed/yield_ml")

# Broad screening threshold for manual review, not a universal
# biological limit for every crop.
REVIEW_YIELD_THRESHOLD = 100.0

TRAIN_END_YEAR = 2015
VALIDATION_END_YEAR = 2018

NUMERIC_COLUMNS = [
    "area",
    "production",
    "yield_tonnes_per_hectare",
]


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def parse_start_year(value):
    """Extract starting year from values such as 1997-1998."""
    if pd.isna(value):
        return pd.NA

    match = re.search(r"(19|20)\d{2}", str(value))

    if match:
        return int(match.group())

    return pd.NA


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_PATH}\n"
            "Run prepare_crop_data.py first."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print("SATYACOVER: CROP YIELD DATASET PREPARATION")
    print("=" * 75)

    # -----------------------------------------------------
    # 1. LOAD DATA
    # -----------------------------------------------------

    df = pd.read_csv(INPUT_PATH, low_memory=False)

    print(f"\nInput file: {INPUT_PATH}")
    print(f"Original rows: {len(df):,}")

    required = [
        "year",
        "state_name",
        "district_name",
        "crop_name",
        "season",
        "area",
        "production",
        "yield_tonnes_per_hectare",
    ]

    missing_columns = [
        col for col in required if col not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Required columns missing: {missing_columns}"
        )

    # Preserve the original source ID if available.
    if "id" in df.columns:
        df["source_record_id"] = df["id"]

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["year_start"] = (
        df["year"].apply(parse_start_year).astype("Int64")
    )

    # -----------------------------------------------------
    # 2. CALCULATE DATA-QUALITY FLAGS
    # -----------------------------------------------------

    area = df["area"]
    production = df["production"]
    target = df["yield_tonnes_per_hectare"]

    df["calculated_yield_t_ha"] = (
        production / area.where(area.gt(0))
    )

    calculated = df["calculated_yield_t_ha"]

    df["flag_missing_measurement"] = (
        area.isna()
        | production.isna()
        | target.isna()
        | df["year_start"].isna()
    )

    df["flag_nonpositive_area"] = (
        area.notna() & area.le(0)
    )

    df["flag_negative_measurement"] = (
        area.lt(0) | production.lt(0) | target.lt(0)
    ).fillna(False)

    df["flag_zero_yield_positive_production"] = (
        target.eq(0) & production.gt(0) & area.gt(0)
    )

    comparable = (
        target.notna()
        & calculated.notna()
        & calculated.gt(0)
        & target.ge(0)
    )

    df["relative_yield_difference"] = (
        (target - calculated).abs()
        / calculated.where(calculated.gt(0))
    )

    df["flag_yield_difference_over_20pct"] = (
        comparable
        & df["relative_yield_difference"].gt(0.20)
    )

    df["flag_yield_over_review_threshold"] = (
        target.gt(REVIEW_YIELD_THRESHOLD)
    )

    # Repeated candidate keys are flagged for review, not deleted.
    key = [
        "year",
        "state_name",
        "district_name",
        "crop_name",
        "season",
    ]

    df["flag_repeated_candidate_key"] = df.duplicated(
        subset=key,
        keep=False,
    )

    flag_columns = [
        "flag_missing_measurement",
        "flag_nonpositive_area",
        "flag_negative_measurement",
        "flag_zero_yield_positive_production",
        "flag_yield_difference_over_20pct",
        "flag_yield_over_review_threshold",
        "flag_repeated_candidate_key",
    ]

    df["needs_manual_review"] = df[flag_columns].any(axis=1)

    # -----------------------------------------------------
    # 3. SELECT INITIAL MODEL CANDIDATES
    # -----------------------------------------------------

    # Keep suspicious records in the audit file, but exclude them
    # from this conservative first modeling dataset.
    df["eligible_for_initial_model"] = (
        ~df[flag_columns].any(axis=1)
    )

    # -----------------------------------------------------
    # 4. ASSIGN CHRONOLOGICAL SPLITS
    # -----------------------------------------------------

    df["dataset_split"] = "unassigned"

    known_year = df["year_start"].notna()

    df.loc[
        known_year & df["year_start"].le(TRAIN_END_YEAR),
        "dataset_split",
    ] = "train"

    df.loc[
        known_year
        & df["year_start"].gt(TRAIN_END_YEAR)
        & df["year_start"].le(VALIDATION_END_YEAR),
        "dataset_split",
    ] = "validation"

    df.loc[
        known_year & df["year_start"].gt(VALIDATION_END_YEAR),
        "dataset_split",
    ] = "test"

    # -----------------------------------------------------
    # 5. SAVE COMPLETE AUDIT DATASET
    # -----------------------------------------------------

    audit_path = OUTPUT_DIR / "idp_yield_dataset_audit.csv"
    df.to_csv(audit_path, index=False)

    # -----------------------------------------------------
    # 6. SAVE RECORDS REQUIRING REVIEW
    # -----------------------------------------------------

    review_path = OUTPUT_DIR / "idp_yield_review.csv"

    df.loc[df["needs_manual_review"]].to_csv(
        review_path,
        index=False,
    )

    # -----------------------------------------------------
    # 7. BUILD MODEL TABLE
    # -----------------------------------------------------

    # Do not use production as an input feature: the target yield
    # is derived from production / area, so this would leak the answer.
    feature_columns = [
        "year_start",
        "state_name",
        "district_name",
        "crop_name",
        "season",
        "area",
    ]

    target_column = "yield_tonnes_per_hectare"

    model_columns = feature_columns + [target_column, "year"]

    candidates = df.loc[
        df["eligible_for_initial_model"],
        model_columns,
    ].copy()

    # FIX: Assign split directly from each row's own year_start.
    # No merge on year is necessary or appropriate.
    candidates["dataset_split"] = "unassigned"

    candidate_year = candidates["year_start"].notna()

    candidates.loc[
        candidate_year
        & candidates["year_start"].le(TRAIN_END_YEAR),
        "dataset_split",
    ] = "train"

    candidates.loc[
        candidate_year
        & candidates["year_start"].gt(TRAIN_END_YEAR)
        & candidates["year_start"].le(VALIDATION_END_YEAR),
        "dataset_split",
    ] = "validation"

    candidates.loc[
        candidate_year
        & candidates["year_start"].gt(VALIDATION_END_YEAR),
        "dataset_split",
    ] = "test"

    candidates_path = (
        OUTPUT_DIR / "idp_yield_training_candidates.csv"
    )
    candidates.to_csv(candidates_path, index=False)

    split_files = {
        "train": "idp_yield_train.csv",
        "validation": "idp_yield_validation.csv",
        "test": "idp_yield_test.csv",
    }

    for split_name, filename in split_files.items():
        split_df = candidates.loc[
            candidates["dataset_split"].eq(split_name)
        ].copy()

        split_df.to_csv(OUTPUT_DIR / filename, index=False)

    # -----------------------------------------------------
    # 8. PRINT SUMMARY
    # -----------------------------------------------------

    print("\nDATA QUALITY SUMMARY")
    print("-" * 75)

    for flag in flag_columns:
        print(f"{flag}: {int(df[flag].sum()):,}")

    print(
        "\nRecords needing manual review: "
        f"{int(df['needs_manual_review'].sum()):,}"
    )

    print(
        "Records eligible for initial model: "
        f"{int(df['eligible_for_initial_model'].sum()):,}"
    )

    print("\nCHRONOLOGICAL SPLIT SUMMARY")
    print("-" * 75)

    for split_name in [
        "train",
        "validation",
        "test",
        "unassigned",
    ]:
        total = int(
            candidates["dataset_split"].eq(split_name).sum()
        )
        print(f"{split_name.capitalize():12s}: {total:,}")

    print("\nTARGET SUMMARY (tonnes/hectare)")
    print("-" * 75)

    if not candidates.empty:
        print(
            candidates[target_column].describe().to_string(
                float_format=lambda value: f"{value:.4f}"
            )
        )
    else:
        print("No eligible rows. Review the data-quality flags.")

    print("\nOUTPUT FILES")
    print("-" * 75)

    for filename in [
        "idp_yield_dataset_audit.csv",
        "idp_yield_review.csv",
        "idp_yield_training_candidates.csv",
        "idp_yield_train.csv",
        "idp_yield_validation.csv",
        "idp_yield_test.csv",
    ]:
        print(OUTPUT_DIR / filename)

    print("\nDataset preparation complete.")
    print("The original standardized dataset was not modified.")
    print(
        "These outputs are candidates for modeling, not proof "
        "of model accuracy or crop-loss validation."
    )


if __name__ == "__main__":
    main()
