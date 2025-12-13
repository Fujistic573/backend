import os
from dotenv import load_dotenv

current_dir = os.getcwd()
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')

print(f"Current Working Directory: {current_dir}")
print(f"Script Directory: {script_dir}")
print(f"Looking for .env at: {env_path}")
print(f"Does .env exist? {os.path.exists(env_path)}")

load_dotenv(env_path)

print(f"EMAIL_ADDRESS loaded: {os.environ.get('EMAIL_ADDRESS')}")
