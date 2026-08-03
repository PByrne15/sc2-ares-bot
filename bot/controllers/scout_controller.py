from typing import TYPE_CHECKING

from ares.behaviors.combat.combat_maneuver import CombatManeuver
from ares.behaviors.combat.individual import (
    PathUnitToTarget,
)
from ares.consts import WORKER_TYPES, UnitRole
from bot.controllers.controller import Controller
from sc2.constants import IS_CARRYING_MINERALS
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

if TYPE_CHECKING:
    from bot.main import WilldZergBot


class ScoutController(Controller):
    def __init__(self, ai: "WilldZergBot") -> None:
        self.ai = ai

        self._first_iteration: bool = True
        self._scouting_natural: bool = False
        self._enemy_nat_taken: bool = False

        self._nat_scout_unit: int = 0
        self._nat_scout_attempts = 0
        self._scouted_lack_of_natural = False

    async def start(self):
        pass

    async def update(self) -> None:
        if self._first_iteration:
            ol = self.ai.units(UnitTypeId.OVERLORD).first
            self.ai.mediator.assign_role(tag=ol.tag, role=UnitRole.SCOUTING)
            self._first_iteration = False

        ols = self.ai.mediator.get_units_from_role(
            role=UnitRole.SCOUTING, unit_type=UnitTypeId.OVERLORD
        )
        for ol in ols:
            maneuver = CombatManeuver()
            maneuver.add(
                PathUnitToTarget(
                    ol,
                    self.ai.mediator.get_air_grid,
                    self.ai.mediator.get_ol_spot_near_enemy_nat,
                )
            )
            self.ai.register_behavior(maneuver)

        if self._scouting_natural:
            self._scout_for_natural()

        self._defending_overseer()
        self._attacking_overseer()

    def scout_for_natural(self) -> None:
        print("Sending scout to natural")
        self._scouting_natural = True

    def cancel_scout_for_natural(self) -> None:
        self._scouting_natural = False

    def enemy_nat_taken(self) -> bool:
        if not self._enemy_nat_taken:
            self._enemy_nat_taken = (
                self.ai.mediator.get_enemy_expanded
                or sum(
                    [
                        IS_CARRYING_MINERALS in worker.buffs
                        for worker in self.ai.enemy_units(WORKER_TYPES).closer_than(
                            10, self.ai.mediator.get_enemy_nat
                        )
                    ]
                )
                > 1
            )
            if self._enemy_nat_taken:
                print(
                    f"Scouted a natural: {self.ai.mediator.get_enemy_expanded=}, {
                        sum(
                            [
                                IS_CARRYING_MINERALS in worker.buffs
                                for worker in self.ai.enemy_units(
                                    WORKER_TYPES
                                ).closer_than(10, self.ai.mediator.get_enemy_nat)
                            ]
                        )
                    } @ {self.ai.time_formatted}"
                )

        return self._enemy_nat_taken

    def _scout_for_natural(self) -> None:
        enemy_nat = self.ai.mediator.get_enemy_nat
        if self.enemy_nat_taken():
            scouting_unit = self.ai.unit_tag_dict.get(self._nat_scout_unit)
            if scouting_unit and scouting_unit.type_id == UnitTypeId.OVERLORD:
                self.ai.mediator.assign_role(
                    tag=scouting_unit.tag, role=UnitRole.SCOUTING
                )

            self._scouting_natural = False
            return

        if self._nat_scout_unit and self.ai.is_visible(enemy_nat):
            # Successfully scouted a lack of natural so add an extra retry when the unit is killed
            self._scouted_lack_of_natural = True
            return

        # Assign a new scout if we don't have one and can't already see the natural location
        if not self._nat_scout_unit and not self.ai.is_visible(enemy_nat):
            if scout_ols := self.ai.mediator.get_units_from_role(
                role=UnitRole.SCOUTING, unit_type=UnitTypeId.OVERLORD
            ):
                self._nat_scout_unit = scout_ols.first.tag
            elif scout_ling := self.ai.mediator.get_units_from_roles(
                roles=(UnitRole.DEFENDING, UnitRole.ATTACKING_MAIN_SQUAD),
                unit_type=UnitTypeId.ZERGLING,
            ):
                self._nat_scout_unit = scout_ling.first.tag
            else:
                # No units available to scout with, try again next time
                if not self.ai.actual_iteration % 10:
                    print(
                        f"No units available to scout with  @ {self.ai.time_formatted}"
                    )
                return

            self.ai.mediator.assign_role(
                tag=self._nat_scout_unit, role=UnitRole.CONTROL_GROUP_ONE
            )

        # If we don't have one at this point we must have visibility from another unit
        if not self._nat_scout_unit:
            return

        if scouting_unit := self.ai.unit_tag_dict.get(self._nat_scout_unit):
            scouting_unit.move(enemy_nat)
        else:
            # Scouting unit must have died
            self._nat_scout_unit = 0
            self._nat_scout_attempts += 1

            # If the scout saw no natural, don't count this attempt
            if self._scouted_lack_of_natural:
                self._scouted_lack_of_natural = False
                self._nat_scout_attempts -= 1
            print(
                f"Scouting unit died, attempts =  {self._nat_scout_attempts} @ {self.ai.time_formatted}"
            )

            # If the scout died without reaching the nat a few times
            # then we will assume it has been taken
            if self._nat_scout_attempts >= 3:
                print("Reached limit for scouting natural, assuming it has been taken")
                self._scouting_natural = False
                self._enemy_nat_taken = True

    def _defending_overseer(self) -> None:
        if UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.ai.completed_researches:
            count = 1
            if self.ai.time > 480:
                count = 2

            self._morph_overseers_in_role(
                UnitRole.DEFENDING, count, self.ai.controllers.defend_point
            )

    def _attacking_overseer(self) -> None:
        if self.ai.supply_used == 200 and self.ai.controllers.attacks >= 2:
            self._morph_overseers_in_role(
                UnitRole.ATTACKING_MAIN_SQUAD, 2, self.ai.controllers.attacker_com
            )

    def _morph_overseers_in_role(
        self, role: UnitRole, max_count: int, location: Point2 | None = None
    ) -> None:
        if not location:
            location = self.ai.start_location
        if (
            self.ai.mediator.get_units_from_role(
                role=role,
                unit_type={
                    UnitTypeId.OVERLORD,
                    UnitTypeId.OVERSEER,
                    UnitTypeId.OVERLORDCOCOON,
                },
            ).amount
            < max_count
            and self.ai.can_afford(UnitTypeId.OVERSEER)
            and self.ai.minerals > 200
        ):
            # print(
            #     f"Spawning overseer for role {role} @ {self.ai.time_formatted}")
            if not self.ai.units(UnitTypeId.OVERLORD):
                return
            overlord = self.ai.units(UnitTypeId.OVERLORD).closest_to(location)
            overlord(AbilityId.MORPH_OVERSEER, subtract_cost=True)
            self.ai.mediator.assign_role(tag=overlord.tag, role=role)
