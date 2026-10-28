
import pandas as pd
from pathlib import Path

codebooks = [
    Path("data/raw/Crop_Wise_Area_Production_Yield/Crop_Wise_Area_Production_Yield_codebook.xlsx"),
    Path("data/raw/Crop-wise_Area_Production_Yield_UPAG/Crop-wise_Area_Production_Yield_UPAG_codebook.xlsx"),
]

for path in codebooks:
    print("\n" + "=" * 70)
    print("CODEBOOK:", path.name)

    try:
        workbook = pd.ExcelFile(path)
        print("Sheets:", workbook.sheet_names)

        for sheet in workbook.sheet_names:
            print(f"\n--- Sheet: {sheet} ---")
            df = pd.read_excel(path, sheet_name=sheet)
            print(df.to_string(index=False, max_rows=40))
    except Exception as error:
        print("Error reading codebook:", error)
