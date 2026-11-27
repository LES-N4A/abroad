"""Database backup script for production."""
import os
import subprocess
from datetime import datetime


def backup_database():
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.environ.get("BACKUP_DIR", "./backups")
    os.makedirs(backup_dir, exist_ok=True)

    # For PostgreSQL
    if os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        db_url = os.environ["DATABASE_URL"]
        backup_file = f"{backup_dir}/abroad_backup_{timestamp}.sql"

        # Use pg_dump
        result = subprocess.run(
            ["pg_dump", db_url, "-f", backup_file],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print(f"✓ Database backed up to {backup_file}")

            # Compress backup
            subprocess.run(["gzip", backup_file])
            print(f"✓ Backup compressed to {backup_file}.gz")
        else:
            print(f"✗ Backup failed: {result.stderr}")

    # For SQLite
    else:
        db_path = os.environ.get("DATABASE_PATH", "instance/abroad.sqlite")
        if os.path.exists(db_path):
            backup_file = f"{backup_dir}/abroad_backup_{timestamp}.sqlite"
            subprocess.run(["cp", db_path, backup_file])
            subprocess.run(["gzip", backup_file])
            print(f"✓ Database backed up to {backup_file}.gz")


if __name__ == "__main__":
    backup_database()
