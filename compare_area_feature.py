
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


DATA_DIR = Path("data/processed/yield_ml")
MODEL_DIR = Path("models")

TARGET = "yield_tonnes_per_hectare"

NUMERIC_FEATURES = ["year_start"]
CATEGORICAL_FEATURES = [
    "state_name",
    "district_name",
    "crop_name",
    "season",
]

CONFIGURATIONS = {
    "with_area": NUMERIC_FEATURES + CATEGORICAL_FEATURES,
    "without_area": ["year_start"] + CATEGORICAL_FEATURES,
}


def load_data(filename):
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path, low_memory=False)

    for col in ["year_start", "area", TARGET]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=[TARGET]).copy()

    return df


def make_preprocessor(features):
    numeric = [
        col for col in features
        if col in NUMERIC_FEATURES
    ]

    categorical = [
        col for col in features
        if col in CATEGORICAL_FEATURES
    ]

    transformers = []

    if numeric:
        transformers.append((
            "numeric",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median"))
            ]),
            numeric,
        ))

    if categorical:
        transformers.append((
            "categorical",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ]),
            categorical,
        ))

    return ColumnTransformer(transformers)


def main():
    print("=" * 60)
    print("SATYACOVER - AREA FEATURE ABLATION EXPERIMENT")
    print("=" * 60)

    train_df = load_data("idp_yield_train.csv")
    validation_df = load_data("idp_yield_validation.csv")

    results = []

    for name, features in CONFIGURATIONS.items():

        print(f"\nTraining experiment: {name}")
        print("Features:", features)

        preprocessor = make_preprocessor(features)

        X_train = preprocessor.fit_transform(
            train_df[features]
        )

        X_validation = preprocessor.transform(
            validation_df[features]
        )

        y_train = train_df[TARGET].to_numpy()
        y_validation = validation_df[TARGET].to_numpy()

        print("Training matrix:", X_train.shape)
        print("Validation matrix:", X_validation.shape)

        model = xgb.XGBRegressor(
    objective="reg:squarederror",
    eval_metric="rmse",
    tree_method="hist",
    device="cuda",
    n_estimators=3500,
    learning_rate=0.05,
    max_depth=7,
    min_child_weight=5,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=1.0,
    early_stopping_rounds=50,
    n_jobs=4,
    random_state=42,
)

        model.fit(
            X_train,
            y_train,
            eval_set=[(X_validation, y_validation)],
            verbose=False,
        )

        predictions = model.predict(X_validation)

        mae = mean_absolute_error(
            y_validation, predictions
        )

        rmse = np.sqrt(
            mean_squared_error(y_validation, predictions)
        )

        r2 = r2_score(
            y_validation, predictions
        )

        bias = np.mean(predictions - y_validation)

        results.append({
            "experiment": name,
            "features": len(features),
            "best_iteration": model.best_iteration,
            "MAE": mae,
            "RMSE": rmse,
            "R2": r2,
            "bias": bias,
        })

        print(f"Best iteration: {model.best_iteration}")
        print(f"MAE: {mae:.4f}")
        print(f"RMSE: {rmse:.4f}")
        print(f"R2: {r2:.4f}")
        print(f"Bias: {bias:.4f}")

    results_df = pd.DataFrame(results)

    output_path = MODEL_DIR / "area_feature_ablation.csv"

    results_df.to_csv(output_path, index=False)

    print("\n" + "=" * 60)
    print("EXPERIMENT COMPARISON")
    print("=" * 60)
    print(results_df.to_string(index=False))

    print("\nSaved:", output_path)


if __name__ == "__main__":
    main()
