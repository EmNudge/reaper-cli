"""Recursive empty-string/empty-collection filter for cleaner JSON output."""


def remove_empty_strings(data: dict | list, keep_keys: set | None = None) -> dict | list:
    keep_keys = keep_keys or set()
    if isinstance(data, dict):
        return {
            key: remove_empty_strings(value, keep_keys) if key not in keep_keys else value
            for key, value in data.items()
            if (
                key in keep_keys
                or (isinstance(value, (list, dict)) and bool(value))
                or (not isinstance(value, (str, list, dict)))
                or (isinstance(value, str) and value != "")
            )
        }
    if isinstance(data, list):
        return [
            remove_empty_strings(item, keep_keys)
            for item in data
            if item != "" and (not isinstance(item, (list, dict)) or bool(item))
        ]
    return data
