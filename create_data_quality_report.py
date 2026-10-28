
import pandas as pd
from pathlib import Path

FILES = {
    "IDP": Path("data/processed/idp_standardized.csv"),
    "UPAG": Path("data/processed/upag_standardized.csv"),
}

OUTPUT_DIR = Path("data/processed/quality_reports")
TOLERANCE = 0.20


def create_report(name, path):
    print(f"\nAuditing {name}...")

    if not path.exists():
        print(f"File not found: {path}")
        return

    df = pd.read_csv(path, low_memory=False)

    required = [
        "area",
        "production",
        "yield_tonnes_per_hectare",
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"Missing required columns: {missing}")
        return

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    area = df["area"]
    production = df["production"]
    reported = df["yield_tonnes_per_hectare"]

    df["calculated_yield_t_ha"] = (
        production / area.where(area.gt(0))
    )

    calculated = df["calculated_yield_t_ha"]

    # Flags identify records for review; they do not delete data.
    df["flag_missing_measurement"] = (
        area.isna() | production.isna() | reported.isna()
    )

    df["flag_nonpositive_area"] = (
        area.notna() & area.le(0)
    )

    df["flag_negative_measurement"] = (
        area.lt(0) | production.lt(0) | reported.lt(0)
    ).fillna(False)

    df["flag_zero_yield_positive_production"] = (
        reported.eq(0) & production.gt(0) & area.gt(0)
    )

    comparable = (
        reported.notna()
        & calculated.notna()
        & calculated.gt(0)
        & reported.ge(0)
    )

    df["relative_yield_difference"] = (
        (reported - calculated).abs()
        / calculated.where(calculated.gt(0))
    )

    df["flag_yield_difference_over_20pct"] = (
        comparable
        & df["relative_yield_difference"].gt(TOLERANCE)
    )

    # Conservative review flag, not an automatic exclusion.
    # Values above this threshold need crop-specific investigation.
    df["flag_yield_over_100_t_ha"] = (
        reported.gt(100)
    )

    flag_columns = [
        "flag_missing_measurement",
        "flag_nonpositive_area",
        "flag_negative_measurement",
        "flag_zero_yield_positive_production",
        "flag_yield_difference_over_20pct",
        "flag_yield_over_100_t_ha",
    ]

    df["needs_manual_review"] = df[flag_columns].any(axis=1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{name.lower()}_quality_report.csv"
    df.to_csv(output_path, index=False)

    print(f"Total records: {len(df):,}")
    for col in flag_columns:
        print(f"{col}: {int(df[col].sum()):,}")

    print(
        "Records flagged for review: "
        f"{int(df['needs_manual_review'].sum()):,}"
    )
    print(f"Saved report: {output_path}")


def main():
    for name, path in FILES.items():
        create_report(name, path)

    print("\nData-quality reporting complete.")
    print("Original and standardized source files were not modified.")


if __name__ == "__main__":
    main()
