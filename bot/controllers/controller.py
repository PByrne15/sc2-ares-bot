from abc import ABC
from typing import Callable


class Controller(ABC):
    async def start(self) -> None:
        ...

    async def update(self) -> None:
        ...

    def interfaces(self) -> dict[str, Callable]:
        interfaces = {}
        for func in dir(self):
            obj = getattr(self, func)
            if (isinstance(obj, Callable)
                and func not in ["start", "update", "interfaces"]
                and not func.startswith('_')
                ):
                interfaces[func] = obj

        return interfaces
