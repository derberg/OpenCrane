"""Helper structure for CRD identity extraction."""

from pydantic import BaseModel


class RootIdentity(BaseModel):
    """Represents the root identity keys from a Kubernetes CRD."""

    apiVersion: str
    kind: str
    name: str
    namespace: str | None = None