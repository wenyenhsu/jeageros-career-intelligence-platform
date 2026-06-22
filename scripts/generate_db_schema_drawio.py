#!/usr/bin/env python3
"""Generate docs/db-schema.drawio with full field lists and orthogonal layout."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "db-schema.drawio"

ROW_H = 22
HEADER_H = 32
TABLE_W = 270
COL_GAP = 110
ROW_GAP = 40
START_X = 40
LEGEND_Y = 82
LEGEND_H = 96
START_Y = LEGEND_Y + LEGEND_H + 28

LEGEND_MODULES: list[tuple[str, str]] = [
    ("auth", "Auth"),
    ("imports", "Imports & crawl"),
    ("core", "Core entities"),
    ("child", "Application children"),
    ("hub", "SkillSet hub"),
    ("skill", "Skills & junctions"),
    ("analytics", "Analytics"),
    ("other", "Other / standalone"),
]


@dataclass(frozen=True)
class RoutingChannels:
    imports_core: float
    core_skill: float
    skill_sat: float
    sat_analytics: float
    top_bus: float
    right_core: float


def gap_after(col_x: float) -> float:
    return col_x + TABLE_W + COL_GAP / 2


class Column:
    """Stack tables vertically without overlap."""

    def __init__(self, builder: DrawioBuilder, x: float, start_y: float = START_Y) -> None:
        self.builder = builder
        self.x = x
        self.y = start_y

    def add(self, key: str, title: str, fields: list[str], theme: str = "core") -> None:
        self.builder.add_table(key, title, fields, self.x, self.y, theme)
        _x, _y, _w, height = self.builder.positions[key]
        self.y += height + ROW_GAP

    @property
    def bottom(self) -> float:
        return self.y


PALETTE = {
    "auth": ("#FFF4D6", "#C9A227"),
    "core": ("#DCEBFA", "#3B6FB6"),
    "hub": ("#BFE8CB", "#2E9B5B"),
    "skill": ("#EAF7EF", "#5BAF7A"),
    "analytics": ("#FFE8CC", "#E08A2E"),
    "imports": ("#FADADA", "#D45B5B"),
    "child": ("#EEF2F7", "#9AA8BC"),
    "other": ("#F5F5F5", "#888888"),
}


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def module_cell(theme: str, label: str) -> str:
    fill, stroke = PALETTE[theme]
    return (
        "<td style='padding:2px 10px 2px 0;white-space:nowrap;vertical-align:middle;'>"
        f"<span style='display:inline-block;width:14px;height:14px;background:{fill};"
        f"border:2px solid {stroke};border-radius:2px;vertical-align:middle;"
        f"margin-right:6px;'></span>{esc(label)}</td>"
    )


class DrawioBuilder:
    def __init__(self) -> None:
        self._id = 2
        self.table_cells: list[str] = []
        self.edge_cells: list[str] = []
        self.decor_cells: list[str] = []
        self.positions: dict[str, tuple[float, float, float, float]] = {}
        self.table_ids: dict[str, str] = {}

    def next_id(self) -> str:
        value = str(self._id)
        self._id += 1
        return value

    def add_table(
        self,
        key: str,
        title: str,
        fields: list[str],
        x: float,
        y: float,
        theme: str = "core",
    ) -> str:
        fill, stroke = PALETTE[theme]
        parent_id = self.next_id()
        height = HEADER_H + len(fields) * ROW_H
        self.positions[key] = (x, y, TABLE_W, height)
        self.table_ids[key] = parent_id

        self.table_cells.append(
            f"""
    <mxCell id="{parent_id}" value="{esc(title)}"
      style="swimlane;fontStyle=1;align=center;verticalAlign=top;childLayout=stackLayout;horizontal=1;startSize={HEADER_H};horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;marginBottom=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};fontColor=#1B2A41;strokeWidth=2;"
      vertex="1" parent="1">
      <mxGeometry x="{x}" y="{y}" width="{TABLE_W}" height="{height}" as="geometry"/>
    </mxCell>"""
        )

        for index, field in enumerate(fields):
            row_id = self.next_id()
            row_y = HEADER_H + index * ROW_H
            self.table_cells.append(
                f"""
    <mxCell id="{row_id}" value="{esc(field)}"
      style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=8;spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;whiteSpace=wrap;html=1;fontSize=11;fontColor=#2C3E50;"
      vertex="1" parent="{parent_id}">
      <mxGeometry y="{row_y}" width="{TABLE_W}" height="{ROW_H}" as="geometry"/>
    </mxCell>"""
            )

        return parent_id

    def center_y(self, key: str) -> float:
        _x, y, _w, h = self.positions[key]
        return y + h / 2

    def _exit_y_frac(self, source_key: str, target_cy: float) -> float:
        _sx, sy, _sw, sh = self.positions[source_key]
        return max(0.06, min(0.94, (target_cy - sy) / sh))

    def add_edge(
        self,
        source_key: str,
        target_key: str,
        label: str = "",
        dashed: bool = False,
        source_side: str = "right",
        target_side: str = "left",
        exit_y: float | None = None,
        entry_y: float | None = None,
        waypoints: list[tuple[float, float]] | None = None,
    ) -> None:
        edge_id = self.next_id()
        source_id = self.table_ids[source_key]
        target_id = self.table_ids[target_key]
        dash = "1" if dashed else "0"
        label_xml = ""
        if label:
            label_xml = (
                f'<mxCell id="{self.next_id()}" value="{esc(label)}" '
                'style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];'
                'fontSize=10;fontColor=#444444;labelBackgroundColor=#FFFFFF;" '
                f'vertex="1" connectable="0" parent="{edge_id}">'
                '<mxGeometry x="-0.1" relative="1" as="geometry"><mxPoint as="offset"/></mxGeometry></mxCell>'
            )

        exit_x = "1" if source_side == "right" else "0" if source_side == "left" else "0.5"
        default_exit_y = "1" if source_side == "bottom" else "0" if source_side == "top" else "0.5"
        entry_x = "0" if target_side == "left" else "1" if target_side == "right" else "0.5"
        default_entry_y = "0" if target_side == "top" else "1" if target_side == "bottom" else "0.5"
        exit_y_val = exit_y if exit_y is not None else default_exit_y
        entry_y_val = entry_y if entry_y is not None else default_entry_y

        points_xml = ""
        if waypoints:
            point_cells = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in waypoints)
            points_xml = f'<Array as="points">{point_cells}</Array>'

        self.edge_cells.append(
            f"""
    <mxCell id="{edge_id}" value="" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;strokeWidth=1.5;strokeColor=#5C6F8A;dashed={dash};exitX={exit_x};exitY={exit_y_val};exitPerimeter=1;entryX={entry_x};entryY={entry_y_val};entryPerimeter=1;"
      edge="1" parent="1" source="{source_id}" target="{target_id}">
      <mxGeometry relative="1" as="geometry">{points_xml}</mxGeometry>
      {label_xml}
    </mxCell>"""
        )

    def add_edge_via_gap(
        self,
        source_key: str,
        target_key: str,
        channel_x: float,
        label: str = "",
        dashed: bool = False,
        source_side: str = "right",
        target_side: str = "left",
    ) -> None:
        """Route only through the vertical corridor at channel_x (between columns)."""
        tgt_cy = self.center_y(target_key)
        src_cy = self.center_y(source_key)
        exit_y = self._exit_y_frac(source_key, tgt_cy) if source_side in {"left", "right"} else 0.5
        self.add_edge(
            source_key,
            target_key,
            label,
            dashed=dashed,
            source_side=source_side,
            target_side=target_side,
            exit_y=exit_y,
            entry_y=0.5,
            waypoints=[(channel_x, src_cy), (channel_x, tgt_cy)],
        )

    def add_edge_via_top_bus(
        self,
        source_key: str,
        target_key: str,
        channels: RoutingChannels,
        entry_channel_x: float,
        label: str = "",
        dashed: bool = False,
    ) -> None:
        """Skip intermediate columns by routing along the top bus (below legend, above tables)."""
        src_cy = self.center_y(source_key)
        tgt_cy = self.center_y(target_key)
        exit_channel = channels.skill_sat if source_key == "skillset" else gap_after(
            self.positions[source_key][0]
        )
        self.add_edge(
            source_key,
            target_key,
            label,
            dashed=dashed,
            source_side="right",
            target_side="left",
            exit_y=self._exit_y_frac(source_key, channels.top_bus),
            entry_y=0.5,
            waypoints=[
                (exit_channel, src_cy),
                (exit_channel, channels.top_bus),
                (entry_channel_x, channels.top_bus),
                (entry_channel_x, tgt_cy),
            ],
        )

    def add_edge_via_right(
        self,
        source_key: str,
        target_key: str,
        channel_x: float,
        label: str = "",
        dashed: bool = False,
    ) -> None:
        """Enter the target from its right edge via a corridor east of the core column."""
        src_cy = self.center_y(source_key)
        tgt_cy = self.center_y(target_key)
        self.add_edge(
            source_key,
            target_key,
            label,
            dashed=dashed,
            source_side="right",
            target_side="right",
            exit_y=0.5,
            entry_y=0.5,
            waypoints=[(channel_x, src_cy), (channel_x, tgt_cy)],
        )

    def add_legend(self, page_width: float) -> None:
        legend_w = page_width - 2 * START_X
        legend_x = START_X
        box_id = self.next_id()

        row1 = "".join(module_cell(theme, label) for theme, label in LEGEND_MODULES[:4])
        row2 = "".join(module_cell(theme, label) for theme, label in LEGEND_MODULES[4:])

        legend_html = (
            "<div style='font-family:Helvetica;font-size:11px;color:#1B2A41;'>"
            "<table style='width:100%;border-collapse:collapse;'>"
            "<tr><td colspan='4' style='font-weight:bold;font-size:12px;padding-bottom:4px;'>"
            "Module colors</td></tr>"
            f"<tr>{row1}</tr>"
            f"<tr>{row2}</tr>"
            "<tr><td colspan='4' style='font-weight:bold;font-size:12px;padding:10px 0 4px 0;'>"
            "Relationship labels</td></tr>"
            "<tr><td colspan='4' style='line-height:1.7;'>"
            "<span style='display:inline-block;min-width:170px;'><b>1:N</b> one-to-many (FK)</span>"
            "<span style='display:inline-block;min-width:120px;'><b>1:1</b> one-to-one</span>"
            "<span style='display:inline-block;min-width:210px;'><b>M:N</b> via junction table</span>"
            "<span style='display:inline-block;min-width:170px;'><b>N:1</b> junction → parent</span>"
            "<span style='display:inline-block;'><span style='color:#5C6F8A;'>- - -</span> "
            "optional / audit FK</span>"
            "</td></tr>"
            "</table></div>"
        )

        self.decor_cells.append(
            f"""
    <mxCell id="{box_id}" value="{esc(legend_html)}"
      style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FAFBFC;strokeColor=#CBD5E1;strokeWidth=1.5;align=left;verticalAlign=top;spacingLeft=14;spacingTop=10;spacingRight=14;spacingBottom=10;fontColor=#1B2A41;"
      vertex="1" parent="1">
      <mxGeometry x="{legend_x}" y="{LEGEND_Y}" width="{legend_w}" height="{LEGEND_H}" as="geometry"/>
    </mxCell>"""
        )

    def render(self, page_width: int = 2000, page_height: int = 3200) -> str:
        title_w = 720
        sub_w = min(page_width - 80, 980)
        title_x = (page_width - title_w) / 2
        sub_x = (page_width - sub_w) / 2
        # Edges first (behind), then tables and legend on top.
        body = "".join(self.edge_cells + self.decor_cells + self.table_cells)
        return f"""<mxfile host="app.diagrams.net" agent="generate_db_schema_drawio.py" version="22.1.0" type="device">
  <diagram id="jaegeros-db-schema-full" name="JägerOS DB Schema">
    <mxGraphModel dx="2200" dy="1400" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{page_width}" pageHeight="{page_height}" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="title" value="JägerOS Database Schema"
          style="text;html=1;fontSize=24;fontStyle=1;align=center;fontColor=#1B2A41;"
          vertex="1" parent="1">
          <mxGeometry x="{title_x}" y="20" width="{title_w}" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="subtitle" value="Full field list · routed via column corridors · edges drawn behind tables"
          style="text;html=1;fontSize=12;align=center;fontColor=#667788;"
          vertex="1" parent="1">
          <mxGeometry x="{sub_x}" y="58" width="{sub_w}" height="24" as="geometry"/>
        </mxCell>
        {body}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""


def main() -> None:
    b = DrawioBuilder()

    x_imports = START_X
    x_core = x_imports + TABLE_W + COL_GAP
    x_skill = x_core + TABLE_W + COL_GAP
    x_skill_sat = x_skill + TABLE_W + COL_GAP
    x_analytics = x_skill_sat + TABLE_W + COL_GAP

    channels = RoutingChannels(
        imports_core=gap_after(x_imports),
        core_skill=gap_after(x_core),
        skill_sat=gap_after(x_skill),
        sat_analytics=gap_after(x_skill_sat),
        top_bus=LEGEND_Y + LEGEND_H + 8,
        right_core=x_core + TABLE_W + 48,
    )

    col_imports = Column(b, x_imports)
    col_core = Column(b, x_core)
    col_skill = Column(b, x_skill)
    col_skill_sat = Column(b, x_skill_sat)
    col_analytics = Column(b, x_analytics)

    col_imports.add(
        "auth_user",
        "auth_user",
        ["id PK", "username", "email", "password", "is_staff", "is_active", "date_joined"],
        "auth",
    )
    col_imports.add(
        "jobsource",
        "imports_jobsource",
        [
            "id PK",
            "name",
            "resource (source_type)",
            "base_url",
            "enabled",
            "crawl_interval_minutes",
            "crawl_config JSON",
            "filter_config JSON",
            "last_crawled_at",
            "notes",
            "created_at",
            "updated_at",
        ],
        "imports",
    )
    col_imports.add(
        "crawlrun",
        "imports_crawlrun",
        [
            "id PK",
            "started_at",
            "finished_at",
            "total_sources",
            "processed_sources",
            "success_count",
            "failure_count",
            "current_source",
            "jobs_created / updated / closed",
            "errors",
            "status",
            "summary JSON",
        ],
        "imports",
    )
    col_imports.add(
        "pipelinelog",
        "imports_pipelinelog",
        [
            "id PK",
            "created_at",
            "service_name",
            "step_name",
            "status",
            "severity",
            "crawl_run_id FK → crawlrun",
            "source_id FK → jobsource",
            "job_id FK → jobpost",
            "company_id FK → company",
            "message",
            "metadata JSON",
            "error_text",
            "duration_ms",
        ],
        "imports",
    )
    col_imports.add(
        "jobarchiverun",
        "imports_jobarchiverun",
        [
            "id PK",
            "created_at",
            "cutoff_at",
            "age_months",
            "jobs_archived",
            "jobs_restored",
            "status",
            "payload JSON",
            "restored_at",
            "error_text",
        ],
        "imports",
    )

    col_core.add(
        "company",
        "companies_company",
        [
            "id PK",
            "name UK",
            "website",
            "industry",
            "location",
            "notes",
            "created_at",
            "updated_at",
        ],
        "core",
    )
    col_core.add(
        "jobpost",
        "jobs_jobpost",
        [
            "id PK",
            "company_id FK",
            "title",
            "source_url",
            "external_id",
            "source_type",
            "status",
            "location",
            "remote_type",
            "job_type",
            "employment_type",
            "salary_min / salary_max",
            "description",
            "tags (notes only)",
            "last_synced_at",
            "created_at",
            "updated_at",
        ],
        "core",
    )
    col_core.add(
        "application",
        "applications_application",
        [
            "id PK",
            "user_id FK",
            "job_post_id FK",
            "status",
            "applied_at",
            "priority",
            "referral",
            "last_updated_at",
            "created_at",
            "updated_at",
            "UNIQUE (user_id, job_post_id)",
        ],
        "core",
    )
    col_core.add(
        "statushistory",
        "applications_statushistory",
        [
            "id PK",
            "application_id FK",
            "old_status",
            "new_status",
            "changed_by_id FK → auth_user",
            "created_at",
            "updated_at",
        ],
        "child",
    )
    col_core.add(
        "interviewround",
        "interviews_interviewround",
        [
            "id PK",
            "application_id FK",
            "round_type",
            "scheduled_at",
            "interviewer",
            "outcome",
            "feedback",
            "created_at",
            "updated_at",
        ],
        "child",
    )
    col_core.add(
        "followuptask",
        "reminders_followuptask",
        [
            "id PK",
            "application_id FK",
            "task_type",
            "due_date",
            "completed",
            "notes",
            "created_at",
            "updated_at",
        ],
        "child",
    )

    col_skill.add(
        "skillset",
        "skills_skillset",
        [
            "id PK",
            "name UK",
            "normalized_name UK",
            "aliases JSON",
            "description",
            "esco_uri UK",
            "is_active",
            "auto_created",
            "embedding vector(1024)",
            "created_at",
            "updated_at",
        ],
        "hub",
    )
    col_skill.add(
        "jobpostskill",
        "skills_jobpostskill",
        [
            "id PK",
            "job_post_id FK",
            "skill_set_id FK",
            "score",
            "source_type",
            "extraction_metadata JSON",
            "created_at",
            "updated_at",
            "UNIQUE (job_post, skill_set)",
        ],
        "skill",
    )
    col_skill.add(
        "applicationskill",
        "skills_applicationskill",
        [
            "id PK",
            "application_id FK",
            "skill_set_id FK",
            "score",
            "source_type",
            "extraction_metadata JSON",
            "created_at",
            "updated_at",
            "UNIQUE (application, skill_set)",
        ],
        "skill",
    )

    col_skill_sat.add(
        "skillkeyword",
        "skills_skillkeyword",
        [
            "id PK",
            "skill_set_id FK",
            "raw_text",
            "normalized_text",
            "source",
            "status",
            "is_primary",
            "metadata JSON",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "skillalias",
        "skills_skillalias",
        [
            "id PK",
            "alias UK",
            "skill_id FK",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "skillcategory",
        "skills_skillcategory",
        [
            "id PK",
            "name",
            "normalized_name",
            "parent_id FK (self)",
            "esco_uri UK",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "skillrelationship",
        "skills_skillrelationship",
        [
            "id PK",
            "source_skill_id FK",
            "target_skill_id FK",
            "relationship_type",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "businesscategory",
        "skills_businesscategory",
        [
            "id PK",
            "name",
            "slug UK",
            "description",
            "parent_id FK (self)",
            "is_active",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "skillbusinesscategory",
        "skills_skillbusinesscategory",
        [
            "id PK",
            "skill_id FK",
            "category_id FK",
            "source",
            "is_approved",
            "confidence",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "marketcategory",
        "skills_marketcategory",
        [
            "id PK",
            "name",
            "slug UK",
            "description",
            "parent_id FK (self)",
            "is_active",
            "created_at",
            "updated_at",
        ],
        "skill",
    )
    col_skill_sat.add(
        "skillmarketcategory",
        "skills_skillmarketcategory",
        [
            "id PK",
            "skill_id FK",
            "category_id FK",
            "source",
            "is_approved",
            "confidence",
            "created_at",
            "updated_at",
        ],
        "skill",
    )

    col_analytics.add(
        "skilldemand",
        "analytics_skilldemand",
        [
            "id PK",
            "skill_id FK (1:1)",
            "total_occurrences",
            "unique_jobs",
            "first_seen",
            "last_seen",
            "rolling_30_day_count",
            "rolling_90_day_count",
            "demand_score",
            "created_at",
            "updated_at",
        ],
        "analytics",
    )
    col_analytics.add(
        "skilltrend",
        "analytics_skilltrend",
        [
            "id PK",
            "skill_id FK (1:1)",
            "trend_type",
            "growth_ratio",
            "created_at",
            "updated_at",
        ],
        "analytics",
    )
    col_analytics.add(
        "skillcandidate",
        "analytics_skillcandidate",
        [
            "id PK",
            "name",
            "normalized_name UK",
            "occurrence_count",
            "first_seen",
            "source",
            "reviewed",
            "flagged_for_review",
            "created_at",
            "updated_at",
        ],
        "other",
    )
    col_analytics.add(
        "notification",
        "notifications_notification",
        [
            "id PK",
            "title",
            "body",
            "is_read",
            "created_at",
            "updated_at",
        ],
        "other",
    )

    page_width = int(x_analytics + TABLE_W + START_X)
    page_height = int(
        max(
            col_imports.bottom,
            col_core.bottom,
            col_skill.bottom,
            col_skill_sat.bottom,
            col_analytics.bottom,
        )
        + 80
    )

    b.add_legend(page_width)

    # Core chain — vertical within column
    b.add_edge("company", "jobpost", "1:N", source_side="bottom", target_side="top")
    b.add_edge("jobpost", "application", "1:N", source_side="bottom", target_side="top")
    b.add_edge("application", "statushistory", "1:N", source_side="bottom", target_side="top")
    b.add_edge("application", "interviewround", "1:N", source_side="bottom", target_side="top")
    b.add_edge("application", "followuptask", "1:N", source_side="bottom", target_side="top")

    # Auth → core (right corridor, east of core column)
    b.add_edge_via_right("auth_user", "application", channels.right_core, "1:N")
    b.add_edge_via_right("auth_user", "statushistory", channels.right_core, "FK changed_by", dashed=True)

    # Core ↔ skills junctions (column gap corridors)
    b.add_edge_via_gap("jobpost", "jobpostskill", channels.core_skill, "M:N")
    b.add_edge_via_gap("application", "applicationskill", channels.core_skill, "M:N")
    b.add_edge("skillset", "jobpostskill", "N:1", source_side="bottom", target_side="top")
    b.add_edge("skillset", "applicationskill", "N:1", source_side="bottom", target_side="top")

    # Skill satellites — corridor between skill and skill_sat columns
    for target, label in (
        ("skillkeyword", "1:N"),
        ("skillalias", "1:N"),
        ("skillcategory", "1:N"),
        ("skillrelationship", "1:N"),
        ("skillbusinesscategory", "M:N"),
        ("skillmarketcategory", "M:N"),
    ):
        b.add_edge_via_gap("skillset", target, channels.skill_sat, label)

    # Category → junction (vertical stack, same column)
    b.add_edge("businesscategory", "skillbusinesscategory", "N:1", source_side="bottom", target_side="top")
    b.add_edge("marketcategory", "skillmarketcategory", "N:1", source_side="bottom", target_side="top")

    # Analytics — top bus avoids crossing skill_sat tables
    b.add_edge_via_top_bus("skillset", "skilldemand", channels, channels.sat_analytics, "1:1")
    b.add_edge_via_top_bus("skillset", "skilltrend", channels, channels.sat_analytics, "1:1")

    # Imports internal
    b.add_edge("crawlrun", "pipelinelog", "1:N", source_side="bottom", target_side="top")
    b.add_edge("jobsource", "pipelinelog", "1:N", source_side="bottom", target_side="top")
    b.add_edge_via_gap("pipelinelog", "jobpost", channels.imports_core, "optional FK", dashed=True)
    b.add_edge_via_gap("pipelinelog", "company", channels.imports_core, "optional FK", dashed=True)

    OUT.write_text(b.render(page_width=page_width, page_height=page_height), encoding="utf-8")
    print(f"Wrote {OUT} ({page_width}×{page_height})")


if __name__ == "__main__":
    main()
