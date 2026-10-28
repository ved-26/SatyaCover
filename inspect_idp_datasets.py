
import pandas as pd
from pathlib import Path

datasets = {
    "IDP": Path(
        "data/raw/Crop_Wise_Area_Production_Yield/"
        "crop-wise-area-production-yield.csv"
    ),
    "UPAG": Path(
        "data/raw/Crop-wise_Area_Production_Yield_UPAG/"
        "cropwise-area-production-yield-upag.csv"
    ),
}

for name, path in datasets.items():
    print("\n" + "=" * 65)
    print("DATASET:", name)

    df = pd.read_csv(path, low_memory=False)

    print("Rows:", len(df))
    print("Columns:", len(df.columns))
    print("Year range:", df["year"].min(), "to", df["year"].max())
    print("States:", df["state_name"].nunique())
    print("Districts:", df["district_name"].nunique())
    print("Crops:", df["crop_name"].nunique())
    print("Seasons:", sorted(df["season"].dropna().unique()))

    print("\nMissing values:")
    print(df.isna().sum().to_string())

    key = [
        "year", "state_code", "district_code",
        "crop_code", "season"
    ]
    print("\nExact duplicate rows:", df.duplicated().sum())

    if all(col in df.columns for col in key):
        print("Duplicate candidate keys:", df.duplicated(key).sum())

    area = pd.to_numeric(df["area"], errors="coerce")
    production = pd.to_numeric(df["production"], errors="coerce")
    reported_yield = pd.to_numeric(df["yield"], errors="coerce")

    if name == "IDP":
        calculated_yield = production / area
    else:
        # UPAG reports yield in kg/ha; convert to tonnes/ha.
        calculated_yield = reported_yield / 1000

    valid = (
        area.gt(0)
        & production.ge(0)
        & reported_yield.ge(0)
        & calculated_yield.notna()
    )

    print("\nRows with valid nonnegative area/production/yield:",
          int(valid.sum()))

    print("Reported yield summary:")
    print(reported_yield.describe().to_string())

    if name == "UPAG":
        print("\nUPAG yield converted to tonnes/hectare:")
        print((reported_yield / 1000).describe().to_string())

    print("\nFirst 3 rows:")
    print(df.head(3).to_string(index=False))

print("\nAudit completed. No source files were modified.")
