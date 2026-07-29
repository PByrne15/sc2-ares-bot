from typing import TYPE_CHECKING

from sc2.constants import IS_CARRYING_MINERALS
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.units import Unit, Units

from ares.consts import (
    BURROWED_ALIAS,
    COMMON_UNIT_IGNORE_TYPES,
    LOSS_MARGINAL_OR_WORSE,
    TOWNHALL_TYPES,
    VICTORY_CLOSE_OR_BETTER,
    WORKER_TYPES,
    EngagementResult,
    UnitRole
)

from ares.behaviors.combat.combat_maneuver import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    MoveToSafeTarget,
    KeepUnitSafe,
    PathUnitToTarget
)
from ares.behaviors.combat.group import (
    KeepGroupSafe,
    AMoveGroup
)

if TYPE_CHECKING:
    from ..main import WilldZergBot


class ScoutManager:
    def __init__(self, ai: "WilldZergBot") -> None:
        self.ai = ai

        self._first_iteration: bool = True
        self._scouting_natural: bool = False
        self._enemy_nat_taken: bool = False

        self._nat_scout_unit: int = 0

    def update(self) -> None:
        if self._first_iteration:
            ol = self.ai.units(UnitTypeId.OVERLORD).first
            self.ai.mediator.assign_role(tag=ol.tag, role=UnitRole.SCOUTING)
            self._first_iteration = False

        ols = self.ai.mediator.get_units_from_role(
            role=UnitRole.SCOUTING, unit_type=UnitTypeId.OVERLORD)
        for ol in ols:
            maneuver = CombatManeuver()
            maneuver.add(PathUnitToTarget(
                ol, self.ai.mediator.get_air_grid, self.ai.mediator.get_ol_spot_near_enemy_nat))
            self.ai.register_behavior(maneuver)

        if self._scouting_natural:
            self._scout_for_natural()

        self._defending_overseer()
        self._attacking_overseer()

    def scout_for_natural(self) -> None:
        self._scouting_natural = True

    def cancel_scout_for_natural(self) -> None:
        self._scouting_natural = False

    @property
    def enemy_nat_taken(self) -> bool:
        if not self._enemy_nat_taken:
            self._enemy_nat_taken = (
                self.ai.mediator.get_enemy_expanded
                or len(
                    [IS_CARRYING_MINERALS in worker.buffs for worker
                     in self.ai.enemy_units(WORKER_TYPES).closer_than(
                         10, self.ai.mediator.get_enemy_nat)]
                ) > 1
            )

        return self._enemy_nat_taken

    def _scout_for_natural(self) -> None:
        enemy_nat = self.ai.mediator.get_enemy_nat
        if self.ai.is_visible(enemy_nat) or self.enemy_nat_taken:
            if scouting_unit := self.ai.unit_tag_dict.get(self._nat_scout_unit):
                if scouting_unit.type_id == UnitTypeId.OVERLORD:
                    self.ai.mediator.assign_role(
                        tag=scouting_unit.tag, role=UnitRole.SCOUTING)

            self._scouting_natural = False
            return

        if not self._nat_scout_unit:
            if scout_ols := self.ai.mediator.get_units_from_role(
                    role=UnitRole.SCOUTING, unit_type=UnitTypeId.OVERLORD):
                self._nat_scout_unit = scout_ols.first.tag
                self.ai.mediator.assign_role(
                    tag=scout_ols.first.tag, role=UnitRole.CONTROL_GROUP_ONE)
            elif scout_ling := self.ai.units(UnitTypeId.ZERGLING).first:
                self._nat_scout_unit = scout_ling.tag
            else:
                # No units available to scout with, try again next time
                return

        if scouting_unit := self.ai.unit_tag_dict.get(self._nat_scout_unit):
            scouting_unit.move(enemy_nat)
        else:
            # Scouting unit must have died, give up
            self._scouting_natural = False

    def _defending_overseer(self) -> None:
        if UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.ai.completed_researches:
            count = 1
            if self.ai.time > 480:
                count = 2

            self._morph_overseers_in_role(
                UnitRole.DEFENDING, count, self.ai.defend_point)

    def _attacking_overseer(self) -> None:
        if self.ai.supply_used == 200 and self.ai.attacks >= 2:
            self._morph_overseers_in_role(
                UnitRole.ATTACKING_MAIN_SQUAD, 2, self.ai.attacker_com)

    def _morph_overseers_in_role(self, role: UnitRole, max_count: int, location: Point2 | None = None) -> None:
        if not location:
            location = self.ai.start_location
        if self.ai.mediator.get_units_from_role(
            role=role, unit_type=set(
                (UnitTypeId.OVERLORD, UnitTypeId.OVERSEER, UnitTypeId.OVERLORDCOCOON))
        ).amount < max_count and self.ai.can_afford(UnitTypeId.OVERSEER) and self.ai.minerals > 200:
            # print(
            #     f"Spawning overseer for role {role} @ {self.ai.time_formatted}")
            overlord = self.ai.units(UnitTypeId.OVERLORD).closest_to(
                location)
            overlord(AbilityId.MORPH_OVERSEER, subtract_cost=True)
            self.ai.mediator.assign_role(
                tag=overlord.tag, role=role)
