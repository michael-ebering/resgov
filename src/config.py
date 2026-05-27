import os
import tomllib
from typing import Optional, Dict, Any

DEFAULT_RGF_PATH = os.path.join(os.getcwd(), ".rgf")

def load_rgf_config(rgf_path: str = DEFAULT_RGF_PATH) -> Dict[str, Any]:
    """
    Loads and parses the .rgf configuration file.
    Returns a dictionary of the configuration.
    """
    config = {}
    if not os.path.exists(rgf_path):
        return config

    try:
        with open(rgf_path, "rb") as f:
            config = tomllib.load(f)
    except Exception as e:
        print(f"Warning: Could not load or parse .rgf file at {rgf_path}: {e}")
        # Potentially log to a more robust system for production

    return config

# Example usage (for testing)
if __name__ == "__main__":
    # Create a dummy .rgf file for testing
    dummy_rgf_content = """
# .rgf - Resource Governance Framework Configuration

[global]
currency = "USD"
fail_safe_action = "deny" # Was passiert, wenn der Proxy offline ist?

[agents.hermes]
daily_budget = 3.00
max_tokens_per_request = 4096
allowed_models = ["owl-alpha", "deepseek-v4"]

[agents.subagent]
daily_budget = 1.00
max_tokens_per_request = 1024
allowed_models = ["gpt-4o-mini"]
"""
    with open(".rgf", "w") as f:
        f.write(dummy_rgf_content)

    loaded_config = load_rgf_config(".rgf")
    print("Loaded RGF Config:")
    print(loaded_config)
    os.remove(".rgf") # Clean up dummy file
