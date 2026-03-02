import contextvars
import os
from base64 import b64encode

from databricks.sdk import WorkspaceClient

header_store = contextvars.ContextVar("header_store")


def get_workspace_client():
    return WorkspaceClient()


def get_user_authenticated_workspace_client():
    # Check if running in a Databricks App environment
    is_databricks_app = "DATABRICKS_APP_NAME" in os.environ

    if not is_databricks_app:
        # Running locally, use default authentication
        return WorkspaceClient()

    # Running in Databricks App, require user authentication token
    headers = header_store.get({})
    token = headers.get("x-forwarded-access-token")

    if not token:
        raise ValueError(
            "Authentication token not found in request headers (x-forwarded-access-token). "
        )

    return WorkspaceClient(token=token, auth_type="pat")


def get_atlassian_config() -> dict:
    """
    Get Atlassian configuration including API key and site URL.

    Returns:
        dict: Configuration with 'api_key', 'email', and 'site_url'

    Raises:
        ValueError: If required environment variables are not set
    """
    api_key = os.getenv("DATABRICKS_ATLASSIAN_API_KEY")
    email = os.getenv("DATABRICKS_ATLASSIAN_EMAIL")
    site_url = os.getenv("DATABRICKS_ATLASSIAN_SITE_URL")

    if not api_key:
        raise ValueError(
            "DATABRICKS_ATLASSIAN_API_KEY environment variable is not set. "
            "Please provide your Atlassian API token."
        )

    if not email:
        raise ValueError(
            "DATABRICKS_ATLASSIAN_EMAIL environment variable is not set. "
            "Please provide your Atlassian email address."
        )

    if not site_url:
        raise ValueError(
            "DATABRICKS_ATLASSIAN_SITE_URL environment variable is not set. "
            "Please provide your Atlassian site URL (e.g., https://your-domain.atlassian.net)."
        )

    return {"api_key": api_key, "email": email, "site_url": site_url}


def get_atlassian_auth_header() -> dict:
    """
    Generate HTTP Authorization header for Atlassian REST API.

    Returns:
        dict: Headers with 'Authorization' for Basic auth and 'Accept' for JSON

    Raises:
        ValueError: If authentication configuration is missing
    """
    config = get_atlassian_config()
    credentials = f"{config['email']}:{config['api_key']}"
    encoded_credentials = b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded_credentials}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

