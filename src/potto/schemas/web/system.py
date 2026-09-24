from typing import Literal

import pydantic


class WebHealthCheck(pydantic.BaseModel):
    status: Literal["ok", "error"]
    collection_manager: Literal["ok", "not-ready", "error"]
    internal_broker: Literal["ok", "error"]
