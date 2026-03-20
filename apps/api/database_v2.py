"""
DEPRECATED: This module has been merged into apps.api.database.

All functions previously in database_v2 now live in database.py.
This file re-exports them for backward compatibility only.
"""

from apps.api.database import (  # noqa: F401
    count_idea_cards,
    count_pain_points,
    create_context_bundle,
    create_domain,
    create_figure_asset,
    create_idea_card,
    create_pain_point,
    create_reading_path,
    get_context_bundle,
    get_domain,
    get_reading_path,
    list_domains,
    list_figures_by_paper,
    list_figures_by_run,
    list_idea_cards,
    list_pain_points,
    update_idea_card,
)
