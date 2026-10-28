
import pandas as pd
from pathlib import Path

data_folder = Path("data/raw")

files = [
    "crop_yield_train.parquet",
    "crop_yield_test.parquet",
]

for filename in files:
    file_path = data_folder / filename

    print("\n" + "=" * 60)
    print("FILE:", filename)

    df = pd.read_parquet(file_path)

    print("Dataset shape:", df.shape)
    print("\nColumn names:")
    print(df.columns.tolist())

    if "Year" in df.columns:
        print("\nYear range:", df["Year"].min(), "-", df["Year"].max())
        print("\nRecords per year:")
        print(df["Year"].value_counts().sort_index().to_string())
    else:
        print("\nWARNING: No 'Year' column found.")

    print("\nFirst 5 records:")
    print(df.head().to_string(index=False))

    print("\nMissing values per column:")
    print(df.isnull().sum().to_string())
