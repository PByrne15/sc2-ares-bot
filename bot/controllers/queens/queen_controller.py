from typing import TYPE_CHECKING

from ares.behaviors.combat.individual import UseTransfuse
from ares.consts import UnitRole
from bot.controllers.controller import Controller
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Point2, Unit

if TYPE_CHECKING:
    from bot.main import WilldZergBot


MIN_QUEENS_BEFORE_CREEP = 3


class QueenController(Controller):
    def __init__(self, ai: "WilldZergBot") -> None:
        self.ai = ai

    async def start(self) -> None:
        pass

    def assign_queen_default(self, queen: Unit) -> None:
        if not self.ai.controllers.add_inject_queen(queen):
            self.ai.controllers.add_creep_queen(queen)

    def _handle_unused_queens(self) -> None:
        queens = self.ai.units(UnitTypeId.QUEEN).ready.tags
        assigned_queens = self.ai.mediator.get_units_from_roles(
            roles={UnitRole.QUEEN_INJECT, UnitRole.QUEEN_CREEP, UnitRole.DEFENDING},
            unit_type=UnitTypeId.QUEEN,
        ).tags

        unused_queens = [q for q in queens if q not in assigned_queens]

        for q in unused_queens:
            print(f"Assigning unused queen with tag {q}")
            q_unit = self.ai.unit_tag_dict[q]
            self.assign_queen_default(q_unit)

    def _handle_defensive_queen_behaviour(self) -> None:
        defensive_queens = self.ai.mediator.get_units_from_role(
            role=UnitRole.DEFENDING, unit_type=UnitTypeId.QUEEN
        )
        all_queens = self.ai.units(UnitTypeId.QUEEN).ready
        defensive_structures = self.ai.structures(
            [UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER]
        )
        for q in defensive_queens:
            self.ai.register_behavior(
                UseTransfuse(q, all_queens + defensive_structures)
            )

    def _transition_creep_queens_to_defensive(self) -> None:
        creep_queens = self.ai.mediator.get_units_from_role(
            role=UnitRole.QUEEN_CREEP, unit_type=UnitTypeId.QUEEN
        )
        if creep_queens:
            print(f"Changing creep queens to defensive @ {self.ai.time_formatted}")
        for q in creep_queens:
            self.ai.controllers.remove_creep_queen(q)
            self.ai.mediator.assign_role(tag=q.tag, role=UnitRole.DEFENDING)

    def _transition_defensive_queens_to_default(self) -> None:
        defensive_queens = self.ai.mediator.get_units_from_role(
            role=UnitRole.DEFENDING, unit_type=UnitTypeId.QUEEN
        )
        if defensive_queens:
            print(f"Changing defensive queens to default @ {self.ai.time_formatted}")
        for q in defensive_queens:
            self.assign_queen_default(q)

    async def update(self) -> None:
        self._handle_unused_queens()

        if self.ai.controllers.under_attack_timer > 1:
            self._transition_creep_queens_to_defensive()
        else:
            self._transition_defensive_queens_to_default()

        self._handle_defensive_queen_behaviour()
