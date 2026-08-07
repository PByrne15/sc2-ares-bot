from typing import TYPE_CHECKING

from ares.behaviors.combat.individual import QueenSpreadCreep, TumorSpreadCreep
from ares.consts import UnitRole
from bot.controllers.controller import Controller
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Point2, Unit

if TYPE_CHECKING:
    from bot.main import WilldZergBot


MIN_QUEENS_BEFORE_CREEP = 3


class CreepController(Controller):
    def __init__(self, ai: "WilldZergBot") -> None:
        self.ai = ai

        self._creep_queens: set[int] = set()
        self._placed_first_tumor: bool = False
        self._first_tumor_position: Point2

    async def start(self) -> None:
        pos = self.ai.mediator.get_closest_creep_tile(pos=self.ai.mediator.get_own_nat)
        assert pos
        self._first_tumor_position = pos

    def add_creep_queen(self, queen: Unit) -> bool:
        self.ai.mediator.assign_role(tag=queen.tag, role=UnitRole.QUEEN_CREEP)
        self._creep_queens.add(queen.tag)
        return True

    def remove_creep_queen(self, queen: Unit) -> None:
        # Caller is responsible for reassigning the role
        self._creep_queens.remove(queen.tag)

    def _place_first_tumor(self):
        if self._placed_first_tumor:
            return

        queens = self._creep_queens.copy()
        for queen in queens:
            try:
                queen_unit = self.ai.unit_tag_dict[queen]
            except KeyError:
                self._creep_queens.remove(queen)
                continue
            queen_unit(AbilityId.BUILD_CREEPTUMOR_QUEEN, self._first_tumor_position)

        if self.ai.structures([UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMOR]):
            self._placed_first_tumor = True

    def _queen_spread_creep(self) -> None:
        self._place_first_tumor()
        if not self._placed_first_tumor:
            return

        queens = self._creep_queens.copy()
        for queen in queens:
            try:
                queen_unit = self.ai.unit_tag_dict[queen]
            except KeyError:
                self._creep_queens.remove(queen)
                continue
            self.ai.register_behavior(QueenSpreadCreep(queen_unit))

    def _tumor_spread_creep(self, target: Point2 | None = None) -> None:
        tumors = self.ai.structures(UnitTypeId.CREEPTUMORBURROWED)
        for tumor in tumors:
            if not target:
                target = self.ai.enemy_start_locations[0]
            self.ai.register_behavior(TumorSpreadCreep(tumor, target))

    def _maybe_build_queen(self, th: Unit) -> None:
        total_queens = self.ai.units(UnitTypeId.QUEEN)
        if (
            total_queens.amount >= MIN_QUEENS_BEFORE_CREEP
            and th.is_idle
            and self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready
            and (
                len(self._creep_queens) < 2
                or (self.ai.minerals > 1000 and total_queens.amount < 12)
            )
        ):
            self.ai.train(UnitTypeId.QUEEN, closest_to=th.position)

    async def update(self) -> None:
        if self.ai.townhalls:
            self._maybe_build_queen(
                self.ai.townhalls.closest_to(self.ai.mediator.get_own_nat)
            )
        self._queen_spread_creep()
        self._tumor_spread_creep()
