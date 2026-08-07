class HealthRepository:
    def check_db(self) -> bool:
        return True

class HealthService:
    def __init__(self, repository: HealthRepository):
        self.repository = repository

    def get_health_status(self) -> dict:
        db_status = self.repository.check_db()
        return {"status": "ok" if db_status else "error", "db": db_status}
