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
    publisher_verified: bool = False
    intake_key: str = ""
    screen_upload_key: str = ""
    intake_verified: bool = False
    monitor: str = "none"
    public_pairing_enabled: bool = False

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
        if self.monitor not in ("none", "webull", "tradier", "alpaca"):
            raise ValueError("CRIER_MONITOR must be none, webull, tradier or alpaca")
        if self.intake_key and (len(self.intake_key) < 32 or self.intake_key == self.token):
            raise ValueError("CRIER_INTAKE_KEY must be a separate key with at least 32 characters")
        if self.screen_upload_key and (len(self.screen_upload_key) < 32 or self.screen_upload_key in (self.token, self.intake_key)):
            raise ValueError("CRIER_SCREEN_UPLOAD_KEY must be unique and contain at least 32 characters")
        if self.intake_verified and not self.intake_key:
            raise ValueError("Verified intake requires CRIER_INTAKE_KEY")
        if self.webhook: validate_webhook(self.webhook)
        if self.delivery_enabled and (not self.webhook or not (self.publisher_verified or self.webull_verified)):
            raise ValueError("Delivery requires a Discord webhook and CRIER_PUBLISHER_VERIFIED=true after reviewing destination and queued alerts")

    @classmethod
    def from_env(cls):
        return cls(data_dir=Path(os.getenv("CRIER_DATA_DIR", "data")), token=os.getenv("CRIER_ACCESS_TOKEN", ""),
            webhook=os.getenv("DISCORD_WEBHOOK_URL", ""),
            delivery_enabled=os.getenv("CRIER_DELIVERY_ENABLED", "false").lower() == "true",
            webull_verified=os.getenv("CRIER_WEBULL_VERIFIED", "false").lower() == "true",
            publisher_verified=os.getenv("CRIER_PUBLISHER_VERIFIED", "false").lower() == "true",
            intake_key=os.getenv("CRIER_INTAKE_KEY", ""),
            screen_upload_key=os.getenv("CRIER_SCREEN_UPLOAD_KEY", ""),
            intake_verified=os.getenv("CRIER_INTAKE_VERIFIED", "false").lower() == "true",
            monitor=os.getenv("CRIER_MONITOR", "none").lower(),
            public_pairing_enabled=os.getenv("CRIER_PUBLIC_PAIRING_ENABLED", "false").lower()=="true")
