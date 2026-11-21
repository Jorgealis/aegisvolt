"""Utilidades compartidas por los servicios de AegisVolt.

Se comparte el *patrón* (logs, flags, idempotencia), nunca los datos: cada
servicio sigue siendo dueño exclusivo de su tabla DynamoDB.
"""
