from dotenv import load_dotenv
import os

# Load local settings, but never print the secret value.
load_dotenv()

api_key = os.getenv("TMDB_API_KEY")

print("TMDB_API_KEY configured:", bool(api_key))