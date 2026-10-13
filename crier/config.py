from dataclasses import dataclass
import os
from pathlib import Path
import secrets
from .delivery import validate_webhook


@dataclass
class Config:
    data_dir: Path = Path("data")
    token: str = ""
    webhook: str = ""
    delivery_enabled: bool = False
    webull_verified: bool = False

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.token:
            path = self.data_dir / "access-token"
            try:
                with path.open("x", encoding="utf-8") as f:
                    os.chmod(path, 0o600)
                    f.write(secrets.token_urlsafe(32))
            except FileExistsError: pass
            self.token = path.read_text(encoding="utf-8").strip()
        if len(self.token) < 32: raise ValueError("CRIER_ACCESS_TOKEN must contain at least 32 characters")
        if self.webhook: validate_webhook(self.webhook)
        if self.delivery_enabled and (not self.webhook or not self.webull_verified):
            raise ValueError("Delivery requires a Discord webhook and CRIER_WEBULL_VERIFIED=true after manual-app coverage and fill semantics checks")

    @classmethod
    def from_env(cls):
        return cls(data_dir=Path(os.getenv("CRIER_DATA_DIR", "data")), token=os.getenv("CRIER_ACCESS_TOKEN", ""),
            webhook=os.getenv("DISCORD_WEBHOOK_URL", ""),
            delivery_enabled=os.getenv("CRIER_DELIVERY_ENABLED", "false").lower() == "true",
            webull_verified=os.getenv("CRIER_WEBULL_VERIFIED", "false").lower() == "true")
