
from app.earth_engine import (
    initialize_earth_engine,
    get_ndvi_summary,
)
import json

try:
    initialize_earth_engine()

    result = get_ndvi_summary(
        latitude=18.5204,
        longitude=73.8567,
        start_date="2025-10-01",
        end_date="2025-10-31",
    )

    print(json.dumps(result, indent=2))

except Exception as error:
    print("Satellite test failed:")
    print(type(error).__name__, str(error))
