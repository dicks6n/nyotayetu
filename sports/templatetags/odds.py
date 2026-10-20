from django import template

register = template.Library()


@register.filter
def mkt(odds, key):
    """{{ match.odds|mkt:"ou_2.5"|pk:"over" }} — safe lookups for keys with dots."""
    return (odds or {}).get(key) or {}


@register.filter
def pk(market, pick):
    return (market or {}).get(str(pick))
