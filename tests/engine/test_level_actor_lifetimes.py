from copy import deepcopy

from arknights_unpacker.extraction.level_actor_lifetimes import _reveal_mode


def test_reveal_requires_owner_switch_and_non_goal_retirement():
    template = {'eventToActions': {
        'ON_BUFF_START': [{
            '$type': 'Torappu.Battle.Action.Nodes+SwitchMode, Assembly-CSharp',
            '_modeIndex': 1, '_loadModeFromBlackboard': False, '_restoreDefault': False,
            '_restartFSM': True, '_targetType': 'BUFF_OWNER',
        }],
        'ON_BUFF_FINISH': [
            {'$type': 'Torappu.Battle.Action.Nodes+IfTarget, Assembly-CSharp', '_targetType': 'BUFF_OWNER',
             '_motionMask': 'ALL', '_checkTargetAlive': True, '_checkApplyWay': False,
             '_checkTargetUnitType': False, '_unitType': 'ENEMY', '_applyWay': 'NONE',
             '_checkTargetFree': False, '_checkMotionTargetFree': False},
            {'$type': 'Torappu.Battle.Action.Nodes+InstantKill, Assembly-CSharp', '_targetType': 'BUFF_OWNER',
             '_killSource': False, '_noSource': False, '_withdrawIfRallyPoint': False,
             '_resultIfInRallyPointMode': False, '_skipReborn': False, '_noReason': False,
             '_markReachExit': False, '_switchState': False},
        ],
    }}
    assert _reveal_mode(template) == 1
    altered = deepcopy(template)
    altered['eventToActions']['ON_BUFF_FINISH'][1]['_markReachExit'] = True
    assert _reveal_mode(altered) is None
    altered = deepcopy(template)
    altered['eventToActions']['ON_BUFF_FINISH'][0]['_checkTargetUnitType'] = True
    assert _reveal_mode(altered) is None
