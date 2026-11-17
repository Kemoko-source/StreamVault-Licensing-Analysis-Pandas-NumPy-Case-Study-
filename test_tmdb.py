import os
import requests
from dotenv import load_dotenv

print("Starting script...")

load_dotenv()

api_key = os.getenv("TMDB_API_KEY")
print("API key loaded:", api_key is not None)

url = "https://api.themoviedb.org/3/movie/550"

response = requests.get(
    url,
    params={"api_key": api_key}
)

print("Status code:", response.status_code)
print("Response text:")
print(response.text[:500])