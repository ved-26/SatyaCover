
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

DATA_DIR = Path("data/processed/yield_ml")
MODEL_DIR = Path("models")

MODEL_PATH = MODEL_DIR / "crop_yield_xgboost_no_area_candidate.joblib"
TRAIN_FILE = DATA_DIR / "idp_yield_train.csv"
TEST_FILE = DATA_DIR / "idp_yield_test.csv"

TARGET = "yield_tonnes_per_hectare"
MIN_GROUP_SIZE = 30

MODEL_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------
# METRICS
# --------------------------------------------------

def calculate_metrics(actual, predicted):
    return {
        "records": len(actual),
        "MAE": mean_absolute_error(actual, predicted),
        "RMSE": np.sqrt(mean_squared_error(actual, predicted)),
        "R2": (
            r2_score(actual, predicted)
            if len(actual) >= 2
            else np.nan
        ),
        "bias": np.mean(predicted - actual),
        "median_absolute_error": np.median(
            np.abs(predicted - actual)
        ),
    }


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    print("=" * 65)
    print("SATYACOVER - DETAILED CROP YIELD ERROR ANALYSIS")
    print("=" * 65)

    # Load model
    print("\nLoading trained XGBoost model...")

    artifact = joblib.load(MODEL_PATH)

    preprocessor = artifact["preprocessor"]
    model = artifact["model"]
    features = artifact["features"]

    # Load datasets
    print("Loading training and test datasets...")

    train_df = pd.read_csv(TRAIN_FILE, low_memory=False)
    test_df = pd.read_csv(TEST_FILE, low_memory=False)

    test_df = test_df.reset_index(drop=True)

    # Validate required columns
    required = features + [
        TARGET,
        "crop_name",
        "year_start",
    ]

    missing = [
        col for col in required
        if col not in test_df.columns
    ]

    if missing:
        raise ValueError(f"Missing test columns: {missing}")

    # Predict
    print("\nGenerating predictions...")

    X_test = preprocessor.transform(test_df[features])
    actual = test_df[TARGET].to_numpy()

    predictions = model.predict(X_test)

    # Prediction error
    test_df["actual_yield"] = actual
    test_df["predicted_yield"] = predictions
    test_df["error"] = predictions - actual
    test_df["absolute_error"] = np.abs(
        test_df["error"]
    )

    # --------------------------------------------------
    # CROP-SPECIFIC BASELINE
    # --------------------------------------------------

    print("\nCalculating crop-specific historical baselines...")

    crop_means = train_df.groupby("crop_name")[TARGET].mean()
    global_mean = train_df[TARGET].mean()

    test_df["baseline_prediction"] = (
        test_df["crop_name"]
        .map(crop_means)
        .fillna(global_mean)
    )

    test_df["baseline_error"] = (
        test_df["baseline_prediction"]
        - test_df["actual_yield"]
    )

    # --------------------------------------------------
    # OVERALL COMPARISON
    # --------------------------------------------------

    xgb_metrics = calculate_metrics(
        test_df["actual_yield"],
        test_df["predicted_yield"],
    )

    baseline_metrics = calculate_metrics(
        test_df["actual_yield"],
        test_df["baseline_prediction"],
    )

    comparison = pd.DataFrame([
        {"model": "XGBoost", **xgb_metrics},
        {"model": "Crop-specific mean baseline", **baseline_metrics},
    ])

    print("\nOVERALL MODEL COMPARISON")
    print("-" * 65)
    print(comparison.to_string(index=False))

    mae_improvement = (
        (baseline_metrics["MAE"] - xgb_metrics["MAE"])
        / baseline_metrics["MAE"]
    ) * 100

    print(
        f"\nXGBoost MAE improvement over crop baseline: "
        f"{mae_improvement:.2f}%"
    )

    # --------------------------------------------------
    # CROP-WISE ANALYSIS
    # --------------------------------------------------

    print("\nCalculating crop-wise errors...")

    crop_results = []

    for crop, group in test_df.groupby("crop_name"):

        if len(group) < MIN_GROUP_SIZE:
            continue

        actual_crop = group["actual_yield"].to_numpy()
        predicted_crop = group["predicted_yield"].to_numpy()
        baseline_crop = group["baseline_prediction"].to_numpy()

        xgb_result = calculate_metrics(
            actual_crop,
            predicted_crop,
        )

        baseline_result = calculate_metrics(
            actual_crop,
            baseline_crop,
        )

        crop_results.append({
            "crop_name": crop,
            "records": len(group),
            "XGBoost_MAE": xgb_result["MAE"],
            "Baseline_MAE": baseline_result["MAE"],
            "MAE_improvement_percent": (
                (baseline_result["MAE"] - xgb_result["MAE"])
                / baseline_result["MAE"] * 100
                if baseline_result["MAE"] > 0
                else np.nan
            ),
            "RMSE": xgb_result["RMSE"],
            "R2": xgb_result["R2"],
            "bias": xgb_result["bias"],
            "median_absolute_error": (
                xgb_result["median_absolute_error"]
            ),
        })

    crop_results = pd.DataFrame(crop_results)

    crop_results = crop_results.sort_values(
        "XGBoost_MAE",
        ascending=False,
    )

    crop_path = MODEL_DIR / "crop_error_analysis.csv"
    crop_results.to_csv(crop_path, index=False)

    print("\nCROPS WITH HIGHEST MAE")
    print("-" * 65)
    print(crop_results.head(15).to_string(index=False))

    print("\nCROPS WITH LOWEST MAE")
    print("-" * 65)
    print(
        crop_results.sort_values("XGBoost_MAE")
        .head(15)
        .to_string(index=False)
    )

    # --------------------------------------------------
    # BIAS ANALYSIS
    # --------------------------------------------------

    print("\nPREDICTION BIAS")

    overestimated = (
        test_df["error"] > 0
    ).sum()

    underestimated = (
        test_df["error"] < 0
    ).sum()

    exact = (
        test_df["error"] == 0
    ).sum()

    print("Overestimated records:", overestimated)
    print("Underestimated records:", underestimated)
    print("Exact predictions:", exact)

    # --------------------------------------------------
    # YEAR-WISE BIAS
    # --------------------------------------------------

    year_results = []

    for year, group in test_df.groupby("year_start"):

        metrics = calculate_metrics(
            group["actual_yield"].to_numpy(),
            group["predicted_yield"].to_numpy(),
        )

        year_results.append({
            "year_start": year,
            **metrics,
        })

    year_results = pd.DataFrame(year_results)

    year_path = MODEL_DIR / "year_error_analysis.csv"
    year_results.to_csv(year_path, index=False)

    # --------------------------------------------------
    # SAVE OUTPUTS
    # --------------------------------------------------

    comparison.to_csv(
        MODEL_DIR / "crop_baseline_comparison.csv",
        index=False,
    )

    test_df.to_csv(
        MODEL_DIR / "detailed_yield_predictions.csv",
        index=False,
    )

    print("\n" + "=" * 65)
    print("ERROR ANALYSIS COMPLETED")
    print("=" * 65)

    print("\nGenerated files:")
    print("1.", crop_path)
    print("2.", year_path)
    print("3.", MODEL_DIR / "crop_baseline_comparison.csv")
    print("4.", MODEL_DIR / "detailed_yield_predictions.csv")


if __name__ == "__main__":
    main()
