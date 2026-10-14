"""Bounded UTF-8 JSON parsing shared by write operations."""
import simplejson
from fastapi import Request
from pydantic import ValidationError

from traceai.errors import APIError

MAX_BODY_BYTES = 65536


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON object member")
        result[key] = value
    return result


async def parse_body(request: Request, model, *, reset=False):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise APIError(400 if reset else 413, "INVALID_RESET" if reset else "REQUEST_TOO_LARGE", "Request body exceeds 65536 bytes.")
        body.extend(chunk)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise APIError(400 if reset else 422, "INVALID_RESET" if reset else "INVALID_EVENT", "Compressed request bodies are unsupported.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise APIError(400 if reset else 422, "INVALID_RESET" if reset else "INVALID_EVENT", "Content-Type must be application/json.")
    try:
        payload = simplejson.loads(bytes(body).decode("utf-8"), use_decimal=True, allow_nan=False, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise APIError(400, "MALFORMED_JSON", "Request body must contain valid UTF-8 JSON.") from None
    try:
        model.model_validate(payload)
        return payload
    except (ValidationError, RecursionError):
        # Do not echo submitted fields/values, which can contain secrets or huge strings.
        raise APIError(400 if reset else 422, "INVALID_RESET" if reset else "INVALID_EVENT", "The submitted reset confirmation is invalid." if reset else "The submitted event failed validation.") from None
