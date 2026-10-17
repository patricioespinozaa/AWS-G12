"""Conversión de los objetos del motor (dataclasses, DataFrames, numpy, fechas) a JSON."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date

import numpy as np
import pandas as pd


def a_json(x):
    """Convierte dataclasses, fechas, DataFrames y tipos numpy en estructuras JSON."""
    if is_dataclass(x):
        return {k: a_json(v) for k, v in asdict(x).items()}
    if isinstance(x, dict):
        return {str(k): a_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [a_json(v) for v in x]
    if isinstance(x, pd.DataFrame):
        return a_json(x.replace({np.nan: None}).to_dict(orient="records"))
    if isinstance(x, pd.Series):
        return a_json(x.to_dict())
    if isinstance(x, (date, pd.Timestamp)):
        return x.isoformat()[:10]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return None if np.isnan(x) else round(float(x), 4)
    if isinstance(x, float):
        return None if np.isnan(x) else round(x, 4)
    if isinstance(x, np.bool_):
        return bool(x)
    return x
