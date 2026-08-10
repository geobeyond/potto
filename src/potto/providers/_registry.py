import inspect
from collections.abc import (
    Awaitable,
    Callable,
)

from typing import (
    cast,
    Generic,
    ParamSpec,
    TypeVar,
)


P = ParamSpec("P")
T = TypeVar("T")


def _to_async(fn: Callable[P, T]) -> Callable[P, Awaitable[T]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return fn(*args, **kwargs)

    return wrapper


class ProviderRegistry(Generic[P, T]):
    _factories: dict[str, Callable[P, Awaitable[T]]]

    def __init__(self) -> None:
        self._factories = {}

    def register(
        self, name: str, factory: Callable[P, T] | Callable[P, Awaitable[T]]
    ) -> None:
        if inspect.iscoroutinefunction(factory):
            self._factories[name] = cast(Callable[P, Awaitable[T]], factory)
        else:
            self._factories[name] = _to_async(cast(Callable[P, T], factory))

    def get(self, name: str) -> Callable[P, Awaitable[T]] | None:
        return self._factories.get(name)
