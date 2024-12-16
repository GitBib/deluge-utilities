"""
:authors: GitBib
:license: Apache License, Version 2.0, see LICENSE file
:copyright: (c) 2022 GitBib
"""

from .deluge import Deluge

VERSION = (0, 0, 4)
__version__ = ".".join(map(str, VERSION))

__author__ = "GitBib"
__email__ = "job@bnff.website"

__all__ = ["Deluge"]
