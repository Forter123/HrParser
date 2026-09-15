"""Create or update an HR user. Usage:
python scripts/create_user.py user@company.com "Full Name" secretpassword
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    email, name, password = sys.argv[1], sys.argv[2], sys.argv[3]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user:
            user.password_hash = hash_password(password)
            user.name = name
            print(f"Updated existing user {email}")
        else:
            user = User(email=email, name=name, password_hash=hash_password(password))
            db.add(user)
            print(f"Created user {email}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
