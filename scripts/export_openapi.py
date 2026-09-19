"""Export the application contract without connecting to PostgreSQL or Docker."""

import json

from app.config import Settings
from app.main import create_app

if __name__ == "__main__":
    app = create_app(Settings(database_url="postgresql+psycopg://schema@invalid/schema"))
    print(json.dumps(app.openapi(), sort_keys=True))
