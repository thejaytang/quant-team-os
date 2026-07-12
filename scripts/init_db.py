from app.db.session import SessionLocal, init_db
from app.services.connections import seed_connections


def main() -> None:
    init_db()
    with SessionLocal() as db:
        seed_connections(db)
        db.commit()


if __name__ == "__main__":
    main()

