import random
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.combat.combat_maneuver import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    KeepUnitSafe,
)
from ares.behaviors.macro import UpgradeController
from ares.consts import (
    CHANGELING_TYPES,
    COMMON_UNIT_IGNORE_TYPES,
    LOSS_MARGINAL_OR_WORSE,
    VICTORY_CLOSE_OR_BETTER,
    EngagementResult,
    UnitRole,
)
from bot.controllers.controller import Controller
from cython_extensions.units_utils import (
    cy_closer_than,
    cy_closest_to,
    cy_find_units_center_mass,
)
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.units import Unit, Units

if TYPE_CHECKING:
    from bot.main import WilldZergBot


class AttackController(Controller):
    def __init__(
        self,
        ai: "WilldZergBot",
    ) -> None:
        self.ai = ai

        self._under_attack_timer: int = 0
        self._trigger_attack_time: int = -200
        self._attacks: int = 0
        self._skip_first_attack = False

        self._attacker_com: Point2 = Point2((0, 0))

    def trigger_attack(self, iteration: int) -> None:
        self._trigger_attack_time = iteration

    def set_under_attack_timer(self, timer: int) -> None:
        self._under_attack_timer = timer

    def under_attack_timer(self) -> int:
        return self._under_attack_timer

    def attacks(self) -> int:
        return self._attacks

    def attacker_com(self) -> Point2:
        return self._attacker_com

    def skip_first_attack(self) -> bool:
        return self._skip_first_attack

    async def start(self) -> None:
        self._attacker_com = self.ai.expansion_entrance

    def _manage_first_attack(self) -> None:
        if self._attacks > 0 or self._skip_first_attack:
            return

        lings = self.ai.mediator.get_own_army_dict[UnitTypeId.ZERGLING]
        _, num_units = cy_find_units_center_mass(lings, 3)
        cancel_attack = (
            self.ai.enemy_units.filter(
                lambda u: not u.type_id in self.ai.WORKER_TYPES
            ).amount
            > 1
            or self.ai.enemy_structures.filter(
                lambda u: u.type_id is UnitTypeId.PHOTONCANNON and u.is_ready
            ).amount
            > 0
        )
        if (num_units >= 6 or len(lings) > 6) and not cancel_attack:
            # This should be hitting the opp natural around 2:30
            self.ai.mediator.batch_assign_role(
                tags={l.tag for l in lings}, role=UnitRole.ATTACKING_MAIN_SQUAD
            )

        if cancel_attack:
            attacking_lings = self.ai.mediator.get_units_from_role(
                role=UnitRole.ATTACKING_MAIN_SQUAD
            )
            if attacking_lings:
                self.ai.mediator.batch_assign_role(
                    tags={l.tag for l in attacking_lings}, role=UnitRole.DEFENDING
                )
                print("Cancelling first attack")

    async def _timing_attacks(self) -> None:
        # If we've seen a cannon we assume we won't be able to break in so skip the first timing attack
        if (
            self._attacks == 0
            and not self._skip_first_attack
            and self.ai.enemy_structures.filter(
                lambda u: u.type_id is UnitTypeId.PHOTONCANNON and u.is_ready
            ).amount
            > 0
        ):
            self._skip_first_attack = True
            print("Scouted a cannon so skipping first timing attack")
            return

        if self.ai.actual_iteration == self._trigger_attack_time + 100:
            self._attacks += 1
            if self._attacks == 1 and self._skip_first_attack:
                print("Would be sending first attack but skipped")
                return
            lings = self.ai.units(UnitTypeId.ZERGLING)
            self.ai.mediator.batch_assign_role(
                tags={l.tag for l in lings}, role=UnitRole.ATTACKING_MAIN_SQUAD
            )

            print(
                f"Sending attack number {self._attacks} with {lings.amount} lings @ {self.ai.time_formatted}"
            )
            await self.ai.chat_send(
                f"Sending timing attack number {self._attacks}", True
            )

    def _other_attacks(self) -> None:
        if self.ai.supply_used == 200 and self._attacks >= 2:
            self.ai.register_behavior(
                UpgradeController(
                    [UpgradeId.OVERLORDSPEED],
                    base_location=self.ai.townhalls.first.position,
                )
            )

            lings = self.ai.mediator.get_units_from_role(
                role=UnitRole.DEFENDING, unit_type=UnitTypeId.ZERGLING
            )
            self.ai.mediator.batch_assign_role(
                tags={l.tag for l in lings}, role=UnitRole.ATTACKING_MAIN_SQUAD
            )

    def _attack_behaviour(self) -> None:
        ground_grid: np.ndarray = self.ai.mediator.get_ground_grid
        attackers: Units = self.ai.mediator.get_units_from_role(
            role=UnitRole.ATTACKING_MAIN_SQUAD
        )

        if not attackers:
            self._attacker_com = self.ai.controllers.defend_point
            return

        com, _ = cy_find_units_center_mass(attackers, 20)
        self._attacker_com = Point2(com)
        close_attackers = cy_closer_than(attackers, 20, com)

        enemy_units: Units = self.ai.enemy_units.closer_than(
            30, Point2(self._attacker_com)
        ).filter(
            lambda u: (
                not u.is_flying
                and not u.is_cloaked
                and not u.is_hallucination
                and not u.type_id in COMMON_UNIT_IGNORE_TYPES
                and u.can_be_attacked
            )
        )

        if not self.ai.actual_iteration % 50 and self.ai.time > 720:
            print(enemy_units)

        combat_sim_result: EngagementResult = self.ai.mediator.can_win_fight(
            own_units=close_attackers,
            enemy_units=enemy_units,
            workers_do_no_damage=True,
        )

        for attacker in attackers:
            maneuver: CombatManeuver = CombatManeuver()
            if enemy_units.closer_than(10, attacker):
                nearby_friendlies = attackers.closer_than(
                    20, enemy_units.closest_to(attacker)
                ).amount
                nearby_enemies = (
                    enemy_units.closer_than(10, enemy_units.closest_to(attacker))
                    .filter(lambda u: not u.type_id in self.ai.WORKER_TYPES)
                    .amount
                )

            else:
                nearby_enemies = nearby_friendlies = 0
            if (
                combat_sim_result in LOSS_MARGINAL_OR_WORSE
                and attackers.amount < 120
                and nearby_enemies * 2 > nearby_friendlies
            ):
                maneuver.add(KeepUnitSafe(attacker, ground_grid))
            target: Point2 | Unit = self._decide_attack_target(
                combat_sim_result, attacker, enemy_units
            )
            maneuver.add(AMove(unit=attacker, target=target))

            self.ai.register_behavior(maneuver)

    async def update(self) -> None:
        self._manage_first_attack()
        await self._timing_attacks()
        self._other_attacks()

        self._attack_behaviour()

    def _decide_attack_target(
        self, combat_sim_result: EngagementResult, unit: Unit, enemy_units: Units
    ) -> Point2 | Unit:
        enemy_structures: Units = self.ai.enemy_structures
        current_target = unit.order_target

        closest_unit = enemy_units.closest_to(unit) if enemy_units else None

        if (
            (enemy_units and combat_sim_result in VICTORY_CLOSE_OR_BETTER)
            and closest_unit
            and (
                not closest_unit.is_burrowed
                or closest_unit.type_id in [UnitTypeId.WIDOWMINEBURROWED]
            )
            and not closest_unit.type_id in CHANGELING_TYPES
        ):
            return closest_unit.position
        elif enemy_structures:
            return cy_closest_to(unit.position, enemy_structures).position
        elif (
            isinstance(current_target, Point2)
            and current_target in self.ai.expansion_locations_list
        ):
            return current_target
        elif self.ai.is_visible(self.ai.enemy_start_locations[0]):
            return random.choice(self.ai.expansion_locations_list)
        else:
            return self.ai.enemy_start_locations[0]
