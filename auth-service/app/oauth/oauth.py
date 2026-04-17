from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()

oauth.register(
  "google",
  client_id=settings.GOOGLE_CLIENT_ID,
  client_secret=settings.GOOGLE_CLIENT_SECRET,
  client_kwargs={"scope": "openid email profile"},
  server_metadata_url="https://accounts.google.com/.well-known/openid-configuration"
)