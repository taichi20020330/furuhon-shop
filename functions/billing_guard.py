"""請求の自動停止：予算を超えたら、このプロジェクトと請求先アカウントの紐づけを外す（＝有料サービスが止まる）。
予算（Google Cloud の「予算とアラート」）から Pub/Sub のトピック budget-alerts へ通知を送る設定が必要。docs/SECURITY.md 参照。"""
import json
import os

from firebase_functions import options, pubsub_fn


@pubsub_fn.on_message_published(topic="budget-alerts", region="asia-northeast1", memory=options.MemoryOption.MB_256)
def stop_billing(event: pubsub_fn.CloudEvent[pubsub_fn.MessagePublishedData]) -> None:
    data = event.data.message.json or {}
    cost, budget = data.get("costAmount", 0), data.get("budgetAmount", 0)
    print(f"budget notice: cost={cost} budget={budget}")
    if not budget or cost < budget:
        return
    import google.auth
    from googleapiclient import discovery

    project = os.environ.get("GCLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    creds, _ = google.auth.default()
    billing = discovery.build("cloudbilling", "v1", credentials=creds, cache_discovery=False)
    name = f"projects/{project}"
    info = billing.projects().getBillingInfo(name=name).execute()
    if not info.get("billingEnabled"):
        return
    billing.projects().updateBillingInfo(name=f"{name}", body={"billingAccountName": ""}).execute()
    print("billing disabled for", project)
