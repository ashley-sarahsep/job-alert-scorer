"""Gmail API access: OAuth2 authentication and message retrieval.

This module handles the fiddly parts of talking to Gmail:
  - Running the OAuth2 desktop flow on first use and caching the token.
  - Searching for messages matching a query (e.g. LinkedIn job alerts).
  - Pulling a full message and decoding its HTML body.

It deliberately knows nothing about LinkedIn or job parsing -- that lives in
linkedin_parser.py. Keeping them separate means the email format can change
without touching the auth/transport code.
"""

import base64
import os

import google_auth_httplib2
import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# gmail.readonly to read alert emails; gmail.send to email the ranked summary
# back to yourself. If you change these, re-run the auth flow (the existing
# token won't carry the new scope).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_service(credentials_file, token_file):
    """Return an authenticated Gmail API service object.

    On first run this opens a browser for you to grant access, then writes the
    resulting token to ``token_file`` so subsequent runs are non-interactive.
    The token is refreshed automatically when it expires.
    """
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        # A token issued before gmail.send was added won't carry that scope;
        # force re-auth so sending works.
        if creds and not creds.has_scopes(SCOPES):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Gmail credentials not found at '{credentials_file}'.\n"
                    "Download the OAuth client file from Google Cloud Console "
                    "(see README, 'Setting up Gmail API credentials') and save "
                    "it to that path."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

    return build("gmail", "v1", http=_authorized_http(creds), cache_discovery=False)


def _authorized_http(creds):
    """Build an authorized httplib2 transport that trusts the right CA bundle.

    The google-api-python-client uses httplib2, which (unlike requests) does not
    read the SSL_CERT_FILE / REQUESTS_CA_BUNDLE environment variables. In
    environments that route traffic through a TLS-inspecting egress proxy, that
    proxy's CA lives in a custom bundle and httplib2 must be told about it
    explicitly. On a normal machine these vars are unset and httplib2 falls back
    to its default trust store, so this is a no-op there.
    """
    ca_certs = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca_certs and os.path.exists(ca_certs):
        base_http = httplib2.Http(ca_certs=ca_certs)
    else:
        base_http = httplib2.Http()
    return google_auth_httplib2.AuthorizedHttp(creds, http=base_http)


def search_message_ids(service, query, max_results=50):
    """Return a list of message ids matching ``query`` (newest first).

    ``query`` uses Gmail search syntax, e.g.
    "from:jobalerts-noreply@linkedin.com after:1717200000".
    """
    ids = []
    page_token = None
    while True:
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=min(100, max_results - len(ids)),
                pageToken=page_token,
            )
            .execute()
        )
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= max_results:
            break
    return ids[:max_results]


def get_message(service, msg_id):
    """Fetch the full message resource for ``msg_id``."""
    return (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )


def get_profile_email(service):
    """Return the authenticated account's own email address."""
    return service.users().getProfile(userId="me").execute().get("emailAddress", "")


def send_email(service, to_addr, subject, html_body, text_body=""):
    """Send a multipart (text + HTML) email from the authenticated account."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    message = MIMEMultipart("alternative")
    message["To"] = to_addr
    message["Subject"] = subject
    if text_body:
        message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return service.users().messages().send(userId="me", body={"raw": raw}).execute()


def get_header(message, name):
    """Return the value of a header (case-insensitive), or '' if absent."""
    name = name.lower()
    for header in message.get("payload", {}).get("headers", []):
        if header.get("name", "").lower() == name:
            return header.get("value", "")
    return ""


def _decode_part(data):
    """Decode a base64url-encoded message part body to text."""
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def get_html_body(message):
    """Extract the HTML body of a message, falling back to plain text.

    Gmail messages are a tree of MIME parts. We walk it depth-first, preferring
    text/html (LinkedIn alerts are HTML), and fall back to text/plain if that's
    all that exists.
    """
    html_body = []
    plain_body = []

    def walk(part):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/html" and data:
            html_body.append(_decode_part(data))
        elif mime == "text/plain" and data:
            plain_body.append(_decode_part(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(message.get("payload", {}))

    if html_body:
        return "".join(html_body), "html"
    if plain_body:
        return "".join(plain_body), "plain"
    return "", "none"
