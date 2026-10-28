
import pandas as pd
from pathlib import Path

files = [
    Path("data/processed/idp_standardized.csv"),
    Path("data/processed/upag_standardized.csv"),
]

for path in files:
    df = pd.read_csv(path, low_memory=False)

    print("\n" + "=" * 80)
    print("DATASET:", path.name)

    columns = [
        "year", "state_name", "district_name",
        "crop_name", "season", "area", "production",
        "yield", "yield_tonnes_per_hectare"
    ]
    columns = [c for c in columns if c in df.columns]

    df["yield_tonnes_per_hectare"] = pd.to_numeric(
        df["yield_tonnes_per_hectare"], errors="coerce"
    )

    print("\nTop 15 highest yields:")
    print(
        df.nlargest(15, "yield_tonnes_per_hectare")[columns]
        .to_string(index=False)
    )

    print("\nRows with missing production or yield:")
    missing = df[
        df["production"].isna()
        | df["yield_tonnes_per_hectare"].isna()
    ]
    print("Count:", len(missing))
    print(missing[columns].head(5).to_string(index=False))

print("\nInspection complete. No source files modified.")
