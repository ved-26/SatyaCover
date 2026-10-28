
import pandas as pd
from pathlib import Path

files = [
    Path("data/processed/idp_standardized.csv"),
    Path("data/processed/upag_standardized.csv"),
]

for path in files:
    df = pd.read_csv(path, low_memory=False)

    print("\n" + "=" * 60)
    print("FILE:", path.name)
    print("Rows:", len(df))

    print("\nMissing values in key measurements:")
    print(
        df[["area", "production", "yield_tonnes_per_hectare"]]
        .isna()
        .sum()
        .to_string()
    )

    print("\nNon-positive area:", int((df["area"] <= 0).sum()))
    print("Negative production:", int((df["production"] < 0).sum()))
    print("Negative standardized yield:",
          int((df["yield_tonnes_per_hectare"] < 0).sum()))

    print("\nYield percentiles (tonnes/hectare):")
    print(
        df["yield_tonnes_per_hectare"]
        .quantile([0, 0.5, 0.9, 0.95, 0.99, 1])
        .to_string()
    )

print("\nValidation summary complete.")
