
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)


# --------------------------------------------------
# PATHS
# --------------------------------------------------

DATA_DIR = Path("data/processed/yield_ml")
MODEL_DIR = Path("models")

MODEL_PATH = MODEL_DIR / "crop_yield_xgboost_gpu.joblib"

TRAIN_FILE = DATA_DIR / "idp_yield_train.csv"
TEST_FILE = DATA_DIR / "idp_yield_test.csv"

MODEL_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------
# METRICS
# --------------------------------------------------

def calculate_metrics(y_true, predictions):
    return {
        "records": len(y_true),
        "MAE": mean_absolute_error(y_true, predictions),
        "RMSE": np.sqrt(
            mean_squared_error(y_true, predictions)
        ),
        "R2": (
            r2_score(y_true, predictions)
            if len(y_true) >= 2
            else np.nan
        ),
    }


def evaluate_groups(df, column, predictions):
    results = []

    for group_name, group in df.groupby(column):
        if len(group) < 30:
            continue

        indices = group.index
        y_true = group["yield_tonnes_per_hectare"].to_numpy()
        group_predictions = predictions[indices]

        metrics = calculate_metrics(
            y_true,
            group_predictions
        )

        results.append({
            column: group_name,
            **metrics,
        })

    return pd.DataFrame(results)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    print("=" * 60)
    print("SATYACOVER - CROP YIELD MODEL EVALUATION")
    print("=" * 60)

    print("\nLoading trained model...")

    if not MODEL_PATH.exists():
        raise FileNotFoundError(MODEL_PATH)

    artifact = joblib.load(MODEL_PATH)

    preprocessor = artifact["preprocessor"]
    model = artifact["model"]
    features = artifact["features"]
    target = artifact["target"]

    print("Model loaded successfully.")

    print("\nLoading datasets...")

    train_df = pd.read_csv(TRAIN_FILE, low_memory=False)
    test_df = pd.read_csv(TEST_FILE, low_memory=False)

    test_df = test_df.reset_index(drop=True)

    print("Training records:", len(train_df))
    print("Test records:", len(test_df))

    print("\nPreparing test features...")

    X_test = preprocessor.transform(test_df[features])
    y_test = test_df[target].to_numpy()

    print("Test feature matrix:", X_test.shape)

    print("\nGenerating predictions...")

    predictions = model.predict(X_test)

    test_df["predicted_yield"] = predictions
    test_df["prediction_error"] = (
        test_df["predicted_yield"] - test_df[target]
    )
    test_df["absolute_error"] = (
        test_df["prediction_error"].abs()
    )

    # --------------------------------------------------
    # OVERALL MODEL PERFORMANCE
    # --------------------------------------------------

    overall = calculate_metrics(y_test, predictions)

    # Baseline: always predict the mean yield from training data.
    baseline_prediction = train_df[target].mean()
    baseline_predictions = np.full(
        len(y_test),
        baseline_prediction
    )

    baseline = calculate_metrics(
        y_test,
        baseline_predictions
    )

    print("\nOVERALL MODEL PERFORMANCE")
    print("-" * 50)

    for key, value in overall.items():
        print(f"{key}: {value:.4f}")

    print("\nBASELINE PERFORMANCE")
    print("-" * 50)
    print(f"Training mean yield: {baseline_prediction:.4f}")

    for key, value in baseline.items():
        print(f"{key}: {value:.4f}")

    # --------------------------------------------------
    # CROP-WISE EVALUATION
    # --------------------------------------------------

    print("\nEvaluating crop-wise performance...")

    crop_results = evaluate_groups(
        test_df,
        "crop_name",
        predictions
    )

    crop_results = crop_results.sort_values(
        "records",
        ascending=False
    )

    crop_path = MODEL_DIR / "crop_wise_evaluation.csv"
    crop_results.to_csv(crop_path, index=False)

    print("\nTOP CROPS BY TEST RECORD COUNT")
    print(crop_results.head(15).to_string(index=False))

    # --------------------------------------------------
    # YEAR-WISE EVALUATION
    # --------------------------------------------------

    print("\nEvaluating year-wise performance...")

    year_results = evaluate_groups(
        test_df,
        "year_start",
        predictions
    )

    year_results = year_results.sort_values("year_start")

    year_path = MODEL_DIR / "year_wise_evaluation.csv"
    year_results.to_csv(year_path, index=False)

    print("\nYEAR-WISE PERFORMANCE")
    print(year_results.to_string(index=False))

    # --------------------------------------------------
    # SAVE SUMMARY
    # --------------------------------------------------

    summary = pd.DataFrame([
        {"model": "XGBoost", **overall},
        {"model": "Training mean baseline", **baseline},
    ])

    summary_path = MODEL_DIR / "yield_model_comparison.csv"
    summary.to_csv(summary_path, index=False)

    predictions_path = (
        MODEL_DIR / "yield_test_predictions.csv"
    )

    test_df.to_csv(predictions_path, index=False)

    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)

    print("\nSaved files:")
    print(summary_path)
    print(crop_path)
    print(year_path)
    print(predictions_path)


if __name__ == "__main__":
    main()
