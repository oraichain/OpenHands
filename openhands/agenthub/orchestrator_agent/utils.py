def get_json_string_from_string(string: str) -> str:
    """Extracts a JSON string from a string.

    Args:
        string (str): The string to extract the JSON string from.

    Returns:
        str: The JSON string.
    """
    ledger_str = string[string.find('{'):string.rfind('}')+1]
    return ledger_str

