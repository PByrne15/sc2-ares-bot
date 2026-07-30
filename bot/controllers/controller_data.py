from typing import TYPE_CHECKING, Callable

from sc2.units import Point2

from bot.controllers.controller import Controller

if TYPE_CHECKING:
    from bot.main import WilldZergBot


class ControllerData:
    def __init__(self, ai: "WilldZergBot", controllers: list[Controller]):
        self.interfaces: dict[str, Callable[...]] = {}

        for controller in controllers:
            interfaces = controller.interfaces()
            # Check there are no repeats
            assert not any(
                k in self.interfaces for k in interfaces)
            self.interfaces.update(interfaces)

        # Check that we're not missing any interfaces
        local_funcs = [d for d in dir(ControllerData) if isinstance(
            getattr(ControllerData, d), Callable | property)]
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
