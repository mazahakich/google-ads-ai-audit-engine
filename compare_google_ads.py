import os
from dotenv import load_dotenv

load_dotenv()

from google.ads.googleads.client import GoogleAdsClient
from collections import defaultdict
from datetime import datetime, timedelta

config = {
    "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
    "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
    "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
    "login_customer_id": os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
    "use_proto_plus": True,
}

client = GoogleAdsClient.load_from_dict(config)

customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID")

ga_service = client.get_service("GoogleAdsService")

query = """
    SELECT
      campaign.name,
      segments.date,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM campaign
    WHERE segments.date DURING LAST_14_DAYS
"""

response = ga_service.search_stream(
    customer_id=customer_id,
    query=query
)

today = datetime.today().date()

last_7_start = today - timedelta(days=7)
prev_7_start = today - timedelta(days=14)

campaign_data = defaultdict(lambda: {
    "last7_cost": 0,
    "last7_conv": 0,
    "last7_value": 0,
    "prev7_cost": 0,
    "prev7_conv": 0,
    "prev7_value": 0,
})

for batch in response:
    for row in batch.results:

        campaign = row.campaign.name
        date = datetime.strptime(
    str(row.segments.date),
    "%Y-%m-%d"
).date()

        cost = row.metrics.cost_micros / 1_000_000
        conv = row.metrics.conversions
        value = row.metrics.conversions_value

        if date >= last_7_start:
            campaign_data[campaign]["last7_cost"] += cost
            campaign_data[campaign]["last7_conv"] += conv
            campaign_data[campaign]["last7_value"] += value

        elif date >= prev_7_start:
            campaign_data[campaign]["prev7_cost"] += cost
            campaign_data[campaign]["prev7_conv"] += conv
            campaign_data[campaign]["prev7_value"] += value

print("\nCAMPAIGN COMPARISON\n")
print("Campaign | Cost Δ | Conv Δ | ROAS Δ")
print("-" * 80)

for campaign, data in campaign_data.items():

    last_roas = (
        data["last7_value"] / data["last7_cost"]
        if data["last7_cost"] > 0 else 0
    )

    prev_roas = (
        data["prev7_value"] / data["prev7_cost"]
        if data["prev7_cost"] > 0 else 0
    )

    cost_change = data["last7_cost"] - data["prev7_cost"]
    conv_change = data["last7_conv"] - data["prev7_conv"]
    roas_change = last_roas - prev_roas

    print(
        f"{campaign} | "
        f"{cost_change:.2f} | "
        f"{conv_change:.2f} | "
        f"{roas_change:.2f}"
    )

    issues = []

if cost_change > 20:
    issues.append("Spend increased but conversions did not grow")

if roas_change < -0.2:
    issues.append("ROAS decreased significantly")

if data["last7_cost"] > 50 and data["last7_conv"] == 0:
    issues.append("Spent money without conversions")

if conv_change < -5:
    issues.append("Conversions dropped")

if issues:
    print("  ALERTS:")
    for issue in issues:
        print(f"   - {issue}")

findings = []
if issues:
    findings.append({
        "campaign": campaign,
        "cost_change": round(cost_change, 2),
        "conv_change": round(conv_change, 2),
        "roas_change": round(roas_change, 2),
        "issues": issues
    })
import json

print("\nAI FINDINGS JSON\n")
print(json.dumps(findings, indent=2))

from anthropic import Anthropic

if findings:
    anthropic_client = Anthropic()

    prompt = f"""
You are a senior Google Ads auditor.

Analyze the structured Google Ads audit findings below.
Use only the provided data. Do not invent numbers.
For each issue, explain:
1. What happened
2. Why it matters
3. Recommended action
4. Priority

Client context:
- Business type: ecommerce / lead generation
- Period comparison: last 7 days vs previous 7 days

Findings JSON:
{json.dumps(findings, indent=2)}
"""

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    print("\nCLAUDE AUDIT SUMMARY\n")
    print(message.content[0].text)
else:
    print("\nNo critical findings detected. Claude summary skipped.")
