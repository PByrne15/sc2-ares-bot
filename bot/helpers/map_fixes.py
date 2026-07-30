from typing import TYPE_CHECKING

from sc2.position import Point2

if TYPE_CHECKING:
    from bot.main import WilldZergBot


def _ley_lines_fixes(ai: "WilldZergBot"):
    broken_expansions = ((94.5, 66.5), (103.5, 107.5))
    for be in broken_expansions:
        point = Point2(be)
        ai._expansion_positions_list.remove(point)


def apply_map_fixes(ai: "WilldZergBot"):
    FIXES = {
        "Ley Lines AIE": _ley_lines_fixes
    }

    map_name = ai.game_info.map_name
    print(map_name)
    if map_name not in FIXES:
        return

    FIXES[map_name](ai)
