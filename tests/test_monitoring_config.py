"""The monitoring stack's files (docker/) stay in step with the app's metrics.

Prometheus and Grafana only find out about a renamed metric when an alert
silently stops firing or a panel goes blank, so check here that every
ragforge_* series they use is one app/core/metrics.py defines.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from prometheus_client import Counter, Histogram

from app.core import metrics

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ROOT / "docker"


def _defined_series() -> set[str]:
    names = set()
    for value in vars(metrics).values():
        if isinstance(value, Counter):
            names.add(f"{value._name}_total")
        elif isinstance(value, Histogram):
            names |= {f"{value._name}_bucket", f"{value._name}_sum", f"{value._name}_count"}
    names.add("ragforge_documents_queued")  # DocumentQueueCollector, at scrape time
    return names


def _series_in(expression: str) -> set[str]:
    return set(re.findall(r"\bragforge_[a-z_]+", expression))


def _alert_rules() -> list[dict]:
    config = yaml.safe_load((DOCKER / "prometheus" / "alerts.yml").read_text())
    return [rule for group in config["groups"] for rule in group["rules"]]


def test_every_alert_uses_defined_metrics_and_explains_itself():
    defined = _defined_series()
    rules = _alert_rules()
    assert len(rules) >= 7
    for rule in rules:
        assert rule["alert"].startswith("Ragforge"), rule
        used = _series_in(rule["expr"])
        assert used <= defined, f"{rule['alert']} uses undefined series {used - defined}"
        assert rule["labels"]["severity"] in ("critical", "warning")
        assert rule["annotations"]["summary"] and rule["annotations"]["description"]
    assert {r["alert"] for r in rules} >= {
        "RagforgeApiDown", "RagforgeWorkerDown", "RagforgeHighErrorRate", "RagforgeSlowRequests",
        "RagforgeLlmErrors", "RagforgeIndexingFailures", "RagforgeIndexingStalled",
    }


def test_alerts_on_scrape_targets_name_the_scraped_jobs():
    jobs = {c["job_name"] for c in yaml.safe_load((DOCKER / "prometheus" / "prometheus.yml").read_text())["scrape_configs"]}
    for rule in _alert_rules():
        for job in re.findall(r'job="([^"]+)"', rule["expr"]):
            assert job in jobs, f"{rule['alert']} refers to unknown job {job}"


def test_prometheus_loads_the_rules_and_sends_alerts_to_alertmanager():
    config = yaml.safe_load((DOCKER / "prometheus" / "prometheus.yml").read_text())
    assert config["rule_files"] == ["/etc/prometheus/alerts.yml"]
    assert config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == ["alertmanager:9093"]
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    assert "./docker/prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro" in services["prometheus"]["volumes"]
    assert services["alertmanager"]["profiles"] == ["observability"]
    assert services["alertmanager"]["ports"] == ["127.0.0.1:9093:9093"]  # never on a public interface

    alertmanager = yaml.safe_load((DOCKER / "alertmanager" / "alertmanager.yml").read_text())
    receivers = {r["name"] for r in alertmanager["receivers"]}
    assert alertmanager["route"]["receiver"] in receivers


def test_every_dashboard_panel_uses_defined_metrics():
    defined = _defined_series()
    dashboard = json.loads((DOCKER / "grafana" / "dashboards" / "ragforge.json").read_text())
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            used = _series_in(target["expr"])
            assert used <= defined, f"panel {panel['title']!r} uses undefined series {used - defined}"
    titles = [p["title"] for p in dashboard["panels"]]
    assert titles[1] == "Firing alerts"  # first thing on the dashboard
    positions = [(p["gridPos"]["x"], p["gridPos"]["y"]) for p in dashboard["panels"]]
    assert len(positions) == len(set(positions)), "two panels share a position"


def test_jaeger_keeps_traces_on_disk_in_a_volume():
    config = yaml.safe_load((DOCKER / "jaeger" / "config.yaml").read_text())
    backend = config["extensions"]["jaeger_storage"]["backends"]["badger_store"]["badger"]
    assert backend["ephemeral"] is False
    assert config["extensions"]["jaeger_query"]["storage"]["traces"] == "badger_store"
    assert config["exporters"]["jaeger_storage_exporter"]["trace_storage"] == "badger_store"
    # Listening on every interface: the api and worker containers send to jaeger:4318.
    assert config["receivers"]["otlp"]["protocols"]["http"]["endpoint"] == "0.0.0.0:4318"
    jaeger = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["jaeger"]
    assert "jaeger-data:/var/tmp" in jaeger["volumes"]
    for directory in backend["directories"].values():
        assert directory.startswith("/var/tmp/")


@pytest.mark.parametrize("name", ["prometheus", "alertmanager", "grafana", "jaeger"])
def test_monitoring_services_only_listen_on_localhost(name):
    service = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"][name]
    for port in service.get("ports", []):
        assert port.startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"
