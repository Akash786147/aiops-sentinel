"""Campus API replay: one route per real endpoint, behaving as the recorded application did."""
from __future__ import annotations

import random

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from campus import behaviour, biometric, directory, gatepass, shuttle
from common.telemetry import Telemetry

app = FastAPI(title="campus-api")
Telemetry("campus-api").install(app)

HANDLERS = {"gatepass": gatepass.process, "shuttle": shuttle.process, "biometric": biometric.process}
rng = random.Random()


def _route(key: str, process):
    def handler(request: Request):
        code = process(key, rng)
        return JSONResponse({"ok": code < 400, "endpoint": key}, status_code=code)
    handler.__name__ = "serve_" + "".join(c if c.isalnum() else "_" for c in key)
    return handler


for spec in sorted(behaviour.profile()["endpoints"], key=lambda e: ("{" in e["path"], -e["share"])):
    app.add_api_route(spec["path"], _route(spec["key"], HANDLERS.get(spec["journey"], directory.process)), methods=[spec["method"]])
