from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    key: str
    label: str
    short_label: str
    dataset_id: str
    date_field: str
    neighborhood_field: str
    category_field: str | None
    section: str
    source_url: str
    notable_fields: tuple[str, ...] = ()
    editorial_weight: float = 1.0


SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(
        key="businesses",
        label="New business locations",
        short_label="New businesses",
        dataset_id="g8m3-pdis",
        date_field="location_start_date",
        neighborhood_field="neighborhoods_analysis_boundaries",
        category_field=None,
        section="Business Desk",
        source_url="https://data.sfgov.org/d/g8m3-pdis",
        notable_fields=(
            "dba_name",
            "ownership_name",
            "full_business_address",
            "location_start_date",
            "neighborhoods_analysis_boundaries",
        ),
        editorial_weight=1.30,
    ),
    SourceConfig(
        key="permits",
        label="Building permit filings",
        short_label="Permits filed",
        dataset_id="i98e-djp9",
        date_field="filed_date",
        neighborhood_field="neighborhoods_analysis_boundaries",
        category_field="permit_type_definition",
        section="Development & Housing",
        source_url="https://data.sfgov.org/d/i98e-djp9",
        notable_fields=(
            "permit_number",
            "permit_type_definition",
            "filed_date",
            "estimated_cost",
            "description",
            "status",
            "street_number",
            "street_name",
            "street_suffix",
            "existing_units",
            "proposed_units",
            "existing_use",
            "proposed_use",
            "neighborhoods_analysis_boundaries",
        ),
        editorial_weight=1.45,
    ),
    SourceConfig(
        key="service_requests",
        label="311 service requests",
        short_label="311 requests",
        dataset_id="vw6y-z8j6",
        date_field="requested_datetime",
        neighborhood_field="analysis_neighborhood",
        category_field="service_name",
        section="City Services",
        source_url="https://data.sfgov.org/d/vw6y-z8j6",
        notable_fields=(
            "service_request_id",
            "requested_datetime",
            "service_name",
            "service_subtype",
            "service_details",
            "address",
            "status_description",
            "analysis_neighborhood",
        ),
        editorial_weight=0.58,
    ),
    SourceConfig(
        key="police",
        label="Reported police incidents",
        short_label="Police incidents",
        dataset_id="wg3w-h783",
        date_field="incident_datetime",
        neighborhood_field="analysis_neighborhood",
        category_field="incident_category",
        section="Public Safety",
        source_url="https://data.sfgov.org/d/wg3w-h783",
        notable_fields=(
            "incident_datetime",
            "incident_category",
            "incident_subcategory",
            "incident_description",
            "intersection",
            "resolution",
            "analysis_neighborhood",
        ),
        editorial_weight=0.92,
    ),
)


ANALYSIS_NEIGHBORHOODS: tuple[str, ...] = (
    "Bayview Hunters Point",
    "Bernal Heights",
    "Castro/Upper Market",
    "Chinatown",
    "Excelsior",
    "Financial District/South Beach",
    "Glen Park",
    "Golden Gate Park",
    "Haight Ashbury",
    "Hayes Valley",
    "Inner Richmond",
    "Inner Sunset",
    "Japantown",
    "Lakeshore",
    "Lincoln Park",
    "Lone Mountain/USF",
    "Marina",
    "McLaren Park",
    "Mission",
    "Mission Bay",
    "Nob Hill",
    "Noe Valley",
    "North Beach",
    "Oceanview/Merced/Ingleside",
    "Outer Mission",
    "Outer Richmond",
    "Pacific Heights",
    "Portola",
    "Potrero Hill",
    "Presidio",
    "Presidio Heights",
    "Russian Hill",
    "Seacliff",
    "South of Market",
    "Sunset/Parkside",
    "Tenderloin",
    "Treasure Island",
    "Twin Peaks",
    "Visitacion Valley",
    "West of Twin Peaks",
    "Western Addition",
)
