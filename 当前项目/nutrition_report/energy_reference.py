"""Explicit BMR reference interval; never infer a midpoint or expand its bounds."""
import math


def bmr_bounds(user):
    raw = [user.get('bmrMin'), user.get('bmrMax')]
    if all(v is None or str(v).strip() == '' for v in raw):
        return None
    try:
        low, high = map(float, raw)
    except (TypeError, ValueError) as error:
        raise ValueError('BMR最低值和最高值须同时填写有效正数') from error
    if not (math.isfinite(low) and math.isfinite(high) and 0 < low <= high):
        raise ValueError('BMR区间须为有限正数，且最低值不得超过最高值')
    return low, high


def energy_reference_text(energy):
    if energy.get('reference_type') == 'bmr':
        return f"{energy['standard_min']:g}-{energy['standard_max']:g}"
    value = energy.get('standard')
    return str(value) if value not in (None, '') else '-'
