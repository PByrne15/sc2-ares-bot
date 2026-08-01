from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.macro import ExpansionController
from sc2.position import Point2

if TYPE_CHECKING:
    from ares import AresBot

from ares.managers.manager_mediator import ManagerMediator


class FixedExpansionController(ExpansionController):

    def _get_next_expansion_location(
        self, ai: "AresBot", mediator: ManagerMediator
    ) -> Point2 | None:
        grid: np.ndarray = mediator.get_ground_grid
        for el in mediator.get_own_expansions:
            location: Point2 = el[0]
            if (
                (
                    self.check_location_is_safe
                    and not mediator.is_position_safe(grid=grid, position=location)
                )
                or ai.location_is_blocked(mediator, location)
                or not mediator.can_place_structure(
                    position=location, structure_type=ai.base_townhall_type
                )
                or location not in ai.expansion_locations_list
            ):
                if location not in ai.expansion_locations_list:
                    print(f"Skipping {location} because not in expansion list")
                continue

            return location

        return None
