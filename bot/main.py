import math
import random
from typing import TYPE_CHECKING

from cython_extensions.general_utils import cy_unit_pending
from cython_extensions.units_utils import cy_closest_to, cy_find_units_center_mass
import numpy as np

from ares import AresBot
from ares.consts import (
    BURROWED_ALIAS,
    CHANGELING_TYPES,
    COMMON_UNIT_IGNORE_TYPES,
    LOSS_MARGINAL_OR_WORSE,
    VICTORY_CLOSE_OR_BETTER,
    EngagementResult,
    UnitRole
)
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.ids.upgrade_id import UpgradeId
from sc2.units import Unit, Units

from ares.behaviors.macro import (
    AutoSupply,
    BuildStructure,
    GasBuildingController,
    Mining,
    BuildWorkers,
    SpawnController,
    MacroPlan,
    TechUp,
    UpgradeController
)
from ares.behaviors.combat.combat_maneuver import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    MoveToSafeTarget,
    KeepUnitSafe
)
from ares.behaviors.combat.group import (
    KeepGroupSafe,
    AMoveGroup
)

from bot.controllers import (
    AttackController,
    DefendController,
    ScoutController
)
from bot.controllers.controller_data import ControllerData
from bot.expansion_controller import FixedExpansionController
from bot.helpers.map_fixes import apply_map_fixes

if TYPE_CHECKING:
    from bot.controllers.controller import Controller


class WilldZergBot(AresBot):
    """Main bot class that handles the game logic."""

    def __init__(self):
        super().__init__()

    async def setup_controllers(self) -> None:
        # The order of this list will be the order controllers are run in
        # so if there are dependencies make sure they're in the right order
        self.controller_list: list[Controller] = []

        self.controller_list.append(ScoutController(self))
        self.controller_list.append(AttackController(self))
        self.controller_list.append(DefendController(self))

        self.controllers = ControllerData(self, self.controller_list)

        for controller in self.controller_list:
            await controller.start()

    async def on_start(self) -> None:
        apply_map_fixes(self)
        await super(WilldZergBot, self).on_start()
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        print("Game started")

        natural_expansion_location = min(
            self.mediator.get_own_expansions, key=lambda t: t[1])[0]

        path = self.mediator.get_map_data_object.pathfind(
            natural_expansion_location, self.enemy_start_locations[0], self.mediator.get_ground_grid)
        # If there is no path from expansion to the enemy then this bot won't work
        assert path

        self.expansion_entrance = path[10]
        await self.setup_controllers()

        self.completed_researches: set[UpgradeId] = set()

    def _position_facing_enemy_base(self, point: Point2):
        path = self.mediator.get_map_data_object.pathfind(
            point, self.enemy_start_locations[0], self.mediator.get_ground_grid
        )
        if not path:
            return self.expansion_entrance
        if len(path) < 10:
            return path[-1]

        return path[10]

    def select_target(self) -> Point2:
        if self.enemy_structures:
            return self.enemy_structures.closest_to(self.townhalls.first.position).position
        return self.enemy_start_locations[0]

    async def on_step(self, iteration: int) -> None:
        await super(WilldZergBot, self).on_step(iteration)
        """
        This code runs continually throughout the game
        Populate this function with whatever your bot should do!
        """
        if (self.time == 270):
            self.controllers.scout_for_natural()
        if self.supply_workers >= 35 and not self.controllers.enemy_nat_taken:
            if not self.actual_iteration % 50:
                print(
                    f"Cutting workers as no natural scouted @ {self.time_formatted}")
            self.controllers.set_under_attack_timer(1)

        for controller in self.controller_list:
            await controller.update()

        # if not self.actual_iteration % 50:
        #     print(
        #         f"Calling _macro with {self.controllers.under_attack_timer=}")
        await self._macro(bool(self.controllers.under_attack_timer))

        if self.controllers.under_attack_timer:
            # if self.combat_controller.under_attack_timer == 100:
            #     print(f"Under attack @ {self.time_formatted}")
            timer = self.controllers.under_attack_timer
            self.controllers.set_under_attack_timer(timer - 1)

    async def _macro(self, under_attack: bool) -> None:
        macro_plan = MacroPlan()
        workers_per_gas = 3
        if ((self.pending_or_complete_upgrade(UpgradeId.ZERGGROUNDARMORSLEVEL3)
                 and self.pending_or_complete_upgrade(UpgradeId.ZERGMELEEWEAPONSLEVEL3)
                 )
                    or (self.minerals < 100 and self.vespene > 300)
                ):
            workers_per_gas = 1
        self.register_behavior(
            Mining(mineral_boost=True, workers_per_gas=workers_per_gas))

        if self.structures(UnitTypeId.SPAWNINGPOOL) and self.supply_workers == 14:
            self.register_behavior(GasBuildingController(to_count=1))

        if not self.townhalls:
            return
        hq = next((th for th in self.townhalls if th.position ==
                  self.start_location), None)
        if not hq:
            hq = self.townhalls.first

        if self.minerals > 150:
            self.register_behavior(BuildStructure(
                base_location=self.mediator.get_behind_mineral_positions(
                    th_pos=hq.position)[0],
                structure_id=UnitTypeId.SPAWNINGPOOL, to_count=1
            ))

        if (self.structures(UnitTypeId.SPAWNINGPOOL) and self.supply_used == 14
                    and (self.units(UnitTypeId.OVERLORD).amount + self.already_pending(UnitTypeId.OVERLORD)) < 2
                    and self.can_afford(UnitTypeId.OVERLORD)
                ):
            self.larva.first.build(UnitTypeId.OVERLORD)
        elif self.structures(UnitTypeId.SPAWNINGPOOL).ready:
            macro_plan.add(AutoSupply(base_location=self.start_location))

        try:
            if not self.structures(UnitTypeId.SPAWNINGPOOL):
                worker_count = 14
            elif not self.controllers.attacks:
                worker_count = 16
            elif self.controllers.attacks == 1:
                worker_count = min(self.supply_used -
                                   2 * int(math.log(self.supply_used)) -
                                   self.units(UnitTypeId.QUEEN).amount * 2,
                                   self.townhalls.amount * 19,
                                   64)
            else:
                worker_count = min(self.supply_used -
                                   16 * int(math.log(self.supply_used)),
                                   80)
        except ValueError:
            # We have already lost at this point but catch this to avoid crashing
            worker_count = 14

        # After first attack stop production until we have 3 hatcheries
        if self.controllers.attacks != 1 or self.townhalls.amount >= 3 or under_attack:
            if self.supply_workers >= worker_count or under_attack:
                macro_plan.add(SpawnController(army_composition_dict={
                    UnitTypeId.ZERGLING: {"proportion": 1.0, "priority": 0}}))
            else:
                macro_plan.add(BuildWorkers(to_count=worker_count))

        if (self.can_afford(UpgradeId.ZERGLINGMOVEMENTSPEED)
            and self.already_pending(UnitTypeId.LAIR) == 0.0
                and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.completed_researches):
            sp = self.structures(UnitTypeId.SPAWNINGPOOL).ready
            if sp:
                self.research(UpgradeId.ZERGLINGMOVEMENTSPEED)

        if (self.already_pending_upgrade(UpgradeId.ZERGMELEEWEAPONSLEVEL1) > 0.0
                    and self.already_pending_upgrade(UpgradeId.ZERGGROUNDARMORSLEVEL1) > 0.0
                    and self.structures(UnitTypeId.SPAWNINGPOOL).ready
                ):
            # await self.chat_send("Upgrading to Lair", True)
            self.register_behavior(
                TechUp(base_location=hq.position, desired_tech=UnitTypeId.LAIR))

        queens = self.units(UnitTypeId.QUEEN)
        for base in self.townhalls:
            if not queens or self.units(UnitTypeId.QUEEN).closest_distance_to(base) > 8:
                if (self.can_afford(UnitTypeId.QUEEN)
                            and base.is_ready
                            and base.is_idle
                            and self.structures(UnitTypeId.SPAWNINGPOOL).ready
                            and queens.amount < 10
                        ):
                    # await self.chat_send("Training Queen", True)
                    base.train(UnitTypeId.QUEEN)
            else:
                queen = queens.closest_to(base)
                if queen.energy >= 25:
                    queen(AbilityId.EFFECT_INJECTLARVA, base)

        if (self.controllers.attacks
                    and not UpgradeId.ZERGGROUNDARMORSLEVEL1 in self.completed_researches
                    and self.townhalls.amount >= 3
                    and (self.units(UnitTypeId.QUEEN).amount + self.already_pending(UnitTypeId.QUEEN) >= 3)
                ):
            self.register_behavior(GasBuildingController(to_count=2))
            self.register_behavior(BuildStructure(
                base_location=hq.position, structure_id=UnitTypeId.EVOLUTIONCHAMBER, to_count=2))

            researches = [
                UpgradeId.ZERGMELEEWEAPONSLEVEL1,
                UpgradeId.ZERGGROUNDARMORSLEVEL1,
                UpgradeId.ZERGMELEEWEAPONSLEVEL2,
            ]

            self.register_behavior(UpgradeController(
                researches, hq.position, False))

            # for evo in self.structures(UnitTypeId.EVOLUTIONCHAMBER).ready:
            #     if evo.is_idle:
            #         for research in researches:
            #             if (self.can_afford(research)
            #                 and not research in self.completed_researches
            #                     and self.already_pending_upgrade(research) == 0):
            #                 await self.chat_send(f"Researching {research}", True)
            #                 evo.research(research)
            #                 break

        if UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.completed_researches:
            self.register_behavior(
                TechUp(base_location=hq.position, desired_tech=UnitTypeId.HIVE))
            self.register_behavior(BuildStructure(
                base_location=hq.position, structure_id=UnitTypeId.EVOLUTIONCHAMBER, to_count=2))

            researches = [
                UpgradeId.ZERGMELEEWEAPONSLEVEL2,
                UpgradeId.ZERGGROUNDARMORSLEVEL2,
                UpgradeId.ZERGMELEEWEAPONSLEVEL3,
                UpgradeId.ZERGGROUNDARMORSLEVEL3,
                UpgradeId.ZERGLINGATTACKSPEED
            ]

            self.register_behavior(UpgradeController(
                researches, hq.position, False))
            # for evo in self.structures(UnitTypeId.EVOLUTIONCHAMBER).ready:
            #     if evo.is_idle:
            #         for research in researches:
            #             if (self.can_afford(research)
            #                 and not research in self.completed_researches
            #                     and self.already_pending_upgrade(research) == 0):
            #                 await self.chat_send(f"Researching {research}", True)
            #                 evo.research(research)
            #                 break

            # if (UpgradeId.ZERGLINGATTACKSPEED not in self.completed_researches
            #         and self.already_pending(UnitTypeId.LAIR) == 0.0):
            #     if sp := self.structures(UnitTypeId.SPAWNINGPOOL):
            #         sp.ready.first.research(UpgradeId.ZERGLINGATTACKSPEED)

        if self.time < 900:
            if self.minerals > 1000:
                max_pending = 10
            elif self.townhalls.amount == 1:
                max_pending = 1
            else:
                max_pending = 2
            self.register_behavior(
                FixedExpansionController(to_count=8, max_pending=max_pending))
        else:
            self.register_behavior(
                FixedExpansionController(to_count=20, max_pending=10))

        if self.minerals > 2000:
            self.register_behavior(BuildStructure(
                base_location=random.choice(self.townhalls).position,
                structure_id=UnitTypeId.HATCHERY,
                to_count=15,
                max_on_route=1))

        self.register_behavior(macro_plan)

    async def on_end(self, game_result: Result) -> None:
        await super(WilldZergBot, self).on_end(game_result)
        """
        This code runs once at the end of the game
        Do things here after the game ends
        """
        print("Game ended.")

        # async def on_building_construction_complete(self, unit: Unit) -> None:
        #     await super(MyBot, self).on_building_construction_complete(unit)
        #
        #     # custom on_building_construction_complete logic here ...
        #
    async def on_unit_created(self, unit: Unit) -> None:
        await super(WilldZergBot, self).on_unit_created(unit)

        if unit.type_id == UnitTypeId.ZERGLING:
            self.mediator.assign_role(tag=unit.tag, role=UnitRole.DEFENDING)

    # async def on_unit_destroyed(self, unit_tag: int) -> None:
    #     await super(MyBot, self).on_unit_destroyed(unit_tag)
    #
    #     # custom on_unit_destroyed logic here ...

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        await super(WilldZergBot, self).on_unit_took_damage(unit, amount_damage_taken)

        if any(unit.position.distance_to(th) <= 10 for th in self.townhalls):
            self.controllers.set_under_attack_timer(100)

    async def on_upgrade_complete(self, upgrade: UpgradeId) -> None:
        await super(WilldZergBot, self).on_upgrade_complete(upgrade)

        if upgrade in [
            UpgradeId.ZERGLINGMOVEMENTSPEED,
            UpgradeId.ZERGGROUNDARMORSLEVEL1,
            UpgradeId.ZERGGROUNDARMORSLEVEL2,
            UpgradeId.ZERGGROUNDARMORSLEVEL3
        ]:
            self.controllers.trigger_attack(self.actual_iteration)

        self.completed_researches.add(upgrade)
