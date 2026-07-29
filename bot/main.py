import math
import random

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

from .expansion_controller import FixedExpansionController
from .managers import ScoutManager
from .helpers.map_fixes import apply_map_fixes


class WilldZergBot(AresBot):
    """Main bot class that handles the game logic."""

    def __init__(self):
        super().__init__()

        self.scout_manager = ScoutManager(self)

    async def on_start(self) -> None:
        apply_map_fixes(self)
        await super(WilldZergBot, self).on_start()
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        print("Game started")

        self.attacks = 0
        self.trigger_attack_time = -200
        self.under_attack_timer = 0

        natural_expansion_location = min(
            self.mediator.get_own_expansions, key=lambda t: t[1])[0]

        path = self.mediator.get_map_data_object.pathfind(
            natural_expansion_location, self.enemy_start_locations[0], self.mediator.get_ground_grid)
        # If there is no path from expansion to the enemy then this bot won't work
        assert path

        self.expansion_entrance = path[10]
        self.defend_point: Point2 = self.expansion_entrance
        self.attacker_com: Point2 = self.expansion_entrance

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
            self.scout_manager.scout_for_natural()
        if self.supply_workers >= 35 and not self.scout_manager.enemy_nat_taken:
            if not self.actual_iteration % 50:
                print(
                    f"Cutting workers as no natural scouted @ {self.time_formatted}")
            self.under_attack_timer = 1
        self.scout_manager.update()

        await self._macro(bool(self.under_attack_timer))
        await self._combat_decisions()
        if self.under_attack_timer:
            # if self.under_attack_timer == 100:
            #     print(f"Under attack @ {self.time_formatted}")
            self.under_attack_timer -= 1

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
            elif not self.attacks:
                worker_count = 16
            elif self.attacks == 1:
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
        if self.attacks != 1 or self.townhalls.amount >= 3:
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

        if (self.attacks
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

    def _decide_attack_target(self, combat_sim_result: EngagementResult, unit: Unit, enemy_units: Units) -> Point2 | Unit:
        enemy_structures: Units = self.enemy_structures
        current_target = unit.order_target

        closest_unit = enemy_units.closest_to(unit) if enemy_units else None

        if (enemy_units
            and combat_sim_result in VICTORY_CLOSE_OR_BETTER
            ) and closest_unit and (not closest_unit.is_burrowed
                                    or closest_unit.type_id in [UnitTypeId.WIDOWMINEBURROWED]):
            return closest_unit.position
        elif enemy_structures:
            return cy_closest_to(unit.position, enemy_structures).position
        elif (isinstance(current_target, Point2)
              and current_target in self.expansion_locations_list
              ):
            return current_target
        elif self.is_visible(self.enemy_start_locations[0]):
            return random.choice(self.expansion_locations_list)
        else:
            return self.enemy_start_locations[0]

    async def _attack_behaviour(self) -> None:
        ground_grid: np.ndarray = self.mediator.get_ground_grid
        if self.actual_iteration == self.trigger_attack_time + 100:
            lings = self.units(UnitTypeId.ZERGLING)
            self.mediator.batch_assign_role(
                tags=set(l.tag for l in lings), role=UnitRole.ATTACKING_MAIN_SQUAD)

            print(
                f"Sending attack number {self.attacks} with {lings.amount} lings @ {self.time_formatted}")
            await self.chat_send(f"Sending timing attack number {self.attacks}", True)

        self.game_data

        if self.supply_used == 200 and self.attacks >= 2:
            self.register_behavior(
                UpgradeController([UpgradeId.OVERLORDSPEED],
                                  base_location=self.townhalls.first.position)
            )

            lings = self.mediator.get_units_from_role(
                role=UnitRole.DEFENDING, unit_type=UnitTypeId.ZERGLING)
            self.mediator.batch_assign_role(
                tags=set(l.tag for l in lings), role=UnitRole.ATTACKING_MAIN_SQUAD)

        attackers: Units = self.mediator.get_units_from_role(
            role=UnitRole.ATTACKING_MAIN_SQUAD)

        if not attackers:
            self.attacker_com = self.defend_point

            return

        com, _ = cy_find_units_center_mass(attackers, 20)
        self.attacker_com = Point2(com)

        enemy_units: Units = self.enemy_units.closer_than(30, Point2(self.attacker_com)).filter(
            lambda u: not u.is_flying
            and not u.is_cloaked
            and not u.is_hallucination
            and not u.type_id in COMMON_UNIT_IGNORE_TYPES
            and u.can_be_attacked
        )

        if not self.actual_iteration % 50 and self.time > 720:
            print(enemy_units)

        combat_sim_result: EngagementResult = self.mediator.can_win_fight(
            own_units=attackers, enemy_units=enemy_units, workers_do_no_damage=True
        )

        for attacker in attackers:
            maneuver: CombatManeuver = CombatManeuver()
            if enemy_units.closer_than(10, attacker):
                nearby_friendlies = attackers.closer_than(
                    20, enemy_units.closest_to(attacker)
                ).amount
                nearby_enemies = enemy_units.closer_than(
                    10, enemy_units.closest_to(attacker)).filter(
                    lambda u: not u.type_id in self.WORKER_TYPES).amount

            else:
                nearby_enemies = nearby_friendlies = 0
            if (combat_sim_result in LOSS_MARGINAL_OR_WORSE
                and attackers.amount < 120
                and nearby_enemies * 2 > nearby_friendlies
                ):
                maneuver.add(KeepUnitSafe(attacker, ground_grid))
            target: Point2 | Unit = self._decide_attack_target(
                combat_sim_result, attacker, enemy_units)
            maneuver.add(AMove(unit=attacker, target=target))

            self.register_behavior(maneuver)

    async def _defend_behaviour(self) -> None:
        ground_grid: np.ndarray = self.mediator.get_ground_grid
        defenders: Units = self.mediator.get_units_from_role(
            role=UnitRole.DEFENDING)
        self.defend_point: Point2
        if not self.townhalls:
            self.defend_point = self.start_location
        elif self.townhalls.amount < 3:
            self.defend_point = self.expansion_entrance
        else:
            self.defend_point = self._position_facing_enemy_base(self.townhalls.closest_to(
                self.enemy_start_locations[0]).position)

        if self.townhalls:
            close_units: Units = self.enemy_units.in_distance_of_group(
                self.townhalls, 40).filter(
                lambda u: not u.is_flying
                and not u.is_cloaked
                and not u.is_hallucination
                and not u.type_id in COMMON_UNIT_IGNORE_TYPES
                and u.can_be_attacked
            )
        else:
            # We've almost certainly lost so just have some behaviour to not crash
            close_units = self.enemy_units

        if not close_units:
            for defender in defenders:
                maneuver: CombatManeuver = CombatManeuver()
                maneuver.add(KeepUnitSafe(unit=defender, grid=ground_grid))
                maneuver.add(AMove(
                    unit=defender, target=self.defend_point))
                self.register_behavior(maneuver)
            return

        combat_sim_result: EngagementResult = self.mediator.can_win_fight(
            own_units=defenders, enemy_units=close_units
        )
        attackers = self.mediator.get_units_from_role(
            role=UnitRole.ATTACKING_MAIN_SQUAD)
        if (attackers
            and defenders.amount >= 10
            and combat_sim_result in [EngagementResult.LOSS_MARGINAL, EngagementResult.LOSS_CLOSE]
            ):
            print("Setting attackers to defend")
            self.mediator.batch_assign_role(
                tags=set(a.tag for a in attackers), role=UnitRole.DEFENDING)

        for defender in defenders:
            maneuver: CombatManeuver = CombatManeuver()
            nearby_friendlies = defenders.closer_than(
                20, close_units.closest_to(defender)
            ).amount
            nearby_enemies = close_units.closer_than(
                10, close_units.closest_to(defender)).amount
            if ((combat_sim_result in LOSS_MARGINAL_OR_WORSE or
                 defender.position.distance_to_closest(self.townhalls) > 40)
                    and nearby_enemies * 2 > nearby_friendlies):
                maneuver.add(KeepUnitSafe(unit=defender, grid=ground_grid))
            elif close_units:
                # if defender.position.distance_to_closest(self.townhalls) > 40:
                #     print(
                #         f"{combat_sim_result=}, {nearby_enemies=}, {nearby_friendlies=}")
                self.defend_point = close_units.closest_to(defender).position
            maneuver.add(AMove(
                unit=defender, target=self.defend_point))
            self.register_behavior(maneuver)

    async def _combat_decisions(self) -> None:
        await self._attack_behaviour()
        await self._defend_behaviour()

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
            self.under_attack_timer = 100

    async def on_upgrade_complete(self, upgrade: UpgradeId) -> None:
        await super(WilldZergBot, self).on_upgrade_complete(upgrade)

        if upgrade in [
            UpgradeId.ZERGLINGMOVEMENTSPEED,
            UpgradeId.ZERGGROUNDARMORSLEVEL1,
            UpgradeId.ZERGGROUNDARMORSLEVEL2,
            UpgradeId.ZERGGROUNDARMORSLEVEL3
        ]:
            self.trigger_attack_time = self.actual_iteration
            self.attacks += 1

        self.completed_researches.add(upgrade)
