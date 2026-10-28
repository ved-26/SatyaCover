from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


# --------------------------------------------------
# PATHS
# --------------------------------------------------

DATA_DIR = Path("data/processed/yield_ml")
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_FILE = DATA_DIR / "idp_yield_train.csv"
VALIDATION_FILE = DATA_DIR / "idp_yield_validation.csv"
TEST_FILE = DATA_DIR / "idp_yield_test.csv"

MODEL_PATH = MODEL_DIR / "crop_yield_xgboost_gpu.joblib"
METRICS_PATH = MODEL_DIR / "crop_yield_xgboost_metrics.csv"

TARGET = "yield_tonnes_per_hectare"

NUMERIC_FEATURES = ["year_start", "area"]

CATEGORICAL_FEATURES = [
    "state_name",
    "district_name",
    "crop_name",
    "season",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

def load_split(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {path.resolve()}"
        )

    df = pd.read_csv(path, low_memory=False)

    if df.empty:
        raise ValueError(f"Dataset is empty: {path}")

    missing = [
        col for col in FEATURES + [TARGET]
        if col not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing columns in {path}: {missing}"
        )

    for col in NUMERIC_FEATURES + [TARGET]:
        df[col] = pd.to_numeric(
            df[col], errors="coerce"
        )

    # The target must be present for supervised learning.
    df = df.dropna(subset=[TARGET]).copy()

    # Avoid invalid target values.
    df = df[
        np.isfinite(df[TARGET]) &
        (df[TARGET] >= 0)
    ].copy()

    return df


# --------------------------------------------------
# PREPROCESS FEATURES
# --------------------------------------------------

def make_preprocessor():
    numeric_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
    ])

    categorical_pipeline = Pipeline([
        (
            "imputer",
            SimpleImputer(strategy="most_frequent"),
        ),
        (
            "onehot",
            OneHotEncoder(
                handle_unknown="ignore",
                sparse_output=True,
            ),
        ),
    ])

    return ColumnTransformer([
        (
            "numeric",
            numeric_pipeline,
            NUMERIC_FEATURES,
        ),
        (
            "categorical",
            categorical_pipeline,
            CATEGORICAL_FEATURES,
        ),
    ])


# --------------------------------------------------
# EVALUATION
# --------------------------------------------------

def evaluate(name, model, X, y):
    predictions = model.predict(X)

    mae = mean_absolute_error(y, predictions)

    rmse = np.sqrt(
        mean_squared_error(y, predictions)
    )

    r2 = r2_score(y, predictions)

    print(f"\n{name} Results")
    print("-" * 45)
    print(f"Records: {len(y):,}")
    print(f"MAE:     {mae:.4f} tonnes/hectare")
    print(f"RMSE:    {rmse:.4f} tonnes/hectare")
    print(f"R²:      {r2:.4f}")

    return {
        "split": name,
        "records": len(y),
        "MAE": mae,
        "RMSE": rmse,
        "R2": r2,
    }


# --------------------------------------------------
# MAIN TRAINING
# --------------------------------------------------

def main():
    print("=" * 60)
    print("SATYACOVER - GPU CROP YIELD PREDICTION")
    print("=" * 60)

    print("\nXGBoost version:", xgb.__version__)

    print("\nLoading chronological datasets...")

    train_df = load_split(TRAIN_FILE)
    validation_df = load_split(VALIDATION_FILE)
    test_df = load_split(TEST_FILE)

    print(f"Training records:   {len(train_df):,}")
    print(f"Validation records: {len(validation_df):,}")
    print(f"Test records:       {len(test_df):,}")

    # Fit preprocessing only on training data.
    preprocessor = make_preprocessor()

    print("\nPreprocessing training features...")

    X_train = preprocessor.fit_transform(
        train_df[FEATURES]
    )

    y_train = train_df[TARGET].to_numpy()

    print("Training feature matrix:", X_train.shape)

    print("\nPreprocessing validation features...")

    X_validation = preprocessor.transform(
        validation_df[FEATURES]
    )

    y_validation = validation_df[TARGET].to_numpy()

    print("Validation feature matrix:", X_validation.shape)

    print("\nPreprocessing test features...")

    X_test = preprocessor.transform(
        test_df[FEATURES]
    )

    y_test = test_df[TARGET].to_numpy()

    print("Test feature matrix:", X_test.shape)

    # GPU-accelerated gradient boosting.
    model = xgb.XGBRegressor(
        objective="reg:squarederror",
        eval_metric="rmse",
        tree_method="hist",
        device="cuda",
        n_estimators=700,
        learning_rate=0.05,
        max_depth=7,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        early_stopping_rounds=30,
        n_jobs=4,
        random_state=42,
    )

    print("\nStarting GPU training...")
    print("Requested device: CUDA")
    print("GPU: NVIDIA GeForce RTX 3050")
    print("Please wait until training finishes.\n")

    # This should fail rather than silently train on the CPU
    # if the requested CUDA training device is unavailable.
    model.fit(
        X_train,
        y_train,
        eval_set=[
            (X_validation, y_validation),
        ],
        verbose=50,
    )

    print("\nBest boosting iteration:", model.best_iteration)

    print("\nEvaluating the trained model...")

    results = []

    results.append(
        evaluate(
            "Validation",
            model,
            X_validation,
            y_validation,
        )
    )

    results.append(
        evaluate(
            "Test",
            model,
            X_test,
            y_test,
        )
    )

    # Save preprocessing and model together.
    artifact = {
        "preprocessor": preprocessor,
        "model": model,
        "features": FEATURES,
        "target": TARGET,
        "device": "cuda",
    }

    joblib.dump(artifact, MODEL_PATH)

    pd.DataFrame(results).to_csv(
        METRICS_PATH,
        index=False,
    )

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)

    print("Saved model:", MODEL_PATH.resolve())
    print("Saved metrics:", METRICS_PATH.resolve())

    print("\nTest metrics:")
    print(pd.DataFrame(results).tail(1).to_string(index=False))


if __name__ == "__main__":
    main()