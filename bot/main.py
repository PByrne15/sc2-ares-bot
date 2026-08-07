import cProfile
import pstats
from typing import TYPE_CHECKING

from ares import AresBot
from ares.consts import (
    UnitRole,
)
from bot.controllers import (
    AttackController,
    CreepController,
    DefendController,
    InjectController,
    MacroController,
    QueenController,
    ScoutController,
)
from bot.controllers.controller_data import ControllerData
from bot.helpers.map_fixes import apply_map_fixes
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.units import Unit

if TYPE_CHECKING:
    from bot.controllers.controller import Controller


ENABLE_PERFORMANCE_PROFILING = False


class WilldZergBot(AresBot):
    """Main bot class that handles the game logic."""

    def __init__(self):
        super().__init__()

        self._profiler = cProfile.Profile()
        if ENABLE_PERFORMANCE_PROFILING:
            self._profiler.enable()

    async def setup_controllers(self) -> None:
        # The order of this list will be the order controllers are run in
        # so if there are dependencies make sure they're in the right order
        self.controller_list: list[Controller] = []

        self.controller_list.append(ScoutController(self))
        self.controller_list.append(AttackController(self))
        self.controller_list.append(DefendController(self))
        self.controller_list.append(InjectController(self))
        self.controller_list.append(CreepController(self))
        self.controller_list.append(QueenController(self))
        self.controller_list.append(MacroController(self))

        self.controllers = ControllerData(self, self.controller_list)

        for controller in self.controller_list:
            await controller.start()

    async def on_start(self) -> None:
        apply_map_fixes(self)
        await super().on_start()
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        print("Game started")

        natural_expansion_location = min(
            self.mediator.get_own_expansions, key=lambda t: t[1]
        )[0]

        path = self.mediator.get_map_data_object.pathfind(
            natural_expansion_location,
            self.enemy_start_locations[0],
            self.mediator.get_ground_grid,
        )
        # If there is no path from expansion to the enemy then this bot won't work
        assert path

        self.expansion_entrance = path[10]
        await self.setup_controllers()

        self.completed_researches: set[UpgradeId] = set()

    def _position_facing_enemy_base(self, point: Point2) -> Point2:
        path = self.mediator.get_map_data_object.pathfind(
            point, self.enemy_start_locations[0], self.mediator.get_ground_grid
        )
        if not path:
            return self.expansion_entrance
        if len(path) < 10:
            return path[-1]

        return path[10]

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        """
        This code runs continually throughout the game
        Populate this function with whatever your bot should do!
        """
        if self.time == 270:
            self.controllers.scout_for_natural()
        if self.supply_workers >= 35 and not self.controllers.enemy_nat_taken:
            if not self.actual_iteration % 50:
                print(f"Cutting workers as no natural scouted @ {self.time_formatted}")
            self.controllers.set_under_attack_timer(1)

        for controller in self.controller_list:
            await controller.update()

        if self.controllers.under_attack_timer:
            # if self.combat_controller.under_attack_timer == 100:
            #     print(f"Under attack @ {self.time_formatted}")
            timer = self.controllers.under_attack_timer
            self.controllers.set_under_attack_timer(timer - 1)

    async def on_end(self, game_result: Result) -> None:
        await super().on_end(game_result)
        """
        This code runs once at the end of the game
        Do things here after the game ends
        """
        print("Game ended.")
        if ENABLE_PERFORMANCE_PROFILING:
            stats = pstats.Stats(self._profiler)
            stats.sort_stats("cumulative")
            stats.print_stats(0.1)
            stats.print_stats("controllers")

        # async def on_building_construction_complete(self, unit: Unit) -> None:
        #     await super(MyBot, self).on_building_construction_complete(unit)
        #
        #     # custom on_building_construction_complete logic here ...
        #

    async def on_unit_created(self, unit: Unit) -> None:
        await super().on_unit_created(unit)

        if unit.type_id == UnitTypeId.ZERGLING:
            self.mediator.assign_role(tag=unit.tag, role=UnitRole.DEFENDING)
        if unit.type_id == UnitTypeId.QUEEN:
            self.controllers.assign_queen_default(unit)

    # async def on_unit_destroyed(self, unit_tag: int) -> None:
    #     await super(MyBot, self).on_unit_destroyed(unit_tag)
    #
    #     # custom on_unit_destroyed logic here ...

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        await super().on_unit_took_damage(unit, amount_damage_taken)

        if any(unit.position.distance_to(th) <= 10 for th in self.townhalls):
            self.controllers.set_under_attack_timer(100)

    async def on_upgrade_complete(self, upgrade: UpgradeId) -> None:
        await super().on_upgrade_complete(upgrade)

        if upgrade in [
            UpgradeId.ZERGLINGMOVEMENTSPEED,
            UpgradeId.ZERGGROUNDARMORSLEVEL1,
            UpgradeId.ZERGGROUNDARMORSLEVEL2,
            UpgradeId.ZERGGROUNDARMORSLEVEL3,
        ]:
            self.controllers.trigger_attack(self.actual_iteration)

        self.completed_researches.add(upgrade)
