import os
from dotenv import load_dotenv
load_dotenv(".env")

class Settings:
    BINANCE_KEY = os.getenv("BINANCE_KEY")
    BINANCE_SECRET = os.getenv("BINANCE_SECRET")

settings = Settings()
