from collections.abc import Callable
from typing import TYPE_CHECKING

from bot.controllers.controller import Controller
from sc2.units import Point2, Unit

if TYPE_CHECKING:
    from bot.main import WilldZergBot


class ControllerData:
    def __init__(self, ai: "WilldZergBot", controllers: list[Controller]):
        self.interfaces: dict[str, Callable[...]] = {}

        for controller in controllers:
            interfaces = controller.interfaces()
            # Check there are no repeats
            assert not any(k in self.interfaces for k in interfaces)
            self.interfaces.update(interfaces)

        # Check that we're not missing any interfaces
        local_funcs = [
            d
            for d in dir(ControllerData)
            if isinstance(getattr(ControllerData, d), Callable | property)
        ]
        for interface in self.interfaces:
            assert interface in local_funcs
            local_funcs.remove(interface)

        # And that we don't have any interfaces that shouldn't be defined
        assert not any(f for f in local_funcs if not f.startswith("_"))

    # AttackController interfaces
    @property
    def attacks(self) -> int:
        return self.interfaces["attacks"]()

    def trigger_attack(self, iteration: int) -> None:
        return self.interfaces["trigger_attack"](iteration)

    def set_under_attack_timer(self, timer: int) -> None:
        return self.interfaces["set_under_attack_timer"](timer)

    @property
    def under_attack_timer(self) -> int:
        return self.interfaces["under_attack_timer"]()

    @property
    def attacker_com(self) -> Point2:
        return self.interfaces["attacker_com"]()

    @property
    def ling_micro_interval(self) -> int:
        return self.interfaces["ling_micro_interval"]()

    @property
    def skip_first_attack(self) -> bool:
        return self.interfaces["skip_first_attack"]()

    # DefendController interfaces
    @property
    def defend_point(self) -> Point2:
        return self.interfaces["defend_point"]()

    # ScoutController interfaces
    @property
    def enemy_nat_taken(self) -> bool:
        return self.interfaces["enemy_nat_taken"]()

    def scout_for_natural(self) -> None:
        return self.interfaces["scout_for_natural"]()

    def cancel_scout_for_natural(self) -> None:
        return self.interfaces["cancel_scout_for_natural"]()

    # InjectController interfaces
    def add_inject_queen(self, queen: Unit) -> bool:
        return self.interfaces["add_inject_queen"](queen)

    def remove_inject_queen(self, queen: Unit) -> None:
        return self.interfaces["remove_inject_queen"](queen)

    # CreepController interfaces
    def add_creep_queen(self, queen: Unit) -> bool:
        return self.interfaces["add_creep_queen"](queen)

    def remove_creep_queen(self, queen: Unit) -> None:
        return self.interfaces["remove_creep_queen"](queen)

    # QueenController interfaces
    def assign_queen_default(self, queen: Unit) -> None:
        return self.interfaces["assign_queen_default"](queen)
