"""Powertools singletons, importable without circular app <-> handler imports."""

from aws_lambda_powertools import Logger, Metrics, Tracer

logger = Logger()
tracer = Tracer()
metrics = Metrics()
