
import pandas as pd
from pathlib import Path

ROOT = Path("data")
RAW = ROOT / "raw"
PROCESSED = ROOT / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

sources = {
    "idp": (
        RAW / "Crop_Wise_Area_Production_Yield"
        / "crop-wise-area-production-yield.csv"
    ),
    "upag": (
        RAW / "Crop-wise_Area_Production_Yield_UPAG"
        / "cropwise-area-production-yield-upag.csv"
    ),
}

for name, path in sources.items():
    print(f"\nProcessing {name.upper()}...")
    df = pd.read_csv(path, low_memory=False)

    # Standardize column names without changing source files.
    df.columns = df.columns.str.strip().str.lower()

    # Parse numeric columns.
    for col in ["area", "production", "yield"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Keep the original reported yield and units.
    df["source_dataset"] = name.upper()

    if name == "idp":
        df["yield_tonnes_per_hectare"] = df["yield"]
    else:
        # UPAG yield is documented in kilograms per hectare.
        df["yield_tonnes_per_hectare"] = df["yield"] / 1000

    # Flag invalid or incomplete measurements; do not silently delete.
    df["has_valid_area"] = df["area"].gt(0)
    df["has_valid_production"] = df["production"].ge(0)
    df["has_valid_yield"] = df["yield_tonnes_per_hectare"].ge(0)

    df["needs_review"] = ~(
        df["has_valid_area"]
        & df["has_valid_production"]
        & df["has_valid_yield"]
    )

    output = PROCESSED / f"{name}_standardized.csv"
    df.to_csv(output, index=False)

    print("Rows:", len(df))
    print("Rows flagged for review:", int(df["needs_review"].sum()))
    print("Saved:", output)

print("\nStandardization complete.")
print("Original raw files were not modified.")
