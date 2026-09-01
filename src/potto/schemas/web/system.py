from typing import Literal

import pydantic


class WebHealthCheck(pydantic.BaseModel):
    status: Literal["ok", "error"]
    database: Literal["ok", "outdated", "error"]
