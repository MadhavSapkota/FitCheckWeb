"""One-time helper: Google OAuth login for the Google Ads API, then stores the credentials
directly as GitHub Actions secrets with `gh secret set`. Nothing secret is printed.

Usage (from the repo root):
  .venv-seo/bin/pip install google-auth-oauthlib
  .venv-seo/bin/python seo-agent/tools/setup_google_ads_secrets.py
"""
import getpass
import subprocess
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

REPO = "MadhavSapkota/FitCheckWeb"
SCOPES = ["https://www.googleapis.com/auth/adwords"]


def set_secret(name: str, value: str) -> None:
    subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value.encode(), check=True)
    print(f"  saved secret {name}")


def main() -> int:
    print("Paste values when asked (input is hidden).")
    client_id = getpass.getpass("OAuth Client ID: ").strip()
    client_secret = getpass.getpass("OAuth Client secret: ").strip()
    dev_token = getpass.getpass("Google Ads developer token: ").strip()
    customer_id = input("Google Ads customer ID (e.g. 123-456-7890): ").strip().replace("-", "")
    login_id = input("Manager (MCC) account ID if you use one, else press Enter: ").strip().replace("-", "")
    if not (client_id and client_secret and dev_token and customer_id.isdigit()):
        print("Missing or invalid values.")
        return 1
    flow = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": client_id, "client_secret": client_secret,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": "https://oauth2.googleapis.com/token",
                       "redirect_uris": ["http://localhost"]}}, SCOPES)
    print("A browser window will open. Sign in with the Google account that owns the Google Ads account.")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        print("No refresh token returned. Remove the app's access at myaccount.google.com/permissions and retry.")
        return 1
    set_secret("GOOGLE_ADS_CLIENT_ID", client_id)
    set_secret("GOOGLE_ADS_CLIENT_SECRET", client_secret)
    set_secret("GOOGLE_ADS_DEVELOPER_TOKEN", dev_token)
    set_secret("GOOGLE_ADS_REFRESH_TOKEN", creds.refresh_token)
    set_secret("GOOGLE_ADS_CUSTOMER_ID", customer_id)
    if login_id:
        set_secret("GOOGLE_ADS_LOGIN_CUSTOMER_ID", login_id)
    print("Done. All Google Ads secrets are stored in GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
