import random

from ares import AresBot
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.ids.upgrade_id import UpgradeId
from sc2.units import Units

from ares.behaviors.macro import (
    AutoSupply,
    BuildStructure,
    GasBuildingController,
    Mining,
    BuildWorkers,
    SpawnController,
    MacroPlan
)

from .expansion_controller import FixedExpansionController


class WilldZergBot(AresBot):
    """Main bot class that handles the game logic."""

    def __init__(self):
        super().__init__()

    async def on_start(self) -> None:
        await super(WilldZergBot, self).on_start()
        """
        This code runs once at the start of the game
        Do things here before the game starts
        """
        print("Game started")

        self.attacks = 0
        self.trigger_attack = False

        self.completed_researches = set()

        self.count = 0

    def select_target(self) -> Point2:
        if self.enemy_structures:
            return random.choice(self.enemy_structures).position
        return self.enemy_start_locations[0]

    async def on_step(self, iteration: int) -> None:
        await super(WilldZergBot, self).on_step(iteration)
        """
        This code runs continually throughout the game
        Populate this function with whatever your bot should do!
        """
        self.count += 1
        await self._macro()

        if self.trigger_attack:
            self.attacks += 1
            for ling in self.units(UnitTypeId.ZERGLING):
                if ling.is_idle:
                    ling.attack(self.select_target())
            self.trigger_attack = False
            await self.chat_send(f"Sending timing attack number {self.attacks}", True)

        if self.supply_used == 200 and self.attacks >= 2:
            for ling in self.units(UnitTypeId.ZERGLING):
                if ling.is_idle:
                    target = self.select_target()
                    if target == self.enemy_start_locations[0]:
                        target = random.choice(self.expansion_locations_list)
                    ling.attack(target)
            self.trigger_attack = False

    async def _macro(self) -> None:

        macro_plan = MacroPlan()
        self.register_behavior(Mining(mineral_boost=True))

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
                base_location=hq.position, structure_id=UnitTypeId.SPAWNINGPOOL, to_count=1))

        if (self.structures(UnitTypeId.SPAWNINGPOOL) and self.supply_used == 14
                and (self.units(UnitTypeId.OVERLORD).amount + self.already_pending(UnitTypeId.OVERLORD)) < 2):
            self.larva.first.build(UnitTypeId.OVERLORD)
        elif self.structures(UnitTypeId.SPAWNINGPOOL).ready:
            macro_plan.add(AutoSupply(base_location=self.start_location))

        if not self.structures(UnitTypeId.SPAWNINGPOOL):
            worker_count = 14
        elif not self.attacks:
            worker_count = 16
        elif self.attacks == 1:
            worker_count = 64
        else:
            worker_count = max(min(self.townhalls.amount * 22,
                                   3 * self.supply_used // 4, 80),
                               22)

        if self.supply_workers >= worker_count:
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

        if self.can_afford(UnitTypeId.LAIR) and (
                self.structures(UnitTypeId.LAIR).amount +
                self.structures(UnitTypeId.HIVE).amount +
                self.already_pending(UnitTypeId.LAIR) +
                self.already_pending(UnitTypeId.HIVE)
        ) < 1 and hq and (
            self.already_pending_upgrade(
                UpgradeId.ZERGMELEEWEAPONSLEVEL1) > 0.0
            and self.already_pending_upgrade(UpgradeId.ZERGGROUNDARMORSLEVEL1) > 0.0
        ) and self.structures(UnitTypeId.SPAWNINGPOOL).ready:
            await self.chat_send("Upgrading to Lair")
            hq.build(UnitTypeId.LAIR)

        queens = self.units(UnitTypeId.QUEEN)
        for base in self.townhalls:
            if not queens or self.units(UnitTypeId.QUEEN).closest_distance_to(base) > 10:
                if (self.can_afford(UnitTypeId.QUEEN)
                            and base.is_ready
                            and base.is_idle
                            and self.structures(UnitTypeId.SPAWNINGPOOL).ready
                        ):
                    # await self.chat_send("Training Queen")
                    base.train(UnitTypeId.QUEEN)
            else:
                queen = queens.closest_to(base)
                if queen.energy >= 25:
                    queen(AbilityId.EFFECT_INJECTLARVA, base)

        if self.attacks and not UpgradeId.ZERGGROUNDARMORSLEVEL1 in self.completed_researches:
            self.register_behavior(GasBuildingController(to_count=2))
            self.register_behavior(BuildStructure(
                base_location=hq.position, structure_id=UnitTypeId.EVOLUTIONCHAMBER, to_count=2))

            researches = [
                UpgradeId.ZERGMELEEWEAPONSLEVEL1,
                UpgradeId.ZERGGROUNDARMORSLEVEL1,
                UpgradeId.ZERGMELEEWEAPONSLEVEL2,
            ]
            for evo in self.structures(UnitTypeId.EVOLUTIONCHAMBER).ready:
                if evo.is_idle:
                    for research in researches:
                        if (self.can_afford(research)
                            and not research in self.completed_researches
                                and self.already_pending_upgrade(research) == 0):
                            await self.chat_send(f"Researching {research}")
                            evo.research(research)
                            break

        if UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.completed_researches:
            self.register_behavior(BuildStructure(
                base_location=hq.position, structure_id=UnitTypeId.INFESTATIONPIT, to_count=1))
            if (self.can_afford(UnitTypeId.HIVE)
                and self.structures(UnitTypeId.HIVE).amount +
                    self.already_pending(UnitTypeId.HIVE) < 1):
                if hq:
                    # await self.chat_send("Upgrading to Hive")
                    hq.build(UnitTypeId.HIVE)

            researches = [
                UpgradeId.ZERGMELEEWEAPONSLEVEL2,
                UpgradeId.ZERGGROUNDARMORSLEVEL2,
                UpgradeId.ZERGMELEEWEAPONSLEVEL3,
                UpgradeId.ZERGGROUNDARMORSLEVEL3
            ]
            for evo in self.structures(UnitTypeId.EVOLUTIONCHAMBER).ready:
                if evo.is_idle:
                    for research in researches:
                        if (self.can_afford(research)
                            and not research in self.completed_researches
                                and self.already_pending_upgrade(research) == 0):
                            await self.chat_send(f"Researching {research}")
                            evo.research(research)
                            break

            if (UpgradeId.ZERGLINGATTACKSPEED not in self.completed_researches
                    and self.already_pending(UnitTypeId.LAIR) == 0.0):
                if sp := self.structures(UnitTypeId.SPAWNINGPOOL):
                    sp.ready.first.research(UpgradeId.ZERGLINGATTACKSPEED)

        if self.time < 900:
            self.register_behavior(
                FixedExpansionController(to_count=8, max_pending=2))
        else:
            self.register_behavior(
                FixedExpansionController(to_count=20, max_pending=10))

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
        # async def on_unit_created(self, unit: Unit) -> None:
        #     await super(MyBot, self).on_unit_created(unit)
        #
        #     # custom on_unit_created logic here ...
        #
        # async def on_unit_destroyed(self, unit_tag: int) -> None:
        #     await super(MyBot, self).on_unit_destroyed(unit_tag)
        #
        #     # custom on_unit_destroyed logic here ...
        #
        # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        #     await super(MyBot, self).on_unit_took_damage(unit, amount_damage_taken)
        #
        #     # custom on_unit_took_damage logic here ...

    async def on_upgrade_complete(self, upgrade: UpgradeId) -> None:
        await super(WilldZergBot, self).on_upgrade_complete(upgrade)

        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            self.trigger_attack = True
        if upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            self.trigger_attack = True
        if upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            self.trigger_attack = True

        self.completed_researches.add(upgrade)
