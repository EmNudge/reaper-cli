"""Track grouping / VCA tools.

REAPER's track-group system has 64 independent groups, each with 23+ "flags"
that determine which behaviors propagate between members: volume master/slave,
mute master/slave, solo, automation mode, recording, FX bypass, polarity, etc.

A track's group membership for each flag is encoded as a 32-bit + 32-bit
bitmask pair (one bit per group, low and high halves). The two reapy / RPR
calls ``GetSetTrackGroupMembership`` and ``GetSetTrackGroupMembershipHigh``
read/write those halves; this module wraps them with a friendlier
group-number + flag-name API.

VCA grouping uses the same mechanism — set a track's ``VOLUME_VCA_LEAD`` flag
to mark it the leader of a group, and other tracks' ``VOLUME_VCA_FOLLOW`` to
follow.
"""

import logging

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.track_groups")

# Names map to REAPER's ``GetSetTrackGroupMembership`` second-arg strings.
# Each membership name covers BOTH leader and follower halves; the leader/follower
# split is per-track via the LEAD/FOLLOW variants below.
GROUP_FLAG_NAMES = (
    "VOLUME_LEAD",
    "VOLUME_FOLLOW",
    "VOLUME_VCA_LEAD",
    "VOLUME_VCA_FOLLOW",
    "PAN_LEAD",
    "PAN_FOLLOW",
    "WIDTH_LEAD",
    "WIDTH_FOLLOW",
    "MUTE_LEAD",
    "MUTE_FOLLOW",
    "SOLO_LEAD",
    "SOLO_FOLLOW",
    "RECARM_LEAD",
    "RECARM_FOLLOW",
    "POLARITY_LEAD",
    "POLARITY_FOLLOW",
    "AUTOMODE_LEAD",
    "AUTOMODE_FOLLOW",
    "VOLUME_REVERSE",
    "PAN_REVERSE",
    "WIDTH_REVERSE",
    "NO_LEAD_WHEN_FOLLOW",
    "VOLUME_VCA_FOLLOW_ISPREFX",
)


def _validate_group(group_number: int) -> None:
    if not 1 <= group_number <= 64:
        raise ValueError(f"group_number must be 1-64, got {group_number}")


def _validate_flag(flag_name: str) -> None:
    if flag_name not in GROUP_FLAG_NAMES:
        raise ValueError(f"Unknown flag {flag_name!r}. Valid: {GROUP_FLAG_NAMES}")


def _flag_mask(group_number: int) -> tuple[int, bool]:
    """Return ``(bitmask, is_high_half)``. Groups 1-32 → low; 33-64 → high."""
    if group_number <= 32:
        return 1 << (group_number - 1), False
    return 1 << (group_number - 33), True


def _read_membership(track_id, flag_name: str) -> tuple[int, int]:
    """Return ``(low_mask, high_mask)`` for the given flag on this track."""
    from reapy import reascript_api as RPR

    low = int(RPR.GetSetTrackGroupMembership(track_id, flag_name, 0, 0))
    high = int(RPR.GetSetTrackGroupMembershipHigh(track_id, flag_name, 0, 0))
    return low, high


def register_tools(mcp):
    @mcp.tool()
    def about_track_groups() -> dict:
        """Orientation primer for the track-group system.

        Use this when you're new to REAPER's group flags — the per-tool
        descriptions can't fit the whole conceptual model.
        """
        return {
            "success": True,
            "concept": (
                "REAPER tracks can belong to up to 64 groups simultaneously. "
                "Each group governs which behaviors propagate between members "
                "(volume, mute, solo, …). Within each group, every track is "
                "either a 'lead' (origin of the change), a 'follower' "
                "(receives), or both — set independently per flag."
            ),
            "vca_vs_grouping": (
                "Plain group flags (e.g. VOLUME_LEAD/VOLUME_FOLLOW) directly "
                "set the receivers' values. VCA group flags "
                "(VOLUME_VCA_LEAD/VOLUME_VCA_FOLLOW) instead apply an offset "
                "via a virtual fader, leaving the follower's stored value "
                "intact — the classic console VCA workflow."
            ),
            "flags": list(GROUP_FLAG_NAMES),
            "common_workflows": {
                "vca_bus": [
                    "Create a track to act as the VCA fader (no audio routed).",
                    "set_track_group_membership(vca_track, 'VOLUME_VCA_LEAD', group=1, enabled=True)",
                    "For each follower: set_track_group_membership(track, 'VOLUME_VCA_FOLLOW', 1, True)",
                ],
                "mute_group": [
                    "For every track in the group: set_track_group_membership(track, 'MUTE_LEAD', group=2, enabled=True)",
                    "And: set_track_group_membership(track, 'MUTE_FOLLOW', group=2, enabled=True)",
                    "Now muting any one mutes them all.",
                ],
            },
            "limits": {
                "groups": "1-64",
                "tools_skip": (
                    "Group naming is a project-state-chunk feature without a "
                    "dedicated API call, so this module addresses groups by "
                    "number, not name. Use REAPER's GUI to label groups."
                ),
            },
        }

    @mcp.tool()
    def set_track_group_membership(
        track_index: int,
        flag: str,
        group_number: int,
        enabled: bool,
    ) -> dict:
        """Add or remove a track from a group for a specific flag.

        ``flag`` is one of the ``GROUP_FLAG_NAMES`` (e.g. ``"VOLUME_VCA_LEAD"``,
        ``"MUTE_FOLLOW"``). ``group_number`` is 1-64. ``enabled=True`` adds
        membership; ``False`` removes it.
        """
        from reapy import reascript_api as RPR

        try:
            _validate_flag(flag)
            _validate_group(int(group_number))
            project = get_project()
            track = project.tracks[track_index]
            mask, is_high = _flag_mask(int(group_number))
            if is_high:
                cur_high = int(RPR.GetSetTrackGroupMembershipHigh(track.id, flag, 0, 0))
                new_high = (cur_high | mask) if enabled else (cur_high & ~mask)
                RPR.GetSetTrackGroupMembershipHigh(track.id, flag, mask, new_high & mask)
            else:
                cur_low = int(RPR.GetSetTrackGroupMembership(track.id, flag, 0, 0))
                new_low = (cur_low | mask) if enabled else (cur_low & ~mask)
                RPR.GetSetTrackGroupMembership(track.id, flag, mask, new_low & mask)
            return {
                "success": True,
                "track_index": track_index,
                "flag": flag,
                "group_number": int(group_number),
                "enabled": bool(enabled),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_group_membership(track_index: int, flag: str) -> dict:
        """List every group number a track belongs to for a specific flag."""
        try:
            _validate_flag(flag)
            project = get_project()
            track = project.tracks[track_index]
            low, high = _read_membership(track.id, flag)
            groups = []
            for g in range(1, 65):
                mask, is_high = _flag_mask(g)
                if is_high and (high & mask) or (not is_high) and (low & mask):
                    groups.append(g)
            return {
                "success": True,
                "track_index": track_index,
                "flag": flag,
                "groups": groups,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_groups(track_index: int) -> dict:
        """Return every flag → group memberships for a track.

        Returns a dict like
        ``{"VOLUME_LEAD": [1, 4], "MUTE_FOLLOW": [2], ...}`` skipping flags
        with no memberships.
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            out: dict[str, list[int]] = {}
            for flag in GROUP_FLAG_NAMES:
                low, high = _read_membership(track.id, flag)
                groups = []
                for g in range(1, 65):
                    mask, is_high = _flag_mask(g)
                    if is_high and (high & mask) or (not is_high) and (low & mask):
                        groups.append(g)
                if groups:
                    out[flag] = groups
            return {
                "success": True,
                "track_index": track_index,
                "memberships": out,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_group_members(flag: str, group_number: int) -> dict:
        """List every track that is a member of ``group_number`` for ``flag``."""
        try:
            _validate_flag(flag)
            _validate_group(int(group_number))
            project = get_project()
            mask, is_high = _flag_mask(int(group_number))
            members = []
            for i in range(project.n_tracks):
                track = project.tracks[i]
                low, high = _read_membership(track.id, flag)
                if is_high and (high & mask) or (not is_high) and (low & mask):
                    members.append({"index": i, "name": track.name})
            return {
                "success": True,
                "flag": flag,
                "group_number": int(group_number),
                "members": members,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
