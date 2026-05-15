# An honest ledger is worth more than a flattering one.
# Let every cost here be counted true.
def normalize_usage(usage: dict) -> dict:
    """
    Normalize usage statistics to standard format.
    Handles OpenAI and llama.cpp formats.

    Adds standardized token fields to the original data:
    - input_tokens: Number of tokens in the prompt
    - output_tokens: Number of tokens generated
    - total_tokens: Sum of input and output tokens
    """
    if not usage:
        return {}

    # Map various field names to standard names
    input_tokens = (
        usage.get('input_tokens')  # Already standard
        or usage.get('prompt_tokens')  # OpenAI
        or usage.get('prompt_n')  # llama.cpp
        or 0
    )

    output_tokens = (
        usage.get('output_tokens')  # Already standard
        or usage.get('completion_tokens')  # OpenAI
        or usage.get('predicted_n')  # llama.cpp
        or 0
    )

    total_tokens = usage.get('total_tokens') or (input_tokens + output_tokens)

    # Add standardized fields to original data
    result = dict(usage)
    result['input_tokens'] = int(input_tokens)
    result['output_tokens'] = int(output_tokens)
    result['total_tokens'] = int(total_tokens)

    return result
