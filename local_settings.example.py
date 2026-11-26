# Copy this file to local_settings.py and fill in real values.
# local_settings.py is in .gitignore and must never be committed.

# --- Matomo ---------------------------------------------------------------
# Base URL of the Matomo installation (no trailing /index.php).
MATOMO_URL = "https://matomo.example.org"

# API token: in Matomo, Administration > Personal > Security > Auth tokens.
# A user with view access to both sites is enough.
MATOMO_TOKEN = "replace-me"

# Site IDs: Administration > Websites > Manage.
MATOMO_SITE_ID_GROUNDUP = 1
MATOMO_SITE_ID_PUZZLES = 2

# The home page exactly as Matomo records it (check www vs non-www).
MATOMO_HOME_PAGE_URL = "https://groundup.org.za/"

# --- GroundUp website API ---------------------------------------------------
# Base URL of the GroundUp API (no trailing slash). Used to list the articles
# published in a month: <GROUNDUP_API_URL>/articles/<year>/<month>/
GROUNDUP_API_URL = "https://groundup.org.za/api"
