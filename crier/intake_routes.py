"""HTTP boundary for reviewed receipts and trusted Sentinel fill observers."""
import hmac
from fastapi import APIRouter, Depends, Header, HTTPException

from .intake import CONTRACT_VERSION, Confirmation, IncomingFill, Intake, IntakeConflict, ReceiptInput


CAPABILITIES = {
    "contract_version": CONTRACT_VERSION,
    "brokers": [
        {"id": "webull", "name": "Webull", "mode": "experimental_api",
         "description": "Official account event stream. Capture-only until baseline and manual-app fill coverage are verified."},
        {"id": "tradier", "name": "Tradier", "mode": "experimental_api",
         "description": "Read-only current-session order polling. Capture-only until verified; order update time, no previous-day backfill."},
        {"id": "robinhood", "name": "Robinhood", "mode": "manual_receipt",
         "description": "Paste a receipt and confirm its fields. Automatic ordinary-account/iPhone monitoring is not connected."},
        {"id": "other", "name": "Other broker", "mode": "manual_receipt",
         "description": "Reviewed receipts or a verified observer using the Crier fill contract. No universal app screen or notification reader."},
    ],
}


def intake_router(config, store, console_auth):
    router = APIRouter(prefix="/api")
    intake = Intake(store)

    def source_auth(x_api_key: str = Header(default="")):
        if not config.intake_key:
            raise HTTPException(503, "Event intake is disabled; configure a dedicated CRIER_INTAKE_KEY")
        if not hmac.compare_digest(x_api_key.encode(), config.intake_key.encode()):
            raise HTTPException(401, "Invalid observer key")

    def translate(call):
        try:
            return call()
        except IntakeConflict as exc:
            raise HTTPException(409, str(exc))
        except KeyError:
            raise HTTPException(404, "Receipt not found")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.get("/capabilities", dependencies=[Depends(console_auth)])
    def capabilities():
        return CAPABILITIES

    @router.get("/intake/schema", dependencies=[Depends(source_auth)])
    def schema():
        return {"contract_version": CONTRACT_VERSION, "schema": IncomingFill.model_json_schema(),
                "semantics": "Cumulative order quantities and weighted average price. Accepted means durably recorded, not delivered. Retry with identical event_id and body."}

    @router.post("/intake/fills", dependencies=[Depends(source_auth)])
    def incoming(event: IncomingFill, idempotency_key: str = Header(default="")):
        if not config.intake_verified:
            raise HTTPException(503, "Validate source coverage and fill semantics, then enable CRIER_INTAKE_VERIFIED")
        if idempotency_key and idempotency_key != event.event_id:
            raise HTTPException(409, "Idempotency-Key must match event_id")
        return translate(lambda: intake.accept(event))

    @router.get("/receipts", dependencies=[Depends(console_auth)])
    def receipts():
        return intake.list_receipts()

    @router.post("/receipts", dependencies=[Depends(console_auth)])
    def capture(value: ReceiptInput):
        return intake.capture(value.text, value.broker, value.environment)

    @router.post("/receipts/{key}/confirm", dependencies=[Depends(console_auth)])
    def confirm(key: str, value: Confirmation):
        return translate(lambda: intake.confirm(key, value.snapshot))

    @router.post("/receipts/{key}/reject", dependencies=[Depends(console_auth)])
    def reject(key: str):
        return translate(lambda: intake.reject(key))

    return router
