"""Multi-vendor access-driver layer.

``get_driver(device)`` returns the right :class:`AccessDriver` for a device by its
``vendor`` field; the cloud command handlers and the per-device event supervisor
call drivers instead of importing vendor-specific services directly.
"""

from app.drivers.base import AccessDriver
from app.drivers.registry import get_driver, register_driver
from app.drivers.dahua import DahuaDriver
from app.drivers.hikvision import HikvisionDriver

# Register built-in vendor drivers at import time (registration is pure, no I/O).
# vendor NULL / unknown still falls through to the GenericHttpDriver default.
register_driver("dahua", DahuaDriver())
register_driver("hikvision", HikvisionDriver())

__all__ = ["AccessDriver", "DahuaDriver", "HikvisionDriver", "get_driver", "register_driver"]
