import requests
import json
import os

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

response = requests.get(
  url="https://openrouter.ai/api/v1/key",
  headers={
    "Authorization": "Bearer sk-or-v1-049cac0e6180cff033baeef99f433c652c7cec8e3503b7"
  }
)

print(json.dumps(response.json(), indent=2))