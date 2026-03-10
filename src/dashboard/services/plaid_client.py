# services/plaid_client.py
import os
from plaid.api import plaid_api
from plaid.configuration import Configuration
from plaid.model.products import Products
from plaid.model.country_code import CountryCode

PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")  # "sandbox" | "development" | "production"

def plaid_client() -> plaid_api.PlaidApi:
    cfg = Configuration(
        host={
            "sandbox": "https://sandbox.plaid.com",
            "development": "https://development.plaid.com",
            "production": "https://production.plaid.com",
        }[PLAID_ENV],
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(plaid_api.ApiClient(cfg))

PLAID_CLIENT_NAME = os.getenv("PLAID_CLIENT_NAME", "Home Dashboard")
PLAID_PRODUCTS = [Products("transactions")]  # add others if needed
PLAID_COUNTRIES = [CountryCode("US")]
PLAID_REDIRECT_URI = os.getenv("PLAID_REDIRECT_URI")  # optional; exact match in Plaid dashboard

def normalize_money(x):
    return float(x) if x is not None else None
