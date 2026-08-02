from typing import TYPE_CHECKING

from ares.consts import AbilityId, UnitRole
from bot.controllers.controller import Controller
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Unit, Units

if TYPE_CHECKING:
    from bot.main import WilldZergBot


MAX_INJECT_QUEENS = 8


class InjectController(Controller):
    def __init__(self, ai: "WilldZergBot") -> None:
        self.ai = ai

        self._inject_dict: dict[int, int | None] = {}

    async def start(self) -> None:
        pass

    def add_inject_queen(self, queen: Unit) -> bool:
        no_queen_ths = [th for th, q in self._inject_dict.items() if q is None]
        if (
            not no_queen_ths
            or len(self._inject_dict) - len(no_queen_ths) > MAX_INJECT_QUEENS
        ):
            return False

        ths = Units(self.ai.mediator.get_units_from_tags(tags=no_queen_ths), self.ai)
        self._inject_dict[ths.closest_to(queen).tag] = queen.tag
        self.ai.mediator.assign_role(tag=queen.tag, role=UnitRole.QUEEN_INJECT)
        print(
            f"Adding queen with tag {queen.tag} to townhall with tag {ths.closest_to(queen).tag}"
        )
        return True

    def remove_inject_queen(self, queen: Unit) -> None:
        for th, q in self._inject_dict.items():
            if queen.tag == q:
                self._inject_dict[th] = None

    def _maybe_build_queen(self, th: Unit) -> None:
        inject_queens = [q for q in self._inject_dict.values() if q]
        building_queens = self.ai.units(UnitTypeId.QUEEN).not_ready
        if (
            len(inject_queens) < MAX_INJECT_QUEENS
            and building_queens.amount < 2
            and th.is_idle
            and self.ai.structures(UnitTypeId.SPAWNINGPOOL).ready
        ):
            self.ai.train(UnitTypeId.QUEEN, closest_to=th.position)

    async def update(self) -> None:
        ths = [th for th in self.ai.townhalls]
        # add any new townhalls
        for th in ths:
            if th.tag not in self._inject_dict and th.is_ready:
                self._inject_dict[th.tag] = None
                print(f"Adding th with tag {th.tag}")

        inject_dict_copy = self._inject_dict.copy()
        for th in inject_dict_copy:
            # remove any destroyed townhalls
            if th not in [th.tag for th in ths]:
                queen = self._inject_dict.pop(th)
                if queen:
                    queen_unit = self.ai.unit_tag_dict[queen]
                    self.ai.controllers.add_creep_queen(queen_unit)
                print(f"Removing th with tag {th}")
                continue

            try:
                th_unit = self.ai.unit_tag_dict[th]
            except KeyError:
                # This shouldn't be possible as we removed destroyed townhalls
                # but catch it anyway
                print("COULDN't FIND TOWNHALL. THIS SHOULDN'T BE POSSIBLE")
                continue

            if not self._inject_dict[th]:
                self._maybe_build_queen(th_unit)
                continue

            queen = None
            try:
                queen = self.ai.unit_tag_dict[self._inject_dict[th]]  # pyright: ignore[reportArgumentType]
            except KeyError:
                # Couldn't get the queen from the tag
                print(f"Removing queen with tag {self._inject_dict[th]}")
                self._inject_dict[th] = None

            if queen and queen.energy >= 25:
                queen(AbilityId.EFFECT_INJECTLARVA, th_unit)
