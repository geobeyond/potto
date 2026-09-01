"""Internal schemas for Potto."""

import dataclasses
import logging

from .. import constants
from .base import Link

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int
    total: int


@dataclasses.dataclass(frozen=True)
class PaginationContext:
    limit: int
    number_matched: int
    number_returned: int
    offset: int

    def get_links(
        self,
        base_url: str,
        target_media_type: str = constants.MEDIA_TYPE_JSON,
        additional_query_params: dict[str, str] | None = None,
    ) -> list[Link]:
        additional = (
            "&".join(
                f"{k}={','.join(str(x) for x in v) if isinstance(v, (list, tuple)) else v}"
                for k, v in additional_query_params.items()
            )
            if additional_query_params
            else None
        )
        result = []
        if self.offset > 0:
            prev_offset = max(0, self.offset - self.limit)
            result.append(
                Link(
                    type=target_media_type,
                    rel="prev",
                    href=f"{base_url}?offset={prev_offset}{f'&{additional}' if additional else ''}",
                    title="Previous page of this resultset",
                )
            )
        if self.number_matched > self.offset + self.limit:
            next_offset = self.offset + self.limit
            result.append(
                Link(
                    type=target_media_type,
                    rel="next",
                    href=f"{base_url}?offset={next_offset}{f'&{additional}' if additional else ''}",
                    title="Next page of this resultset",
                )
            )
        return result
