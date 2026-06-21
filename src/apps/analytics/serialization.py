from datetime import date, datetime
from decimal import Decimal


def make_json_serializable(value):
    if isinstance(value, dict):
        return {
            key: make_json_serializable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [make_json_serializable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
