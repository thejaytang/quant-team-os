from __future__ import annotations

import json
import os

from superset import db, security_manager
from superset.app import create_app
from superset.connectors.sqla.models import SqlaTable, SqlMetric, TableColumn
from superset.models.core import Database
from superset.models.dashboard import Dashboard
from superset.models.slice import Slice

DASHBOARD_TITLE = "Strategy and Backtest Aggregate"
DASHBOARD_SLUG = "strategy-backtest-aggregate"
DATABASE_NAME = "quant_team_os"
DATASET_NAME = "qto_strategy_backtest_aggregate"
ANALYTICS_URI = os.getenv(
    "QTO_ANALYTICS_SQLALCHEMY_URI",
    "postgresql+psycopg2://qto_app:qto_app@postgres:5432/quant_team_os",
)

CHARTS = [
    ("Strategies by Status", "strategy_status"),
    ("Backtest Runs by Status", "backtest_status"),
    ("Risk Review Verdicts", "risk_verdict"),
    ("Factor Specs by Status", "factor_status"),
]

DATASET_SQL = """
select 'strategy_status' as metric_family, current_status as bucket, count(*) as record_count
from strategy_cards
group by current_status
union all
select 'backtest_status' as metric_family, status as bucket, count(*) as record_count
from backtest_runs
group by status
union all
select 'risk_verdict' as metric_family, verdict as bucket, count(*) as record_count
from risk_reviews
group by verdict
union all
select 'factor_status' as metric_family, status as bucket, count(*) as record_count
from factor_specs
group by status
""".strip()


def main() -> None:
    app = create_app()
    with app.app_context():
        admin = security_manager.find_user(username=os.getenv("SUPERSET_ADMIN_USERNAME", "admin"))
        database = db.session.query(Database).filter_by(database_name=DATABASE_NAME).one_or_none()
        if database is None:
            database = Database(database_name=DATABASE_NAME)
            db.session.add(database)
        database.set_sqlalchemy_uri(ANALYTICS_URI)
        database.expose_in_sqllab = True
        database.allow_dml = False
        database.extra = json.dumps({"allows_virtual_table_explore": True})
        db.session.flush()

        for dashboard in db.session.query(Dashboard).filter_by(dashboard_title=DASHBOARD_TITLE).all():
            dashboard.slices = []
            db.session.delete(dashboard)
        for chart in db.session.query(Slice).filter(Slice.slice_name.in_([name for name, _ in CHARTS])).all():
            db.session.delete(chart)
        dataset = (
            db.session.query(SqlaTable)
            .filter_by(database_id=database.id, table_name=DATASET_NAME)
            .one_or_none()
        )
        if dataset is not None:
            db.session.delete(dataset)
        db.session.flush()

        dataset = SqlaTable(
            table_name=DATASET_NAME,
            database=database,
            database_id=database.id,
            sql=DATASET_SQL,
            is_sqllab_view=True,
        )
        if admin:
            dataset.owners = [admin]
        dataset.columns = [
            TableColumn(column_name="metric_family", type="VARCHAR", groupby=True, filterable=True),
            TableColumn(column_name="bucket", type="VARCHAR", groupby=True, filterable=True),
            TableColumn(column_name="record_count", type="BIGINT", groupby=False, filterable=False),
        ]
        dataset.metrics = [
            SqlMetric(metric_name="sum__record_count", expression="SUM(record_count)", metric_type="sum"),
        ]
        db.session.add(dataset)
        db.session.flush()

        charts: list[Slice] = []
        for name, family in CHARTS:
            params = {
                "datasource": f"{dataset.id}__table",
                "viz_type": "dist_bar",
                "metrics": ["sum__record_count"],
                "groupby": ["bucket"],
                "adhoc_filters": [
                    {
                        "clause": "WHERE",
                        "expressionType": "SIMPLE",
                        "subject": "metric_family",
                        "operator": "==",
                        "comparator": family,
                    }
                ],
                "row_limit": 100,
                "show_legend": False,
                "x_axis_label": "Status",
                "y_axis_label": "Count",
                "time_range": "No filter",
            }
            chart = Slice(
                slice_name=name,
                datasource_id=dataset.id,
                datasource_type="table",
                datasource_name=dataset.table_name,
                viz_type="dist_bar",
                params=json.dumps(params),
            )
            if admin:
                chart.owners = [admin]
            db.session.add(chart)
            charts.append(chart)
        db.session.flush()

        for chart in charts:
            params = json.loads(chart.params)
            params["slice_id"] = chart.id
            chart.params = json.dumps(params)

        dashboard = Dashboard(
            dashboard_title=DASHBOARD_TITLE,
            slug=DASHBOARD_SLUG,
            published=True,
            json_metadata=json.dumps({"timed_refresh_immune_slices": [], "expanded_slices": {}}),
            position_json=json.dumps(_position(charts)),
            slices=charts,
        )
        if admin:
            dashboard.owners = [admin]
        db.session.add(dashboard)
        db.session.commit()
        print(f"seeded Superset dashboard: {DASHBOARD_TITLE}")


def _position(charts: list[Slice]) -> dict[str, object]:
    row_ids = ["ROW-0", "ROW-1"]
    chart_nodes = [f"CHART-{index}" for index, _chart in enumerate(charts)]
    position: dict[str, object] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"children": ["GRID_ID"], "id": "ROOT_ID", "type": "ROOT"},
        "GRID_ID": {"children": row_ids, "id": "GRID_ID", "parents": ["ROOT_ID"], "type": "GRID"},
        "HEADER_ID": {"id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}, "type": "HEADER"},
    }
    for row_index, row_id in enumerate(row_ids):
        children = chart_nodes[row_index * 2 : row_index * 2 + 2]
        position[row_id] = {
            "children": children,
            "id": row_id,
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": ["ROOT_ID", "GRID_ID"],
            "type": "ROW",
        }
    for node_id, chart in zip(chart_nodes, charts, strict=True):
        position[node_id] = {
            "children": [],
            "id": node_id,
            "meta": {
                "chartId": chart.id,
                "height": 50,
                "sliceName": chart.slice_name,
                "uuid": str(chart.uuid),
                "width": 6,
            },
            "parents": ["ROOT_ID", "GRID_ID", "ROW-0" if node_id in chart_nodes[:2] else "ROW-1"],
            "type": "CHART",
        }
    return position


if __name__ == "__main__":
    main()
