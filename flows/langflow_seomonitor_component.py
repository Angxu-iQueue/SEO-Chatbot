from __future__ import annotations

import requests
from langflow.custom import Component
from langflow.io import DropdownInput, IntInput, MessageTextInput, Output, SecretStrInput
from langflow.schema import Data

BASE_URL = "https://apigw.seomonitor.com/v3"

ENDPOINTS = {
    "Tracked campaigns": ("/dashboard/v3.0/campaigns/tracked", ()),
    "Keywords": ("/rank-tracker/v3.0/keywords", ("campaign_id", "search", "limit")),
    "Group daily visibility": (
        "/rank-tracker/v3.0/groups/daily-visibility",
        ("campaign_id", "start_date", "end_date"),
    ),
    "Topic overview": ("/research/v3.0/topic-overview", ("campaign_id", "keyword")),
    "Domain overview": ("/research/v3.0/domain-overview", ("campaign_id", "url")),
}


class SEOMonitorComponent(Component):
    display_name = "SEOmonitor"
    description = "Fetch live rankings, visibility and research data from SEOmonitor v3."
    icon = "trending-up"
    name = "SEOMonitor"

    inputs = [
        SecretStrInput(
            name="api_key",
            display_name="API token",
            info="Account Settings > Edit Profile > API Token. Raw token, no Bearer prefix.",
            required=True,
        ),
        DropdownInput(
            name="endpoint",
            display_name="Endpoint",
            options=list(ENDPOINTS),
            value="Keywords",
        ),
        IntInput(
            name="campaign_id",
            display_name="Campaign ID",
            tool_mode=True,
        ),
        MessageTextInput(
            name="query",
            display_name="Keyword or domain",
            info="Keyword for Topic overview, domain for Domain overview, "
            "substring filter for Keywords.",
            tool_mode=True,
        ),
        IntInput(name="limit", display_name="Row limit", value=50),
        MessageTextInput(name="start_date", display_name="Start date (YYYY-MM-DD)"),
        MessageTextInput(name="end_date", display_name="End date (YYYY-MM-DD)"),
    ]

    outputs = [Output(display_name="Data", name="data", method="fetch")]

    def fetch(self) -> Data:
        path, accepted = ENDPOINTS[self.endpoint]

        candidates = {
            "campaign_id": self.campaign_id,
            "limit": min(self.limit or 50, 1000),
            "search": self.query,
            "keyword": self.query,
            "url": self.query,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        params = {k: v for k, v in candidates.items() if k in accepted and v}

        response = requests.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={"Authorization": self.api_key, "Accept": "application/json"},
            timeout=30,
        )

        if response.status_code != 200:
            message = f"SEOmonitor {response.status_code}: {response.text[:200]}"
            self.status = message
            return Data(data={"error": message})

        payload = response.json()
        rows = len(payload) if isinstance(payload, list) else 1
        self.status = f"{self.endpoint}: {rows} row(s)"
        return Data(data={"endpoint": self.endpoint, "params": params, "result": payload})
