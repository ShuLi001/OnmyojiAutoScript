"""Inventory differences; absent observations are never zero-filled."""
from datetime import date, datetime, timedelta

from tasks.AssetSnapshot.repository import STATISTICS_TZ, parse_time


def valid(item):
    return bool(item and type(item.get("quantity")) is int and item.get("source") == "observed" and item.get("observedAt")
                and item.get("precision") in {"exact", "display_quantized"})


def change(before, after):
    result = {"status": "no_baseline", "delta": None, "approximate": False}
    if not valid(after):
        result["status"] = (after or {}).get("source", "not_observed")
    elif valid(before):
        result.update(status="ok", delta=after["quantity"] - before["quantity"],
                      approximate=any(x.get("precision") != "exact" for x in (before, after)),
                      fromValue=before["quantity"], toValue=after["quantity"],
                      fromObservedAt=before["observedAt"], toObservedAt=after["observedAt"])
    return result


def history(documents, asset, report_date=None, days=7):
    end = date.fromisoformat(report_date) if report_date else datetime.now(STATISTICS_TZ).date()
    start = end - timedelta(days=days - 1)
    baseline = start - timedelta(days=1)
    closes, observations = {}, []
    for doc in documents:
        item = doc["snapshot"].get("assets", {}).get(asset)
        if not valid(item):
            continue
        stamp = parse_time(item["observedAt"])
        day = stamp.astimezone(STATISTICS_TZ).date()
        if baseline <= day <= end:
            closes[day] = item
            if start <= day:
                observations.append(item)
    daily = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        item, prev = closes.get(day), closes.get(day - timedelta(days=1))
        diff = change(prev, item)
        daily.append({"date": day.isoformat(), "closeValue": item["quantity"] if item else None,
                      "closeObservedAt": item.get("observedAt") if item else None,
                      "fromObservedAt": diff.get("fromObservedAt"),
                      "delta": diff["delta"], "approximate": diff["approximate"],
                      "status": "ok" if diff["delta"] is not None else "missing"})
    complete = change(closes.get(baseline), closes.get(end))
    partial = change(observations[0], observations[-1]) if len(observations) > 1 else change(None, None)
    missing = [d["date"] for d in daily if d["closeValue"] is None]
    summary = {**complete, "netChange": complete["delta"],
               "status": "complete" if complete["delta"] is not None else "partial" if partial["delta"] is not None else "insufficient",
               "partialChange": partial, "observedDayCount": days - len(missing),
               "comparableDayCount": sum(d["delta"] is not None for d in daily),
               "missingDates": missing, "hasGaps": bool(missing),
               "fullScanCompletedAt": documents[-1].get("fullScanCompletedAt") if documents else None}
    return {"asset": asset, "window": {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "reportDate": end.isoformat(), "timezone": "UTC+08:00",
            "asOfSnapshotId": documents[-1]["snapshotId"] if documents else None,
            "todayProvisional": end == datetime.now(STATISTICS_TZ).date()}, "daily": daily, "summary": summary}


def latest_payload(documents, identity_id, compare="previous", report_date=None):
    report_date = report_date or datetime.now(STATISTICS_TZ).date().isoformat()
    if not documents:
        return {"status": "unavailable", "values": {}, "identityId": identity_id,
                "message": "暂无资产快照，点击刷新资产执行一次采集。"}
    doc = documents[-1]
    snapshot = dict(doc["snapshot"])
    previous = documents[-2]["snapshot"].get("assets", {}) if len(documents) > 1 else {}
    assets = {}
    for key, quantity in snapshot["values"].items():
        item = dict(snapshot.get("assets", {}).get(key, {"source": "legacy_unknown", "precision": "unknown"}))
        item.setdefault("quantity", quantity)
        item["change"] = (history(documents, key, report_date)["summary"] if compare == "seven_days"
                          else change(previous.get(key), item))
        if compare == "seven_days":
            item["change"]["delta"] = item["change"]["netChange"]
        assets[key] = item
    snapshot.update(schemaVersion=2, snapshotId=doc["snapshotId"], identityId=identity_id,
                    reportDate=report_date, statisticsTimezone="UTC+08:00", assets=assets,
                    lastCategory=doc["lastCategory"], fullScanCompletedAt=doc["fullScanCompletedAt"],
                    comparison={"mode": compare, "toSnapshotId": doc["snapshotId"],
                                "fromSnapshotId": documents[-2]["snapshotId"] if len(documents) > 1 else None})
    return snapshot
