from pathlib import Path
import uvicorn
from app.config import SERVER_HOST, SERVER_PORT

if __name__ == "__main__":
    app_dir = Path(__file__).resolve().parent / "app"
    uvicorn.run(
        "app.main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False
    )
