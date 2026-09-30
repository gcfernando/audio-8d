# Developed by ::> Gehan Fernando
"""Write-then-publish helpers so a half-encoded file is never visible."""

import os
import uuid
from pathlib import Path

from ..core.errors import ConversionError, InputValidationError


def create_temporary_output(output_file: Path) -> Path:
    """Pick a hidden, unique scratch name in the same folder as the destination."""
    # Same folder keeps the rename atomic; the real extension picks the container
    return output_file.with_name(
        f".{output_file.stem}.{uuid.uuid4().hex}.partial{output_file.suffix}"
    )


def _publish_without_overwrite(temporary_file: Path, output_file: Path) -> None:
    """Move the file into place, failing if something already sits there."""
    try:
        # A hard link fails if output_file appeared after validation, so no race
        os.link(temporary_file, output_file)
    except FileExistsError:
        # FileExistsError is also an OSError, so let it out before the fallback below
        raise
    except OSError:
        # FAT32/exFAT and some shares lack hard links; Windows rename never overwrites
        if os.name != "nt":
            raise
        os.rename(temporary_file, output_file)
        return

    # The hard link left two names for one file, so drop the scratch name
    temporary_file.unlink()


def commit_output(temporary_file: Path, output_file: Path, *, overwrite: bool) -> None:
    """Publish a finished encode under its real name."""
    try:
        if overwrite:
            os.replace(temporary_file, output_file)
        else:
            _publish_without_overwrite(temporary_file, output_file)
    except FileExistsError as exc:
        raise InputValidationError(
            f"Output appeared while conversion was running: {output_file}"
        ) from exc
    except OSError as exc:
        raise ConversionError(
            f"Unable to publish completed output to {output_file}: {exc}"
        ) from exc
