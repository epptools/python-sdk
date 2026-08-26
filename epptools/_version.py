"""Single source of the package version.

Kept in its own module so ``client`` can report it (RFC 8807 ``<loginSec:app>``) without importing
the package root, which imports ``client`` in turn.
"""

__version__ = "1.0.2"
