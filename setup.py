#!/usr/bin/env python3

import os
from io import open

from setuptools import find_packages, setup


def read(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


version = __import__("deluge_utilities").__version__

setup(
    name="deluge-utilities",
    version=version,
    description="Is a set of utilities to help you work with Deluge.",
    long_description=read("README.md"),
    long_description_content_type="text/markdown",
    author="Ivan Vyalov",
    author_email="job@bnff.website",
    url="https://github.com/GitBib/deluge-utilities",
    download_url=f"https://github.com/GitBib/deluge-utilities/archive/{version}.zip",
    license="Apache License, Version 2.0, see LICENSE file",
    packages=find_packages(exclude=["tests", "testapp"]),
    install_requires=["setuptools", "deluge-client"],
    py_modules=["batch"],
    entry_points="""
    [console_scripts]
    deluge_utilities = batch:master
    """,
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Programming Language :: Python :: Implementation :: CPython",
    ],
)
