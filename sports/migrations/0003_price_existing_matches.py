from django.db import migrations


def price_existing(apps, schema_editor):
    """Fit the goal model and build the full price book for matches created before live markets existed."""
    from sports import markets
    Match = apps.get_model("sports", "Match")
    for m in Match.objects.filter(status__in=["upcoming", "live"], lambda_home__isnull=True):
        try:
            m.lambda_home, m.lambda_away = markets.lambdas_from_odds(m.home_odds, m.draw_odds, m.away_odds)
        except (ZeroDivisionError, ValueError, TypeError):
            continue
        m.odds = markets.price(m.lambda_home, m.lambda_away)
        m.save(update_fields=["lambda_home", "lambda_away", "odds"])


class Migration(migrations.Migration):
    dependencies = [("sports", "0002_live_and_markets")]
    operations = [migrations.RunPython(price_existing, migrations.RunPython.noop)]
