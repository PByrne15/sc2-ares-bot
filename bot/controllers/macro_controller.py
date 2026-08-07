import math
import random
from typing import TYPE_CHECKING

from ares.behaviors.macro import (
    AutoSupply,
    BuildStructure,
    BuildWorkers,
    GasBuildingController,
    MacroPlan,
    Mining,
    SpawnController,
    TechUp,
    UpgradeController,
)
from bot.controllers.controller import Controller
from bot.expansion_controller import FixedExpansionController
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

if TYPE_CHECKING:
    from bot.main import WilldZergBot


class MacroController(Controller):
    def __init__(
        self,
        ai: "WilldZergBot",
    ) -> None:
        self.ai = ai

    async def start(self) -> None:
        pass

    async def update(self) -> None:
        under_attack = bool(self.ai.controllers.under_attack_timer)
        macro_plan = MacroPlan()
        workers_per_gas = 3
        if (
            self.ai.pending_or_complete_upgrade(UpgradeId.ZERGGROUNDARMORSLEVEL3)
            and self.ai.pending_or_complete_upgrade(UpgradeId.ZERGMELEEWEAPONSLEVEL3)
        ) or (self.ai.minerals < 100 and self.ai.vespene > 300):
            workers_per_gas = 1
        self.ai.register_behavior(
            Mining(mineral_boost=True, workers_per_gas=workers_per_gas)
        )

        if self.ai.structures(UnitTypeId.SPAWNINGPOOL) and self.ai.supply_workers == 14:
            self.ai.register_behavior(GasBuildingController(to_count=1))

        if not self.ai.townhalls:
            return

        hq = self.ai.townhalls.closest_to(self.ai.start_location)
        if not hq:
            hq = self.ai.townhalls.first

        if self.ai.minerals > 150:
            self.ai.register_behavior(
                BuildStructure(
                    base_location=self.ai.mediator.get_behind_mineral_positions(
                        th_pos=hq.position
                    )[0],
                    structure_id=UnitTypeId.SPAWNINGPOOL,
                    to_count=1,
                )
            )

        if (
            self.ai.structures(UnitTypeId.SPAWNINGPOOL)
            and self.ai.supply_used == 14
            and (
                self.ai.units(UnitTypeId.OVERLORD).amount
                + self.ai.already_pending(UnitTypeId.OVERLORD)
            )
            < 2
            and self.ai.can_afford(UnitTypeId.OVERLORD)
        ):
            self.ai.larva.first.build(UnitTypeId.OVERLORD)
        elif self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready:
            macro_plan.add(AutoSupply(base_location=self.ai.start_location))

        try:
            if not self.ai.structures(UnitTypeId.SPAWNINGPOOL):
                worker_count = 14
            elif (
                not self.ai.controllers.attacks
                and not self.ai.controllers.skip_first_attack
            ):
                worker_count = 16
            elif self.ai.controllers.attacks == 1 or (
                self.ai.controllers.skip_first_attack
                and self.ai.controllers.attacks == 0
            ):
                worker_count = min(
                    self.ai.supply_used
                    - 3 * int(math.log(self.ai.supply_used))
                    - self.ai.units(UnitTypeId.QUEEN).amount * 2,
                    self.ai.townhalls.amount * 19,
                    60,
                )
            else:
                worker_count = min(
                    self.ai.supply_used - 16 * int(math.log(self.ai.supply_used)), 75
                )
        except ValueError:
            # This is possible if we're taking the log of 0
            # We have already lost at this point but catch it to avoid crashing
            worker_count = 14

        # After first attack stop production until we have 3 hatcheries
        if (
            self.ai.controllers.attacks != 1
            or self.ai.townhalls.amount >= 3
            or under_attack
        ):
            if self.ai.supply_workers >= worker_count or under_attack:
                macro_plan.add(
                    SpawnController(
                        army_composition_dict={
                            UnitTypeId.ZERGLING: {"proportion": 1.0, "priority": 0}
                        }
                    )
                )
            else:
                macro_plan.add(BuildWorkers(to_count=worker_count))

        if (
            self.ai.can_afford(UpgradeId.ZERGLINGMOVEMENTSPEED)
            and self.ai.already_pending(UnitTypeId.LAIR) == 0.0
            and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.ai.completed_researches
        ):
            sp = self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready
            if sp:
                self.ai.research(UpgradeId.ZERGLINGMOVEMENTSPEED)

        if (
            self.ai.already_pending_upgrade(UpgradeId.ZERGMELEEWEAPONSLEVEL1) > 0.0
            and self.ai.already_pending_upgrade(UpgradeId.ZERGGROUNDARMORSLEVEL1) > 0.0
            and self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready
        ):
            # await self.chat_send("Upgrading to Lair", True)
            self.ai.register_behavior(
                TechUp(base_location=hq.position, desired_tech=UnitTypeId.LAIR)
            )

        if (
            self.ai.controllers.attacks
            and not UpgradeId.ZERGGROUNDARMORSLEVEL1 in self.ai.completed_researches
            and self.ai.townhalls.amount >= 3
            and (
                self.ai.units(UnitTypeId.QUEEN).amount
                + self.ai.already_pending(UnitTypeId.QUEEN)
                >= 3
            )
        ):
            self.ai.register_behavior(GasBuildingController(to_count=2))
            self.ai.register_behavior(
                BuildStructure(
                    base_location=hq.position,
                    structure_id=UnitTypeId.EVOLUTIONCHAMBER,
                    to_count=2,
                )
            )

            researches = [
                UpgradeId.ZERGMELEEWEAPONSLEVEL1,
                UpgradeId.ZERGGROUNDARMORSLEVEL1,
                UpgradeId.ZERGMELEEWEAPONSLEVEL2,
            ]

            self.ai.register_behavior(UpgradeController(researches, hq.position, False))

            # for evo in self.structures(UnitTypeId.EVOLUTIONCHAMBER).ready:
            #     if evo.is_idle:
            #         for research in researches:
            #             if (self.can_afford(research)
            #                 and not research in self.completed_researches
            #                     and self.already_pending_upgrade(research) == 0):
            #                 await self.chat_send(f"Researching {research}", True)
            #                 evo.research(research)
            #                 break

        if UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.ai.completed_researches:
            self.ai.register_behavior(
                TechUp(base_location=hq.position, desired_tech=UnitTypeId.HIVE)
            )
            self.ai.register_behavior(
                BuildStructure(
                    base_location=hq.position,
                    structure_id=UnitTypeId.EVOLUTIONCHAMBER,
                    to_count=2,
                )
            )
            self.ai.register_behavior(GasBuildingController(to_count=2))

            researches = [
                UpgradeId.ZERGMELEEWEAPONSLEVEL2,
                UpgradeId.ZERGGROUNDARMORSLEVEL2,
                UpgradeId.ZERGMELEEWEAPONSLEVEL3,
                UpgradeId.ZERGGROUNDARMORSLEVEL3,
                UpgradeId.ZERGLINGATTACKSPEED,
            ]

            self.ai.register_behavior(UpgradeController(researches, hq.position, False))
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

        if self.ai.time < 900:
            if self.ai.minerals > 1000:
                max_pending = 10
            elif self.ai.townhalls.amount == 1:
                max_pending = 1
            else:
                max_pending = 2
            self.ai.register_behavior(
                FixedExpansionController(to_count=8, max_pending=max_pending)
            )
        else:
            self.ai.register_behavior(
                FixedExpansionController(to_count=20, max_pending=10)
            )

        if self.ai.minerals > 2000:
            self.ai.register_behavior(
                BuildStructure(
                    base_location=random.choice(self.ai.townhalls).position,
                    structure_id=UnitTypeId.HATCHERY,
                    to_count=15,
                    max_on_route=1,
                )
            )

        self.ai.register_behavior(macro_plan)
