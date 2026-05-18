from __future__ import annotations

from dataclasses import dataclass


class ConversionActionQueryError(Exception):
    """Raised when conversion action queries fail."""


@dataclass(frozen=True)
class ConversionAction:
    id: int | None = None
    name: str = ""
    status: str = ""
    type: str = ""
    category: str = ""
    primary_for_goal: bool = False
    include_in_conversions_metric: bool = False
    default_value: float | None = None
    always_use_default_value: bool = False
    counting_type: str = ""
    attribution_model: str = ""


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if name:
        return name

    text = str(value or "")
    return text.rsplit(".", maxsplit=1)[-1]


def _conversion_action_from_row(row) -> ConversionAction:
    action = row.conversion_action
    value_settings = action.value_settings
    attribution_settings = action.attribution_model_settings

    return ConversionAction(
        id=getattr(action, "id", None),
        name=getattr(action, "name", ""),
        status=_enum_name(getattr(action, "status", "")),
        type=_enum_name(getattr(action, "type_", "")),
        category=_enum_name(getattr(action, "category", "")),
        primary_for_goal=getattr(action, "primary_for_goal", False),
        include_in_conversions_metric=getattr(action, "include_in_conversions_metric", False),
        default_value=getattr(value_settings, "default_value", None),
        always_use_default_value=getattr(value_settings, "always_use_default_value", False),
        counting_type=_enum_name(getattr(action, "counting_type", "")),
        attribution_model=_enum_name(getattr(attribution_settings, "attribution_model", "")),
    )


def fetch_conversion_actions(client, customer_id: str) -> list[ConversionAction]:
    queries = (
        """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.type,
          conversion_action.category,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value,
          conversion_action.counting_type,
          conversion_action.attribution_model_settings.attribution_model
        FROM conversion_action
        """,
        """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.type,
          conversion_action.category,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value,
          conversion_action.counting_type
        FROM conversion_action
        """,
        """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.type,
          conversion_action.category,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric
        FROM conversion_action
        """,
    )
    last_error: Exception | None = None

    for query in queries:
        try:
            ga_service = client.get_service("GoogleAdsService")
            response = ga_service.search_stream(customer_id=customer_id, query=query)
            actions: list[ConversionAction] = []

            for batch in response:
                for row in batch.results:
                    actions.append(_conversion_action_from_row(row))

            return actions
        except Exception as exc:
            last_error = exc

    raise ConversionActionQueryError(f"Conversion action query failed: {last_error}") from last_error
