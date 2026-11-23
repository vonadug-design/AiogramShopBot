import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

import config
from services.apirone import ApironeService

apirone_router = APIRouter(prefix="/apirone")


@apirone_router.post("/callback/{secret}")
async def apirone_callback(secret: str, request: Request):
    expected = config.APIRONE_CALLBACK_SECRET or ""
    if not expected or not secrets.compare_digest(secret, expected):
        raise HTTPException(status_code=403)
    payload = await request.json()
    invoice_id = payload.get("invoice")
    if invoice_id:
        try:
            await ApironeService.process_callback(invoice_id)
        except Exception as exception:
            logging.error(f"Apirone callback failed for {invoice_id}: {exception}")
            raise HTTPException(status_code=500)  # Apirone retries until it gets *ok*
    return PlainTextResponse("*ok*")
