from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.combat.combat_maneuver import CombatManeuver
from ares.consts import (
    COMMON_UNIT_IGNORE_TYPES,
    LOSS_MARGINAL_OR_WORSE,
    VICTORY_DECISIVE_OR_BETTER,
    EngagementResult,
    UnitRole,
)
from bot.behaviour_overwrite import (
    AMove,
    KeepUnitSafe,
    PathUnitToTarget,
)
from bot.controllers.controller import Controller
from sc2.units import Point2, Units, UnitTypeId

if TYPE_CHECKING:
    from bot.main import WilldZergBot


class DefendController(Controller):
    def __init__(
        self,
        ai: "WilldZergBot",
    ) -> None:
        self.ai = ai

        self._defend_point: Point2 = Point2((0, 0))

    def defend_point(self) -> Point2:
        return self._defend_point

    async def start(self):
        self._defend_point = self.ai.expansion_entrance

    async def update(self) -> None:
        ground_grid: np.ndarray = self.ai.mediator.get_ground_grid
        attackers: Units = self.ai.mediator.get_units_from_role(
            role=UnitRole.ATTACKING_MAIN_SQUAD
        )
        defenders: Units = self.ai.mediator.get_units_from_role(role=UnitRole.DEFENDING)
        unassigned_lings = [
            l
            for l in self.ai.units(UnitTypeId.ZERGLING)
            if l not in (attackers + defenders)
        ]

        if unassigned_lings:
            print("FOUND LINGS WITHOUT A ROLE. ASSIGNING THEM TO DEFENDING")
            self.ai.mediator.batch_assign_role(
                tags={l.tag for l in unassigned_lings}, role=UnitRole.DEFENDING
            )

        if not self.ai.townhalls:
            self._defend_point = self.ai.start_location
        elif self.ai.townhalls.amount < 3:
            self._defend_point = self.ai.expansion_entrance
        else:
            self._defend_point = self.ai._position_facing_enemy_base(
                self.ai.townhalls.closest_to(self.ai.enemy_start_locations[0]).position
            )

        if self.ai.townhalls:
            close_units: Units = self.ai.enemy_units.in_distance_of_group(
                self.ai.townhalls, 40
            ).filter(
                lambda u: (
                    not u.is_flying
                    and not u.is_cloaked
                    and not u.is_hallucination
                    and not u.type_id in COMMON_UNIT_IGNORE_TYPES
                    and u.can_be_attacked
                )
            )
        else:
            # We've almost certainly lost so just have some behaviour to not crash
            close_units = self.ai.enemy_units

        if not close_units:
            for defender in defenders:
                maneuver: CombatManeuver = CombatManeuver()
                maneuver.add(KeepUnitSafe(unit=defender, grid=ground_grid))
                maneuver.add(
                    PathUnitToTarget(
                        unit=defender, grid=ground_grid, target=self._defend_point
                    )
                )
                self.ai.register_behavior(maneuver)
            return

        combat_sim_result: EngagementResult = self.ai.mediator.can_win_fight(
            own_units=defenders, enemy_units=close_units
        )
        # attackers = self.ai.mediator.get_units_from_role(
        #     role=UnitRole.ATTACKING_MAIN_SQUAD
        # )
        # if (
        #     attackers
        #     and defenders.amount >= 10
        #     and combat_sim_result
        #     in [EngagementResult.LOSS_MARGINAL, EngagementResult.LOSS_CLOSE]
        # ):
        #     all_units = attackers + defenders
        #     new_combat_sim_result: EngagementResult = self.ai.mediator.can_win_fight(
        #         own_units=all_units, enemy_units=close_units
        #     )
        #     if new_combat_sim_result is VICTORY_DECISIVE_OR_BETTER:
        #         print("Setting attackers to defend")
        #         self.ai.mediator.batch_assign_role(
        #             tags={a.tag for a in attackers}, role=UnitRole.DEFENDING
        #         )

        for defender in defenders:
            maneuver: CombatManeuver = CombatManeuver()
            nearby_friendlies = defenders.closer_than(
                20, close_units.closest_to(defender)
            ).amount
            nearby_enemies = close_units.closer_than(
                10, close_units.closest_to(defender)
            ).amount
            if (
                combat_sim_result in LOSS_MARGINAL_OR_WORSE
                or (
                    self.ai.townhalls
                    and defender.position.distance_to_closest(self.ai.townhalls) > 50
                )
            ) and nearby_enemies * 2 > nearby_friendlies:
                maneuver.add(KeepUnitSafe(unit=defender, grid=ground_grid))
            elif close_units:
                # if defender.position.distance_to_closest(self.townhalls) > 40:
                #     print(
                #         f"{combat_sim_result=}, {nearby_enemies=}, {nearby_friendlies=}")
                self._defend_point = close_units.closest_to(defender).position
            maneuver.add(AMove(unit=defender, target=self._defend_point))
            self.ai.register_behavior(maneuver)
