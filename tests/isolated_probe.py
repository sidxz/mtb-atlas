"""A stage for `pipeline._isolated` to run: it says which process it ran in."""

import os
from pathlib import Path


def build(**kwargs: object) -> Path:
    return Path(f"/{os.getpid()}/{','.join(f'{k}={v}' for k, v in sorted(kwargs.items()))}")
