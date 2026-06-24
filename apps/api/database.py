"""Compatibility facade for database access.

Concrete implementations live under apps.api.db.*. Keep this module as the
stable import path for API routes, workers, services, and tests.
"""

from apps.api.db.events import count_events, create_event, list_events
from apps.api.db.pool import (
    close_pool,
    get_pool,
    init_pool,
    record_to_dict as _record_to_dict,
)
from apps.api.db.results import (
    count_idea_cards,
    count_pain_points,
    count_papers_by_run,
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
    list_hypotheses,
    list_idea_cards,
    list_pain_points,
    list_papers_by_run,
    update_idea_card,
)
from apps.api.db.runs import (
    count_runs,
    count_runs_by_status,
    create_run,
    delete_run,
    get_run,
    list_runs,
    update_run,
)

__all__ = [
    "_record_to_dict",
    "close_pool",
    "count_events",
    "count_idea_cards",
    "count_pain_points",
    "count_papers_by_run",
    "count_runs",
    "count_runs_by_status",
    "create_context_bundle",
    "create_domain",
    "create_event",
    "create_figure_asset",
    "create_idea_card",
    "create_pain_point",
    "create_reading_path",
    "create_run",
    "delete_run",
    "get_context_bundle",
    "get_domain",
    "get_pool",
    "get_reading_path",
    "get_run",
    "init_pool",
    "list_domains",
    "list_events",
    "list_figures_by_paper",
    "list_figures_by_run",
    "list_hypotheses",
    "list_idea_cards",
    "list_pain_points",
    "list_papers_by_run",
    "list_runs",
    "update_idea_card",
    "update_run",
]
