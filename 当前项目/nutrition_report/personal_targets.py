"""Joint numerical validation, separate from original rules and release approval.

80/5/15 and 70/30 are inequalities, not forced allocation endpoints. A numerical
solution is not a new normative range or an approved practical prescription.
"""
import math


NUTRIENTS = ('energy', 'protein', 'carbohydrate', 'fat')
REPRESENTATIVES = {
    'grains_remainder': ('谷类', '米饭'), 'beans_energy': ('豆类', '豆腐'),
    'tubers_energy': ('薯类', '土豆'), 'livestock_remainder': ('畜禽肉', '牛肉'),
    'seafood': ('水产品', '海白虾'), 'milk': ('奶类', '鲜奶'),
    'eggs': ('蛋类', '蛋类'), 'vegetables': ('蔬菜', '白菜'),
    'fruit': ('水果', '苹果'), 'nuts': ('坚果', '核桃仁'),
}
STAPLE_SHARES = {'grains_remainder': .80, 'beans_energy': .05, 'tubers_energy': .15}


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def energy_bounds(energy):
    """Use interval reference (resting + net if applicable), otherwise personal EER."""
    if energy.get('reference_type') in {'bmr', 'bmr_plus_net', 'tdee'}:
        low, high = positive(energy.get('standard_min')), positive(energy.get('standard_max'))
        return (low, high) if low is not None and high is not None else (None, None)
    value = positive(energy.get('standard'))
    return value, value


def build_personal_targets(athlete, standard, food_db, energy=None, config=None):
    """One validated joint food plan; never a carbohydrate/protein-only projection."""
    import copy, json
    # Cache only immutable requirement/rule/density snapshots, never intake or
    # manual output. API changes therefore create a different cache key.
    fields=('target_min','target_max','target_planning')
    a={'targets_applicable':athlete.get('targets_applicable'),
       'rows':[{'key':r['key'],**{f:r.get(f) for f in fields}} for r in athlete['rows']]}
    s={'rows':[{'key':r['key'],'target_min':r.get('target_min'),'target_max':r.get('target_max')} for r in standard['rows']]}
    db={name:food_db.get(name,{}) for _,name in REPRESENTATIVES.values()}
    e={k:(energy or {}).get(k) for k in ('reference_type','standard','standard_min','standard_max','standard_source','standard_note')}
    payload=json.dumps([a,s,db,e,{'fat_energy_percent':(config or {}).get('fat_energy_percent',[20,30])}],sort_keys=True,ensure_ascii=False)
    return copy.deepcopy(_cached_joint_plan(payload))

from functools import lru_cache
@lru_cache(maxsize=256)
def _cached_joint_plan(payload):
    import json
    from .joint_plan import build_joint_plan
    return build_joint_plan(*json.loads(payload))
