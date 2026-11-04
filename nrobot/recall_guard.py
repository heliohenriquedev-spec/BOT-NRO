"""A map change the bot did not cause (GM @recall, forced teleport): everything stops.

While hunting, the bot never walks into a portal (their areas are forbidden cells) and only
the quest/map routes travel between maps. So arriving somewhere else while hunting, from a
cell far from every known portal, means the server moved the character: a GM recall, a
warp by script or a respawn. The bot then stops sending anything until the player acts."""
from .portals import PortalGuard, chebyshev

SAME_MAP_SLIP = 5  # a same-map "change" this short is a position correction, not a teleport


def unexpected_teleport(events, previous_map, origin, portals):
    """{'from_map', 'origin', 'to_map', 'position'} for a map change far from any portal, else None."""
    if origin is None:
        return None
    for event in events:
        if event['kind'] not in ('map_change', 'map_transfer'):
            continue
        target_map, target = event.get('map'), event.get('position')
        same = PortalGuard.key(target_map) == PortalGuard.key(previous_map)
        if same and target and chebyshev(origin, target) <= SAME_MAP_SLIP:
            continue
        near_portal = (any(chebyshev(origin, cell) <= margin+2 for cell, margin in portals.portals(previous_map))
                       or any(chebyshev(origin, cell) <= 2 for cell, _ in portals.links(previous_map)))
        if near_portal:
            continue
        return dict(from_map=previous_map, origin=list(origin), to_map=target_map,
                    position=list(target) if target else None)
    return None
