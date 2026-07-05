"""Powertools singletons, importable without circular app <-> handler imports."""

from aws_lambda_powertools import Logger, Metrics, Tracer

from comments.settings import get_observability_settings

_settings = get_observability_settings()

logger = Logger(service=_settings.service_name)
tracer = Tracer(service=_settings.service_name)
metrics = Metrics(namespace=_settings.metrics_namespace, service=_settings.service_name)
