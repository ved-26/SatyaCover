
import pandas as pd
from pathlib import Path

# Standardized datasets created by prepare_crop_data.py
FILES = {
    "IDP": Path("data/processed/idp_standardized.csv"),
    "UPAG": Path("data/processed/upag_standardized.csv"),
}

TOLERANCE = 0.20  # 20% difference allowed


def check_dataset(name: str, path: Path) -> None:
    """Compare reported yield with production / area."""

    print("\n" + "=" * 90)
    print(f"DATASET: {name}")
    print("=" * 90)

    if not path.exists():
        print(f"ERROR: File not found: {path}")
        print("Run prepare_crop_data.py first.")
        return

    df = pd.read_csv(path, low_memory=False)

    required_columns = [
        "area",
        "production",
        "yield_tonnes_per_hectare",
    ]

    missing_columns = [
        col for col in required_columns if col not in df.columns
    ]

    if missing_columns:
        print("ERROR: Required columns are missing:", missing_columns)
        return

    # Convert measurement columns to numeric safely.
    for col in required_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Calculate yield independently from area and production.
    # Both standardized yields are expressed in tonnes/hectare.
    valid_area = df["area"].gt(0)

    df["calculated_yield_t_ha"] = (
        df["production"] / df["area"].where(valid_area)
    )

    reported = df["yield_tonnes_per_hectare"]
    calculated = df["calculated_yield_t_ha"]

    # Compare records where both values exist and calculated yield is positive.
    comparable = (
        reported.notna()
        & calculated.notna()
        & calculated.gt(0)
        & reported.ge(0)
    )

    # Avoid division by zero and invalid calculations.
    df["yield_ratio"] = (
        reported / calculated.where(calculated.gt(0))
    )

    # Relative difference: 0.0 = exact match; 0.2 = 20% difference.
    df["relative_difference"] = (
        (reported - calculated).abs()
        / calculated.where(calculated.gt(0))
    )

    consistent = (
        comparable
        & df["relative_difference"].le(TOLERANCE)
    )

    inconsistent = comparable & ~consistent

    # Important data-quality conditions.
    missing_reported_yield = reported.isna()
    missing_calculated_yield = calculated.isna()
    zero_reported_positive_production = (
        reported.eq(0)
        & df["production"].gt(0)
        & valid_area
    )

    missing_measurements = (
        df["area"].isna()
        | df["production"].isna()
        | reported.isna()
    )

    print(f"Total records: {len(df):,}")
    print(f"Comparable records: {int(comparable.sum()):,}")
    print(
        "Within 20% of calculated yield: "
        f"{int(consistent.sum()):,}"
    )
    print(
        "Outside 20% of calculated yield: "
        f"{int(inconsistent.sum()):,}"
    )
    print(
        "Missing reported yield: "
        f"{int(missing_reported_yield.sum()):,}"
    )
    print(
        "Missing or uncalculable yield: "
        f"{int(missing_calculated_yield.sum()):,}"
    )
    print(
        "Reported yield is zero despite positive production: "
        f"{int(zero_reported_positive_production.sum()):,}"
    )
    print(
        "Records with missing area, production, or reported yield: "
        f"{int(missing_measurements.sum()):,}"
    )

    # Show the largest discrepancies.
    columns = [
        "year",
        "state_name",
        "district_name",
        "crop_name",
        "area",
        "production",
        "yield_tonnes_per_hectare",
        "calculated_yield_t_ha",
        "yield_ratio",
        "relative_difference",
    ]

    # Include only columns that exist in this particular dataset.
    columns = [col for col in columns if col in df.columns]

    report = df.loc[comparable].copy()

    print("\nLargest yield inconsistencies:")
    if report.empty:
        print("No comparable records were found.")
    else:
        report = report.sort_values(
            "relative_difference",
            ascending=False,
        )

        print(
            report[columns]
            .head(10)
            .to_string(
                index=False,
                float_format=lambda value: f"{value:.8f}",
            )
        )

    # Show records that need attention but may not appear among the
    # largest discrepancies because calculated yield is zero or unavailable.
    zero_cases = df.loc[
        zero_reported_positive_production,
        columns,
    ]

    if not zero_cases.empty:
        print("\nExamples: zero reported yield with positive production")
        print(
            zero_cases.head(5).to_string(
                index=False,
                float_format=lambda value: f"{value:.8f}",
            )
        )

    print(
        "\nNote: discrepancies are data-quality flags, not proof that "
        "a record is incorrect. Source units, rounding, and definitions "
        "should be checked before excluding records."
    )


def main() -> None:
    for name, path in FILES.items():
        check_dataset(name, path)

    print("\n" + "=" * 90)
    print("Consistency check complete. Source files unchanged.")
    print("=" * 90)


if __name__ == "__main__":
    main()
