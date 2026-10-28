import sys
import subprocess
import xgboost as xgb

print("Python executable:", sys.executable)
print("XGBoost version:", xgb.__version__)

print("\nChecking NVIDIA driver...")
try:
    result = subprocess.run(
        ["nvidia-smi"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    print(result.stdout if result.returncode == 0 else result.stderr)
except Exception as exc:
    print("Could not run nvidia-smi:", exc)

print("\nChecking XGBoost CUDA training...")

try:
    import numpy as np

    X = np.array([
        [1.0, 10.0],
        [2.0, 20.0],
        [3.0, 30.0],
        [4.0, 40.0],
        [5.0, 50.0],
        [6.0, 60.0],
    ])
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    model = xgb.XGBRegressor(
        n_estimators=5,
        max_depth=2,
        tree_method="hist",
        device="cuda",
        n_jobs=2,
    )

    model.fit(X, y)
    print("SUCCESS: XGBoost trained using CUDA.")
    print("Sample predictions:", model.predict(X[:2]))

except Exception as exc:
    print("GPU training failed:")
    print(type(exc).__name__, str(exc))