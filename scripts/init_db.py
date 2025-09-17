# scripts/init_db.py
from models.branch_model import create_tables
from config import DB_PATH

if __name__ == "__main__":
    print(f"Creating tables in {DB_PATH} ...")
    create_tables()
    print("Done ✅")
